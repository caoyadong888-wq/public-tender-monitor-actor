"""China Government Procurement (ccgp.gov.cn) public search.

Plain GET only. A captcha, anti-bot page, or HTTP error is logged and this
source returns no items. Nothing is done to get around a block.
"""

from __future__ import annotations

import re
from datetime import timedelta

from src.context import FetchContext, SourceOutcome
from src.http_client import SourceHTTPError
from src.normalize import clean_text, finalize, notice_matches

SEARCH_URL = "https://search.ccgp.gov.cn/bxsearch"
MAX_PAGES = 30
_BLOCK_MARKERS = ("访问频繁", "访问过于频繁", "系统繁忙", "安全验证")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_LI = re.compile(r"<li>(.*?)</li>", re.DOTALL)
_HREF = re.compile(r'href="([^"]+)"', re.IGNORECASE)
_ANCHOR = re.compile(r"<a\b[^>]*>(.*?)</a>", re.DOTALL | re.IGNORECASE)
_P = re.compile(r"<p>(.*?)</p>", re.DOTALL | re.IGNORECASE)
_SPAN = re.compile(r"<span>(.*?)</span>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_NOTICE_ID = re.compile(r"(t\d+_\d+)\.htm")
_DEADLINE = re.compile(
    r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:\s*(上午|下午)?\s*(\d{1,2})\s*[:：点时]\s*(\d{2}))?"
)
_PUBLISHED = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})(?:\s+(\d{2}):(\d{2}):(\d{2}))?")
_BUYER = re.compile(r"采购人：\s*([^|<]+)")
_STRONG = re.compile(r"<strong\b[^>]*>(.*?)</strong>", re.DOTALL | re.IGNORECASE)


def strip_tags(value: str) -> str:
    return clean_text(_TAG.sub(" ", value or "")) or ""


def parse_deadline(text: str) -> str | None:
    match = _DEADLINE.search(text or "")
    if not match:
        return None
    year, month, day, meridiem, hour, minute = match.groups()
    if hour is None:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    hour_value = int(hour)
    minute_value = int(minute or 0)
    if meridiem == "下午" and hour_value < 12:
        hour_value += 12
    if meridiem == "上午" and hour_value == 12:
        hour_value = 0
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}T{hour_value:02d}:{minute_value:02d}:00"


def parse_ccgp_html(html_text: str) -> tuple[list[dict], str | None]:
    """Return partial notices and a block reason. The reason is set only when nothing was parsed."""
    visible = _COMMENT.sub("", html_text or "")
    region = re.search(r"vT-srch-result-list-bid\">(.*)", html_text or "", re.DOTALL)
    chunk = region.group(1) if region else ""
    end = chunk.find("</ul>")
    if end >= 0:
        chunk = chunk[:end]
    items: list[dict] = []
    for block in _LI.findall(chunk):
        href_match = _HREF.search(block)
        anchor_match = _ANCHOR.search(block)
        if not href_match or not anchor_match:
            continue
        title = strip_tags(anchor_match.group(1))
        if not title:
            continue
        paragraph = strip_tags(_P.search(block).group(1)) if _P.search(block) else ""
        span = _SPAN.search(block).group(1) if _SPAN.search(block) else ""
        span_text = strip_tags(span)
        published = None
        published_match = _PUBLISHED.search(span_text)
        if published_match:
            year, month, day, hour, minute, second = published_match.groups()
            if hour is None:
                published = f"{year}-{month}-{day}"
            else:
                published = f"{year}-{month}-{day}T{hour}:{minute}:{second}"
        buyer_match = _BUYER.search(span_text)
        buyer = clean_text(buyer_match.group(1)) if buyer_match else None
        strongs = [strip_tags(piece) for piece in _STRONG.findall(span)]
        strongs = [piece for piece in strongs if piece]
        category = strongs[0] if strongs else None
        url = href_match.group(1).strip()
        if url.startswith("//"):
            url = "https:" + url
        notice_match = _NOTICE_ID.search(url)
        items.append(
            {
                "title": title,
                "buyer": buyer,
                "country": "CHN",
                "category": category,
                "value": None,
                "currency": None,
                "publishedDate": published,
                "deadline": parse_deadline(paragraph),
                "url": url,
                "noticeId": notice_match.group(1) if notice_match else url,
                "source": "ccgp",
                "description": paragraph or None,
            }
        )
    if items:
        return items, None
    lowered = visible.lower()
    if any(marker in visible for marker in _BLOCK_MARKERS) or "验证码" in visible or "captcha" in lowered:
        return [], "not reachable / blocked"
    return [], None


def _accept(partial: dict, ctx: FetchContext) -> dict | None:
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
    keywords = [str(keyword).strip() for keyword in ctx.keywords if str(keyword).strip()] or [""]
    start = (ctx.now - timedelta(days=ctx.published_within_days)).date()
    end = ctx.now.date()
    seen: set[str] = set()
    items: list[dict] = []
    pages = 0
    blocked_reason = None
    try:
        for keyword in keywords:
            if len(items) >= ctx.max_items or pages >= MAX_PAGES:
                break
            page = 1
            while len(items) < ctx.max_items and pages < MAX_PAGES:
                response = await ctx.client.request(
                    "ccgp",
                    "GET",
                    SEARCH_URL,
                    params={
                        "searchtype": "1",
                        "page_index": page,
                        "bidSort": "0",
                        "pinMu": "0",
                        "bidType": "1",
                        "dbselect": "bidx",
                        "kw": keyword,
                        "start_time": start.strftime("%Y:%m:%d"),
                        "end_time": end.strftime("%Y:%m:%d"),
                        "timeType": "6",
                        "pppStatus": "0",
                    },
                )
                pages += 1
                parsed, block = parse_ccgp_html(response.text)
                if block:
                    blocked_reason = f"CCGP search HTTP {response.status_code}: {block}"
                    break
                fresh = 0
                for partial in parsed:
                    item = _accept(partial, ctx)
                    if item is None:
                        continue
                    key = item.get("noticeId") or item.get("url")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    items.append(item)
                    fresh += 1
                    if len(items) >= ctx.max_items:
                        break
                if not parsed or fresh == 0:
                    break
                page += 1
            if blocked_reason:
                break
    except SourceHTTPError as exc:
        if items:
            return SourceOutcome(items, "partial", str(exc))
        return SourceOutcome([], "error", f"not reachable / blocked: {exc}")
    except Exception as exc:
        if items:
            return SourceOutcome(items, "partial", f"{type(exc).__name__}: {exc}")
        raise
    if blocked_reason and not items:
        ctx.log.warning("ccgp: %s", blocked_reason)
        return SourceOutcome([], "empty", blocked_reason)
    if not items:
        return SourceOutcome([], "empty", "CCGP search returned no notices matching the filters")
    if blocked_reason:
        return SourceOutcome(items, "partial", blocked_reason)
    return SourceOutcome(items, "ok", None)
