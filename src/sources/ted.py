"""EU TED Search API v3. https://api.ted.europa.eu/v3/notices/search"""

from __future__ import annotations

from datetime import timedelta

from src.context import FetchContext, SourceOutcome
from src.http_client import SourceHTTPError
from src.normalize import (
    collect_text,
    finalize,
    first_text,
    latest_iso,
    notice_matches,
    text_list,
)

SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
PAGE_LIMIT = 100
MAX_PAGES = 30
FIELDS = [
    "publication-number",
    "notice-title",
    "buyer-name",
    "buyer-country",
    "deadline-receipt-tender-date-lot",
    "publication-date",
    "classification-cpv",
    "estimated-value-lot",
    "estimated-value-cur-lot",
    "estimated-value-proc",
    "estimated-value-cur-proc",
    "description-lot",
    "description-proc",
]


def _quote_term(term: str) -> str:
    return term.replace("\\", " ").replace('"', " ").strip()


def build_query(ctx: FetchContext) -> str:
    """Expert query. Deadline is not required here, so notices with no deadline survive."""
    parts: list[str] = []
    keyword_clauses: list[str] = []
    for keyword in ctx.keywords:
        quoted = _quote_term(str(keyword))
        if not quoted:
            continue
        keyword_clauses.append(f'notice-title ~ "{quoted}"')
        keyword_clauses.append(f'description-lot ~ "{quoted}"')
    if keyword_clauses:
        parts.append("(" + " OR ".join(keyword_clauses) + ")")
    cpv_codes = []
    for code in ctx.cpv_codes:
        cleaned = str(code).strip()
        if cleaned and all(character.isalnum() for character in cleaned):
            cpv_codes.append(cleaned)
    if cpv_codes:
        parts.append("classification-cpv IN (" + " ".join(cpv_codes) + ")")
    countries = [code.strip().upper() for code in ctx.countries if str(code).strip()]
    countries = [code for code in countries if len(code) == 3 and code.isalpha()]
    if countries:
        parts.append("buyer-country IN (" + " ".join(countries) + ")")
    since = (ctx.now - timedelta(days=ctx.published_within_days)).date()
    parts.append("publication-date >= " + since.strftime("%Y%m%d"))
    return " AND ".join(parts)


def _first_number_and_currency(amount, currency):
    from src.normalize import coerce_number

    if isinstance(amount, list):
        number = None
        code = None
        for index, item in enumerate(amount):
            number = coerce_number(item)
            if number is not None:
                if isinstance(currency, list) and index < len(currency):
                    code = currency[index]
                elif not isinstance(currency, list):
                    code = currency
                break
        return number, code
    return coerce_number(amount), currency


def parse_ted_notice(notice: dict) -> dict:
    publication_number = first_text(notice.get("publication-number"))
    cpv_codes = []
    for code in text_list(notice.get("classification-cpv")):
        if code not in cpv_codes:
            cpv_codes.append(code)
    value, currency = _first_number_and_currency(
        notice.get("estimated-value-proc"),
        notice.get("estimated-value-cur-proc"),
    )
    if value is None:
        value, currency = _first_number_and_currency(
            notice.get("estimated-value-lot"),
            notice.get("estimated-value-cur-lot"),
        )
    countries = notice.get("buyer-country") or []
    if isinstance(countries, list):
        country = ",".join(dict.fromkeys(str(code).strip() for code in countries if str(code).strip()))
    else:
        country = first_text(countries)
    description = first_text(notice.get("description-proc")) or first_text(notice.get("description-lot"))
    search_text = " ".join(
        collect_text(notice.get(field))
        for field in ("notice-title", "description-proc", "description-lot")
    )
    return {
        "title": notice.get("notice-title"),
        "buyer": notice.get("buyer-name"),
        "country": country,
        "category": " ".join(cpv_codes) or None,
        "value": value,
        "currency": currency,
        "publishedDate": notice.get("publication-date"),
        "deadline": latest_iso(notice.get("deadline-receipt-tender-date-lot")),
        "url": f"https://ted.europa.eu/en/notice/-/detail/{publication_number}" if publication_number else None,
        "noticeId": publication_number,
        "source": "ted",
        "description": description,
        "searchText": search_text,
    }


def _accept(partial: dict, ctx: FetchContext) -> dict | None:
    item = finalize(partial, ctx.fetched_at)
    if item is None:
        return None
    probe = dict(item)
    extra = partial.get("searchText") or ""
    if extra:
        probe["description"] = f"{item.get('description') or ''} {extra}"
    if not notice_matches(
        probe,
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
    query = build_query(ctx)
    page = 1
    seen: set[str] = set()
    items: list[dict] = []
    try:
        while len(items) < ctx.max_items and page <= MAX_PAGES:
            response = await ctx.client.request(
                "ted",
                "POST",
                SEARCH_URL,
                json={"query": query, "fields": FIELDS, "limit": PAGE_LIMIT, "page": page},
            )
            payload = response.json()
            notices = payload.get("notices") or []
            if payload.get("timedOut") and not notices and not items:
                return SourceOutcome([], "error", "TED search timed out and returned no notices")
            for notice in notices:
                item = _accept(parse_ted_notice(notice), ctx)
                if item is None:
                    continue
                key = item.get("noticeId") or item.get("url")
                if not key or key in seen:
                    continue
                seen.add(key)
                items.append(item)
                if len(items) >= ctx.max_items:
                    break
            total = int(payload.get("totalNoticeCount") or 0)
            if not notices or len(notices) < PAGE_LIMIT or page * PAGE_LIMIT >= total:
                break
            page += 1
    except SourceHTTPError as exc:
        if items:
            return SourceOutcome(items, "partial", str(exc))
        return SourceOutcome([], "error", str(exc))
    except Exception as exc:
        if items:
            return SourceOutcome(items, "partial", f"{type(exc).__name__}: {exc}")
        raise
    if not items:
        return SourceOutcome([], "empty", "TED returned no notices matching the filters")
    return SourceOutcome(items, "ok", None)
