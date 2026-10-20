"""CanadaBuys open tender notice CSV (daily open-data file).

The file has no value or currency columns, so those fields stay null.
"""

from __future__ import annotations

import csv
import io

from src.context import FetchContext, SourceOutcome
from src.http_client import SourceHTTPError
from src.normalize import clean_text, finalize, notice_matches

CSV_URL = "https://canadabuys.canada.ca/opendata/pub/openTenderNotice-ouvertAvisAppelOffres.csv"


def _category(row: dict) -> str | None:
    parts: list[str] = []
    unspsc = clean_text(row.get("unspsc"))
    unspsc_text = clean_text(row.get("unspscDescription-eng"))
    gsin = clean_text(row.get("gsin-nibs"))
    gsin_text = clean_text(row.get("gsinDescription-nibsDescription-eng"))
    if unspsc or unspsc_text:
        parts.append(" ".join(bit for bit in ("UNSPSC", unspsc, unspsc_text) if bit))
    if gsin or gsin_text:
        parts.append(" ".join(bit for bit in ("GSIN", gsin, gsin_text) if bit))
    return "; ".join(parts) or None


def parse_canada_row(row: dict) -> dict:
    title = clean_text(row.get("title-titre-eng")) or clean_text(row.get("title-titre-fra"))
    description = row.get("tenderDescription-descriptionAppelOffres-eng") or row.get(
        "tenderDescription-descriptionAppelOffres-fra"
    )
    notice_id = clean_text(row.get("referenceNumber-numeroReference")) or clean_text(
        row.get("solicitationNumber-numeroSollicitation")
    )
    return {
        "title": title,
        "buyer": clean_text(row.get("contractingEntityName-nomEntitContractante-eng"))
        or clean_text(row.get("contractingEntityName-nomEntitContractante-fra")),
        "country": "CAN",
        "category": _category(row),
        "value": None,
        "currency": None,
        "publishedDate": clean_text(row.get("publicationDate-datePublication")),
        "deadline": clean_text(row.get("tenderClosingDate-appelOffresDateCloture")),
        "url": clean_text(row.get("noticeURL-URLavis-eng")) or clean_text(row.get("noticeURL-URLavis-fra")),
        "noticeId": notice_id,
        "source": "canadabuys",
        "description": description,
        "status": clean_text(row.get("tenderStatus-appelOffresStatut-eng")),
    }


def row_to_item(row: dict, ctx: FetchContext) -> dict | None:
    partial = parse_canada_row(row)
    status = (partial.pop("status") or "").lower()
    if ctx.open_only and status and status not in {"open", "ouvert"}:
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


def items_from_csv(text: str, ctx: FetchContext) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for row in csv.DictReader(io.StringIO(text)):
        item = row_to_item(row, ctx)
        if item is None:
            continue
        key = item.get("noticeId") or item.get("url")
        if not key or key in seen:
            continue
        seen.add(key)
        items.append(item)
        if len(items) >= ctx.max_items:
            break
    return items


async def fetch(ctx: FetchContext) -> SourceOutcome:
    try:
        response = await ctx.client.request("canadabuys", "GET", CSV_URL)
    except SourceHTTPError as exc:
        return SourceOutcome([], "error", str(exc))
    text = response.content.decode("utf-8-sig", errors="replace")
    items = items_from_csv(text, ctx)
    if not items:
        return SourceOutcome([], "empty", "CanadaBuys CSV contained no notices matching the filters")
    return SourceOutcome(items, "ok", None)
