"""SAM.gov Get Opportunities API. Called only when samGovApiKey is set."""

from __future__ import annotations

from datetime import timedelta

from src.context import FetchContext, SourceOutcome
from src.http_client import SourceHTTPError, redact
from src.normalize import clean_text, finalize, notice_matches

SEARCH_URL = "https://api.sam.gov/opportunities/v2/search"
MAX_PAGES = 30
# Solicitation, combined synopsis/solicitation, and presolicitation.
OPEN_PTYPES = "o,k,p"


def parse_opportunity(opportunity: dict) -> dict:
    notice_id = clean_text(opportunity.get("noticeId"))
    description = opportunity.get("description")
    if isinstance(description, str) and description.strip().lower().startswith("http"):
        description = None
    naics = clean_text(opportunity.get("naicsCode"))
    classification = clean_text(opportunity.get("classificationCode"))
    category_parts = []
    if naics:
        category_parts.append(f"NAICS {naics}")
    if classification:
        category_parts.append(f"PSC {classification}")
    place = opportunity.get("placeOfPerformance") if isinstance(opportunity.get("placeOfPerformance"), dict) else {}
    country = None
    if isinstance(place.get("country"), dict):
        country = clean_text(place["country"].get("code"))
    if not country or len(country) != 3:
        country = "USA"
    url = clean_text(opportunity.get("uiLink"))
    if not url and notice_id:
        url = f"https://sam.gov/opp/{notice_id}/view"
    return {
        "title": opportunity.get("title"),
        "buyer": opportunity.get("fullParentPathName"),
        "country": country,
        "category": " ".join(category_parts) or None,
        "value": None,
        "currency": None,
        "publishedDate": opportunity.get("postedDate"),
        "deadline": opportunity.get("responseDeadLine"),
        "url": url,
        "noticeId": notice_id,
        "source": "sam_gov",
        "description": description,
        "active": opportunity.get("active"),
    }


def opportunity_to_item(opportunity: dict, ctx: FetchContext) -> dict | None:
    partial = parse_opportunity(opportunity)
    active = partial.pop("active", None)
    if ctx.open_only and isinstance(active, str) and active.strip().lower() == "no":
        return None
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


async def fetch(ctx: FetchContext) -> SourceOutcome:
    api_key = (ctx.sam_api_key or "").strip()
    if not api_key:
        reason = "sam_gov selected but samGovApiKey is empty; skipping source"
        ctx.log.warning(reason)
        return SourceOutcome([], "skipped", reason)
    posted_to = ctx.now.date()
    posted_from = posted_to - timedelta(days=ctx.published_within_days)
    offset = 0
    seen: set[str] = set()
    items: list[dict] = []
    pages = 0
    try:
        while len(items) < ctx.max_items and pages < MAX_PAGES:
            response = await ctx.client.request(
                "sam_gov",
                "GET",
                SEARCH_URL,
                params={
                    "api_key": api_key,
                    "postedFrom": posted_from.strftime("%m/%d/%Y"),
                    "postedTo": posted_to.strftime("%m/%d/%Y"),
                    "ptype": OPEN_PTYPES,
                    "limit": 100,
                    "offset": offset,
                },
            )
            payload = response.json()
            batch = payload.get("opportunitiesData") or []
            pages += 1
            if not batch:
                break
            for opportunity in batch:
                if not isinstance(opportunity, dict):
                    continue
                item = opportunity_to_item(opportunity, ctx)
                if item is None:
                    continue
                key = item.get("noticeId") or item.get("url")
                if not key or key in seen:
                    continue
                seen.add(key)
                items.append(item)
                if len(items) >= ctx.max_items:
                    break
            total = int(payload.get("totalRecords") or 0)
            offset += len(batch)
            if offset >= total or len(batch) < 100:
                break
    except SourceHTTPError as exc:
        if items:
            return SourceOutcome(items, "partial", redact(str(exc)))
        return SourceOutcome([], "error", redact(str(exc)))
    except Exception as exc:
        if items:
            return SourceOutcome(items, "partial", redact(f"{type(exc).__name__}: {exc}"))
        raise
    if not items:
        return SourceOutcome([], "empty", "SAM.gov returned no notices matching the filters")
    return SourceOutcome(items, "ok", None)
