"""Shared types passed from the run into each source."""

from dataclasses import dataclass, field
from datetime import datetime
import logging


@dataclass
class FetchContext:
    client: object
    keywords: list[str]
    cpv_codes: list[str]
    countries: list[str]
    open_only: bool
    published_within_days: int
    max_items: int
    sam_api_key: str | None
    now: datetime
    fetched_at: str
    log: logging.Logger


@dataclass
class SourceOutcome:
    items: list[dict] = field(default_factory=list)
    status: str = "ok"
    reason: str | None = None
