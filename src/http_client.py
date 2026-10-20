"""Polite HTTP: fixed user agent, 60s timeout, gap between pages, limited retries."""

from __future__ import annotations

import asyncio
import re
import time

import httpx

USER_AGENT = "public-tender-monitor/0.1 (Apify Actor)"
PAGE_GAP_SECONDS = 1.5
TIMEOUT_SECONDS = 60.0
MAX_RETRIES = 2

_SECRET_RE = re.compile(r"(api_key=)[^&\s]+", re.IGNORECASE)


def redact(text: str) -> str:
    return _SECRET_RE.sub(r"\1***", text or "")


class SourceHTTPError(Exception):
    def __init__(self, status: int, url: str, detail: str = ""):
        self.status = status
        self.url = redact(url)
        self.detail = redact(detail)[:180]
        message = f"HTTP {status} for {self.url}"
        if self.detail:
            message = f"{message}: {self.detail}"
        super().__init__(message)


class PoliteClient:
    """One gap of at least 1.5s between completed calls of the same source."""

    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self._last: dict[str, float] = {}

    async def _gap(self, source: str) -> None:
        last = self._last.get(source)
        if last is None:
            return
        wait = PAGE_GAP_SECONDS - (time.monotonic() - last)
        if wait > 0:
            await asyncio.sleep(wait)

    def _touch(self, source: str) -> None:
        self._last[source] = time.monotonic()

    async def request(self, source: str, method: str, url: str, **kwargs) -> httpx.Response:
        await self._gap(source)
        attempt = 0
        while True:
            try:
                response = await self.client.request(method, url, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= MAX_RETRIES:
                    self._touch(source)
                    raise
                attempt += 1
                await asyncio.sleep(PAGE_GAP_SECONDS * (2 ** (attempt - 1)))
                continue
            if response.status_code == 429 or 500 <= response.status_code <= 599:
                if attempt < MAX_RETRIES:
                    attempt += 1
                    await asyncio.sleep(PAGE_GAP_SECONDS * (2 ** (attempt - 1)))
                    continue
            self._touch(source)
            if response.status_code >= 400:
                raise SourceHTTPError(response.status_code, str(response.url), response.text)
            return response


def build_async_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(TIMEOUT_SECONDS),
        follow_redirects=True,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/csv, text/html, */*",
        },
    )
