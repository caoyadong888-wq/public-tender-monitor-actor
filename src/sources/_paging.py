"""Page through an OCDS release package that exposes links.next."""

from __future__ import annotations

from src.context import FetchContext, SourceOutcome
from src.http_client import SourceHTTPError
from src.normalize import finalize, notice_matches

MAX_PAGES = 30


def accept_partial(partial: dict, ctx: FetchContext) -> dict | None:
    item = finalize(partial, ctx.fetched_at)
    if item is None:
        return None
    if not notice_matches(
        item,
        keywords=ctx.keywords,
        cpv_codes=ctx.cpv_codes,
        countries=ctx.countries,
        open_only=ctx.open_only,
        published_within_days=ctx.published_within_days,
        now=ctx.now,
    ):
        return None
    return item


async def collect_ocds_pages(
    ctx: FetchContext,
    *,
    source: str,
    url: str,
    params: dict | None,
    parse_release,
    empty_reason: str,
) -> SourceOutcome:
    seen: set[str] = set()
    items: list[dict] = []
    pages = 0
    try:
        while url and pages < MAX_PAGES and len(items) < ctx.max_items:
            response = await ctx.client.request(source, "GET", url, params=params)
            params = None
            payload = response.json()
            pages += 1
            for release in payload.get("releases") or []:
                if not isinstance(release, dict):
                    continue
                partial = parse_release(release)
                if not partial:
                    continue
                item = accept_partial(partial, ctx)
                if item is None:
                    continue
                key = item.get("noticeId") or item.get("url")
                if not key or key in seen:
                    continue
                seen.add(key)
                items.append(item)
                if len(items) >= ctx.max_items:
                    break
            url = ((payload.get("links") or {}).get("next")) or ""
    except SourceHTTPError as exc:
        if items:
            return SourceOutcome(items, "partial", str(exc))
        return SourceOutcome([], "error", str(exc))
    except Exception as exc:
        if items:
            return SourceOutcome(items, "partial", f"{type(exc).__name__}: {exc}")
        raise
    if not items:
        return SourceOutcome([], "empty", empty_reason)
    return SourceOutcome(items, "ok", None)
