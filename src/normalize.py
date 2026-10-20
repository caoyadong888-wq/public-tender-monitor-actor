"""Map source records onto the dataset schema and apply the input filters.

Null deadlines are kept when openOnly is true. A missing published date is
dropped when publishedWithinDays is set, because the window cannot be checked.
A date-only deadline stays open through the end of that UTC date. A datetime
without a timezone is compared as UTC. TED dates written as YYYY-MM-DD+HH:MM
with no clock time are stored as that calendar date. Those choices keep
published values; nothing is filled in.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta, timezone

OUTPUT_FIELDS = (
    "title",
    "buyer",
    "country",
    "category",
    "value",
    "currency",
    "publishedDate",
    "deadline",
    "url",
    "noticeId",
    "source",
    "description",
    "fetchedAt",
)

_LANG_PREFERENCE = ("eng", "en", "en-gb", "en-us")
_WS = re.compile(r"\s+")
_COUNTRY = re.compile(r"[A-Z]{3}")


def clean_text(value) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str):
        return None
    value = html.unescape(value).replace("\x00", " ")
    value = _WS.sub(" ", value).strip()
    return value or None


def first_text(value) -> str | None:
    """Prefer an English string out of TED-style multilingual objects."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        lowered = {str(key).lower(): item for key, item in value.items()}
        for key in _LANG_PREFERENCE:
            if key in lowered:
                text = first_text(lowered[key])
                if text:
                    return text
        for item in value.values():
            text = first_text(item)
            if text:
                return text
        return None
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = first_text(item)
            if text and text not in parts:
                parts.append(text)
        return ", ".join(parts) or None
    return None


def text_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            text = first_text(item) if not isinstance(item, str) else clean_text(item)
            if text and text not in out:
                out.append(text)
        return out
    text = first_text(value)
    return [text] if text else []


