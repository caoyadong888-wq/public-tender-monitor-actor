"""UK Contracts Finder OCDS search.

Verified endpoint:
https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search
Query: stages=tender, publishedFrom, limit, and links.next (cursor).
"""

from __future__ import annotations

from datetime import timedelta

from src.context import FetchContext
from src.ocds import contracts_finder_url, ocds_tender_partial
from src.sources._paging import collect_ocds_pages

BASE = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"


def parse_release(release: dict) -> dict:
    return ocds_tender_partial(
        release,
        source="uk_contracts_finder",
        country="GBR",
        url=contracts_finder_url(release),
    )


async def fetch(ctx: FetchContext):
    since = (ctx.now - timedelta(days=ctx.published_within_days)).strftime("%Y-%m-%dT%H:%M:%S")
    return await collect_ocds_pages(
        ctx,
        source="uk_contracts_finder",
        url=BASE,
        params={"stages": "tender", "publishedFrom": since, "limit": 100},
        parse_release=parse_release,
        empty_reason="Contracts Finder returned no notices matching the filters",
    )
