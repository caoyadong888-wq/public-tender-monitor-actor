"""Official notice sources. Each module exposes async fetch(ctx) -> SourceOutcome."""

from src.sources import (
    austender,
    canadabuys,
    ccgp,
    sam_gov,
    ted,
    uk_contracts_finder,
    uk_fts,
)

FETCHERS = {
    "ted": ted.fetch,
    "uk_fts": uk_fts.fetch,
    "uk_contracts_finder": uk_contracts_finder.fetch,
    "canadabuys": canadabuys.fetch,
    "sam_gov": sam_gov.fetch,
    "austender": austender.fetch,
    "ccgp": ccgp.fetch,
}

SOURCE_COUNTRY = {
    "uk_fts": "GBR",
    "uk_contracts_finder": "GBR",
    "canadabuys": "CAN",
    "sam_gov": "USA",
    "austender": "AUS",
    "ccgp": "CHN",
}