def coerce_number(value):
    """Return an int or float, or None when the source did not publish a number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, list):
        for item in value:
            number = coerce_number(item)
            if number is not None:
                return number
        return None
    if isinstance(value, dict):
        return coerce_number(first_text(value))
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    if not isinstance(value, str):
        return None
    text = value.strip().replace(" ", "").replace("\u00a0", "")
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif text.count(",") > 1:
        text = text.replace(",", "")
    elif "," in text:
        left, right = text.split(",", 1)
        if right.isdigit() and len(right) == 3 and left.replace("-", "").isdigit():
            text = left + right
        else:
            text = left + "." + right
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        number = float(text)
    except ValueError:
        return None
    if number != number:  # NaN
        return None
    return int(number) if number.is_integer() else number


def parse_datetime(value):
    """Return (datetime, date_only). date_only is True for a calendar date."""
    if value is None or value == "":
        return None, False
    if isinstance(value, datetime):
        return value, False
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day), True
    if not isinstance(value, str):
        return None, False
    text = value.strip()
    if not text:
        return None, False
    dotted = re.fullmatch(
        r"(\d{4})[.](\d{2})[.](\d{2})(?:[ T](\d{2}):(\d{2}):(\d{2}))?",
        text,
    )
    if dotted:
        year, month, day, hour, minute, second = dotted.groups()
        if hour is None:
            return datetime(int(year), int(month), int(day)), True
        return datetime(int(year), int(month), int(day), int(hour), int(minute), int(second)), False
    us = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", text)
    if us:
        month, day, year = us.groups()
        return datetime(int(year), int(month), int(day)), True
    compact = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text)
    if compact:
        year, month, day = compact.groups()
        return datetime(int(year), int(month), int(day)), True
    # TED publishes some dates as YYYY-MM-DD+HH:MM with no clock time.
    # datetime.fromisoformat reads the offset as a time, so handle it first.
    zoned_date = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})[+-]\d{2}:\d{2}", text)
    if zoned_date and "T" not in text:
        year, month, day = zoned_date.groups()
        return datetime(int(year), int(month), int(day)), True
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None, False
    date_only = len(text) == 10 and text[4] == "-" and "T" not in text
    return parsed, date_only


def to_iso(value) -> str | None:
    parsed, date_only = parse_datetime(value)
    if parsed is None:
        return None
    if date_only:
        return parsed.date().isoformat()
    return parsed.isoformat()


def _as_utc(parsed: datetime, date_only: bool, *, end_of_day: bool) -> datetime:
    if date_only:
        if end_of_day:
            return datetime(parsed.year, parsed.month, parsed.day, 23, 59, 59, tzinfo=timezone.utc)
        return datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def latest_iso(values) -> str | None:
    """Latest published instant. Used when one notice carries several lot deadlines."""
    best_key = None
    best_iso = None
    for text in text_list(values):
        parsed, date_only = parse_datetime(text)
        if parsed is None:
            continue
        key = _as_utc(parsed, date_only, end_of_day=date_only)
        iso = parsed.date().isoformat() if date_only else parsed.isoformat()
        if best_key is None or key > best_key:
            best_key = key
            best_iso = iso
    return best_iso


def deadline_passed(value, now: datetime) -> bool:
    """True only when a published deadline is already before now.

    A null or unparsed deadline is not treated as passed, so the notice is kept.
    """
    if value is None or value == "":
        return False
    parsed, date_only = parse_datetime(value)
    if parsed is None:
        return False
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return _as_utc(parsed, date_only, end_of_day=date_only) < now


def published_within(value, days: int, now: datetime) -> bool:
    if not days or days <= 0:
        return True
    parsed, _date_only = parse_datetime(value)
    if parsed is None:
        return False
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = (now.astimezone(timezone.utc) - timedelta(days=days)).date()
    published = parsed.date() if parsed.tzinfo is None else parsed.astimezone(timezone.utc).date()
    return published >= cutoff


def keyword_match(title, description, keywords) -> bool:
    keys = [str(keyword).strip().lower() for keyword in keywords or [] if str(keyword).strip()]
    if not keys:
        return True
    haystack = f"{title or ''} {description or ''}".lower()
    return any(keyword in haystack for keyword in keys)


def cpv_match(category, codes) -> bool:
    wanted = [str(code).strip().lower() for code in codes or [] if str(code).strip()]
    if not wanted:
        return True
    if not category:
        return False
    text = str(category).lower()
    tokens = re.findall(r"[a-z0-9]{2,}", text)
    for code in wanted:
        if code in text:
            return True
        for token in tokens:
            if token.startswith(code) or (len(token) >= 2 and code.startswith(token)):
                return True
    return False


def country_codes(value) -> list[str]:
    if not value:
        return []
    return _COUNTRY.findall(str(value).upper())


def country_match(country, countries) -> bool:
    wanted = [str(code).strip().upper() for code in countries or [] if str(code).strip()]
    if not wanted:
        return True
    return any(code in wanted for code in country_codes(country))


def normalize_country(value) -> str | None:
    codes = country_codes(value)
    unique: list[str] = []
    for code in codes:
        if code not in unique:
            unique.append(code)
    return ",".join(unique) or None


def collect_text(value) -> str:
    """Flatten multilingual objects so keyword matching can see every language."""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return " ".join(collect_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(collect_text(item) for item in value)
    return ""


def _currency_code(value) -> str | None:
    candidates = text_list(value)
    if not candidates and isinstance(value, str):
        candidates = [value]
    for text in candidates:
        token = re.split(r"[,;\s]+", text.strip())[0].upper()
        if re.fullmatch(r"[A-Z]{3}", token):
            return token
    return None


def finalize(partial: dict, fetched_at: str) -> dict | None:
    raw_title = partial.get("title")
    title = clean_text(raw_title) if isinstance(raw_title, str) or raw_title is None else first_text(raw_title)
    if not title:
        return None
    description = _text_field(partial.get("description"))
    if description:
        description = description[:1000]
    return {
        "title": title,
        "buyer": _text_field(partial.get("buyer")),
        "country": normalize_country(partial.get("country")),
        "category": _text_field(partial.get("category")),
        "value": coerce_number(partial.get("value")),
        "currency": _currency_code(partial.get("currency")),
        "publishedDate": to_iso(partial.get("publishedDate")),
        "deadline": to_iso(partial.get("deadline")),
        "url": _text_field(partial.get("url")),
        "noticeId": _text_field(partial.get("noticeId")),
        "source": _text_field(partial.get("source")),
        "description": description,
        "fetchedAt": fetched_at,
    }


def _text_field(value) -> str | None:
    if isinstance(value, str) or value is None or isinstance(value, (int, float)):
        return clean_text(value)
    return first_text(value)


def notice_matches(
    item: dict,
    *,
    keywords,
    cpv_codes,
    countries,
    open_only: bool,
    published_within_days: int,
    now: datetime,
) -> bool:
    if not keyword_match(item.get("title"), item.get("description"), keywords):
        return False
    if not cpv_match(item.get("category"), cpv_codes):
        return False
    if not country_match(item.get("country"), countries):
        return False
    if published_within_days and published_within_days > 0:
        if not published_within(item.get("publishedDate"), published_within_days, now):
            return False
    if open_only and deadline_passed(item.get("deadline"), now):
        return False
    return True


def interleave(buckets: list[list[dict]], cap: int) -> list[dict]:
    """Take turns across sources so the global cap is not filled by the first source."""
    if cap <= 0:
        return []
    indexes = [0] * len(buckets)
    chosen: list[dict] = []
    while len(chosen) < cap:
        progressed = False
        for position, bucket in enumerate(buckets):
            cursor = indexes[position]
            if cursor < len(bucket):
                chosen.append(bucket[cursor])
                indexes[position] = cursor + 1
                progressed = True
                if len(chosen) >= cap:
                    break
        if not progressed:
            break
    return chosen
