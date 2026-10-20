"""Run the Public Tender Monitor actor."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from apify import Actor

from src.context import FetchContext, SourceOutcome
from src.http_client import PoliteClient, build_async_client, redact
from src.normalize import interleave
from src.push import push_notice
from src.sources import FETCHERS, SOURCE_COUNTRY

DEFAULT_SOURCES = ["ted", "uk_fts", "uk_contracts_finder", "canadabuys"]


def _string_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def parse_input(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    requested = _string_list(raw.get("sources")) or list(DEFAULT_SOURCES)
    sources: list[str] = []
    unknown: list[str] = []
    for name in requested:
        if name in FETCHERS and name not in sources:
            sources.append(name)
        elif name not in FETCHERS:
            unknown.append(name)
    open_only = raw["openOnly"] if "openOnly" in raw and raw["openOnly"] is not None else True
    days = raw["publishedWithinDays"] if raw.get("publishedWithinDays") is not None else 30
    max_items = raw["maxItems"] if raw.get("maxItems") is not None else 100
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 30
    try:
        max_items = int(max_items)
    except (TypeError, ValueError):
        max_items = 100
    if days < 1:
        days = 1
    if max_items < 1:
        max_items = 1
    if max_items > 5000:
        max_items = 5000
    api_key = raw.get("samGovApiKey")
    if isinstance(api_key, str):
        api_key = api_key.strip() or None
    else:
        api_key = None
    countries = [code.upper() for code in _string_list(raw.get("countries"))]
    return {
        "sources": sources,
        "unknown": unknown,
        "keywords": _string_list(raw.get("keywords")),
        "cpv_codes": _string_list(raw.get("cpvCodes")),
        "countries": countries,
        "open_only": bool(open_only),
        "published_within_days": days,
        "max_items": max_items,
        "sam_api_key": api_key,
    }


async def _fetch_one(name: str, ctx: FetchContext) -> SourceOutcome:
    fixed = SOURCE_COUNTRY.get(name)
    if fixed and ctx.countries and fixed not in ctx.countries:
        reason = f"country filter {','.join(ctx.countries)} does not include {fixed}"
        ctx.log.info("source %s skipped: %s", name, reason)
        return SourceOutcome([], "skipped", reason)
    try:
        return await FETCHERS[name](ctx)
    except Exception as exc:
        ctx.log.exception("source %s failed", name)
        return SourceOutcome([], "error", redact(f"{type(exc).__name__}: {exc}"))


async def run(actor) -> None:
    raw = await actor.get_input() or {}
    settings = parse_input(raw)
    for name in settings["unknown"]:
        actor.log.warning("ignoring unknown source %s", name)
    actor.log.info(
        "sources=%s keywordCount=%s cpv=%s countries=%s openOnly=%s publishedWithinDays=%s maxItems=%s samKey=%s",
        settings["sources"],
        len(settings["keywords"]),
        settings["cpv_codes"],
        settings["countries"],
        settings["open_only"],
        settings["published_within_days"],
        settings["max_items"],
        bool(settings["sam_api_key"]),
    )
    now = datetime.now(timezone.utc)
    fetched_at = now.isoformat()
    report: list[dict] = []
    buckets: list[list[dict]] = []
    if not settings["sources"]:
        actor.log.warning("no sources selected")
    async with build_async_client() as http:
        ctx = FetchContext(
            client=PoliteClient(http),
            keywords=settings["keywords"],
            cpv_codes=settings["cpv_codes"],
            countries=settings["countries"],
            open_only=settings["open_only"],
            published_within_days=settings["published_within_days"],
            max_items=settings["max_items"],
            sam_api_key=settings["sam_api_key"],
            now=now,
            fetched_at=fetched_at,
            log=actor.log,
        )
        for name in settings["sources"]:
            actor.log.info("fetching %s", name)
            outcome = await _fetch_one(name, ctx)
            actor.log.info(
                "source %s status=%s fetched=%s reason=%s",
                name,
                outcome.status,
                len(outcome.items),
                outcome.reason,
            )
            report.append(
                {
                    "source": name,
                    "status": outcome.status,
                    "fetched": len(outcome.items),
                    "pushed": 0,
                    "reason": outcome.reason,
                }
            )
            buckets.append(outcome.items)
    chosen = interleave(buckets, settings["max_items"])
    pushed = 0
    stopped = False
    by_source = {row["source"]: row for row in report}
    for item in chosen:
        try:
            keep_going = await push_notice(actor, item)
        except Exception as exc:
            actor.log.exception("push failed")
            report.append({"source": "_push", "status": "error", "fetched": 0, "pushed": pushed, "reason": str(exc)})
            break
        pushed += 1
        row = by_source.get(item.get("source"))
        if row is not None:
            row["pushed"] += 1
        if not keep_going:
            stopped = True
            break
    summary = {
        "pushed": pushed,
        "chargeLimitReached": stopped,
        "sources": report,
    }
    actor.log.info("SOURCE_REPORT %s", json.dumps(summary, ensure_ascii=False))
    try:
        await actor.set_value("SOURCE_REPORT", summary)
    except Exception as exc:
        actor.log.warning("could not store SOURCE_REPORT: %s", exc)


async def main() -> None:
    async with Actor:
        await run(Actor)
