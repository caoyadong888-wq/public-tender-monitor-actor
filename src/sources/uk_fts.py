"""UK Find a Tender OCDS API. Stage filter is tender, as published by the service."""

from __future__ import annotations

from datetime import timedelta

from src.context import FetchContext
from src.ocds import find_tender_url, ocds_tender_partial
from src.sources._paging import collect_ocds_pages

BASE = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"


def parse_release(release: dict) -> dict:
    return ocds_tender_partial(
        release,
        source="uk_fts",
        country="GBR",
        url=find_tender_url(release),
    )


async def fetch(ctx: FetchContext) -> SourceOutcome:
    since = (ctx.now - timedelta(days=ctx.published_within_days)).strftime("%Y-%m-%dT%H:%M:%S")
    url = BASE
    params = {"stages": "tender", "updatedFrom": since, "limit": 100}
    return await collect_ocds_pages(
        ctx,
        source="uk_fts",
        url=url,
        params=params,
        parse_release=parse_release,
        empty_reason="Find a Tender returned no notices matching the filters",
    )
