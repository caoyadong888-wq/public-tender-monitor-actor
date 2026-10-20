"""AusTender. Experimental: the official OCDS API publishes contract notices only.

The current-ATM RSS feed is requested with a plain GET. When that feed is
blocked, open tenders are not scraped from the HTML site. Contract notices are
returned only when openOnly is false, and they are still labelled source
austender. With openOnly true (the default) this source returns no items.
"""

from __future__ import annotations

from datetime import timedelta

from src.context import FetchContext, SourceOutcome
from src.http_client import SourceHTTPError
from src.ocds import austender_contract_partial
from src.sources._paging import accept_partial, collect_ocds_pages

ATM_RSS = "https://www.tenders.gov.au/public_data/rss/rss.xml"
CONTRACT_URL = (
    "https://api.tenders.gov.au/ocds/findByDates/contractPublished/{start}/{end}"
)


def _window(ctx: FetchContext) -> tuple[str, str]:
    end = ctx.now.strftime("%Y-%m-%dT%H:%M:%SZ")
    start = (ctx.now - timedelta(days=min(ctx.published_within_days, 7))).strftime("%Y-%m-%dT%H:%M:%SZ")
    return start, end


async def _probe_open_feed(ctx: FetchContext) -> str:
    try:
        response = await ctx.client.request("austender", "GET", ATM_RSS)
    except SourceHTTPError as exc:
        return f"open ATM feed {ATM_RSS} {exc}"
    except Exception as exc:
        return f"open ATM feed {ATM_RSS} {type(exc).__name__}: {exc}"
    body = response.text[:500].lower()
    if "<rss" in body or "<item" in body:
        return "open"
    return f"open ATM feed {ATM_RSS} HTTP {response.status_code} but body was not an RSS feed"


async def _probe_contract_api(ctx: FetchContext) -> str:
    start, end = _window(ctx)
    url = CONTRACT_URL.format(start=start, end=end)
    try:
        response = await ctx.client.request("austender", "GET", url)
    except SourceHTTPError as exc:
        return str(exc)
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    try:
        count = len((response.json().get("releases") or []))
    except Exception:
        count = 0
    return (
        f"OCDS contractPublished HTTP {response.status_code} "
        f"({count} contract notices on the first page; not open tenders)"
    )


async def fetch(ctx: FetchContext) -> SourceOutcome:
    feed = await _probe_open_feed(ctx)
    if feed == "open":
        # The RSS probe succeeded. Parsing is intentionally not invented here:
        # a real RSS body would be handled below if the feed starts returning items.
        # Re-request is avoided; the probe already consumed the body. Callers that
        # reach this branch need the items, so fetch again through the client gap.
        try:
            response = await ctx.client.request("austender", "GET", ATM_RSS)
            items = _items_from_rss(response.text, ctx)
        except SourceHTTPError as exc:
            return SourceOutcome([], "error", str(exc))
        if items:
            return SourceOutcome(items, "ok", None)
        return SourceOutcome([], "empty", "AusTender ATM RSS contained no matching items")
    contract_note = await _probe_contract_api(ctx)
    if ctx.open_only:
        reason = (
            f"{feed}. Official OCDS date types are contractPublished, "
            "contractLastModified, contractStart, and contractEnd. "
            f"{contract_note}. openOnly=true, so contract notices were not returned."
        )
        ctx.log.warning("austender: %s", reason)
        return SourceOutcome([], "empty", reason)
    start, end = _window(ctx)
    url = CONTRACT_URL.format(start=start, end=end)
    outcome = await collect_ocds_pages(
        ctx,
        source="austender",
        url=url,
        params=None,
        parse_release=austender_contract_partial,
        empty_reason="AusTender contractPublished returned no matching contract notices",
    )
    note = (
        "experimental: these are AusTender contract notices, not open approaches to market. "
        + feed
    )
    if outcome.reason:
        outcome.reason = note + " " + outcome.reason
    else:
        outcome.reason = note
    if outcome.status == "ok":
        outcome.status = "experimental"
    return outcome


def _items_from_rss(xml_text: str, ctx: FetchContext) -> list[dict]:
    """Parse a plain RSS 2.0 ATM feed if one is ever returned. No HTML scraping."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: list[dict] = []
    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        description = node.findtext("description") or ""
        published = node.findtext("pubDate") or node.findtext("date")
        if published:
            try:
                from email.utils import parsedate_to_datetime

                published = parsedate_to_datetime(published).isoformat()
            except (TypeError, ValueError, IndexError, OverflowError):
                pass
        partial = {
            "title": title,
            "buyer": None,
            "country": "AUS",
            "category": None,
            "value": None,
            "currency": None,
            "publishedDate": published,
            "deadline": None,
            "url": link or None,
            "noticeId": link or title,
            "source": "austender",
            "description": description,
        }
        item = accept_partial(partial, ctx)
        if item is None:
            continue
        items.append(item)
        if len(items) >= ctx.max_items:
            break
    return items
