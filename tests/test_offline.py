"""Offline tests. No network."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from src.context import FetchContext
from src.http_client import PoliteClient, SourceHTTPError
from src.main import parse_input
from src.normalize import (
    coerce_number,
    deadline_passed,
    finalize,
    interleave,
    notice_matches,
)
from src.ocds import ocds_tender_partial, find_tender_url
from src.push import push_notice
from src.sources import canadabuys, ccgp, sam_gov, ted

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
FETCHED = "2026-10-20T12:00:00+00:00"


def make_ctx(**overrides) -> FetchContext:
    values = dict(
        client=None,
        keywords=[],
        cpv_codes=[],
        countries=[],
        open_only=True,
        published_within_days=30,
        max_items=100,
        sam_api_key=None,
        now=NOW,
        fetched_at=FETCHED,
        log=logging.getLogger("tender-test"),
    )
    values.update(overrides)
    return FetchContext(**values)


def test_ted_notice_uses_published_fields_only():
    notice = json.loads((FIXTURES / "ted_notice.json").read_text(encoding="utf-8"))
    item = finalize(ted.parse_ted_notice(notice), FETCHED)
    assert item["title"] == "Czechia – Security software package – SW pro SIEM"
    assert item["buyer"] == "Středisko společných činností AV ČR, v. v. i."
    assert item["country"] == "CZE"
    assert item["value"] == 5300000
    assert item["currency"] == "CZK"
    assert "72268000" in item["category"]
    assert item["category"].split().count("72268000") == 1
    assert item["publishedDate"].startswith("2026-10-01")
    assert item["deadline"].startswith("2026-11-04")
    assert item["noticeId"] == "674231-2026"
    assert item["url"] == "https://ted.europa.eu/en/notice/-/detail/674231-2026"
    assert item["description"] == "Delivery of security software"
    assert item["source"] == "ted"
    assert item["fetchedAt"] == FETCHED
    assert set(item) == {
        "title", "buyer", "country", "category", "value", "currency",
        "publishedDate", "deadline", "url", "noticeId", "source",
        "description", "fetchedAt",
    }


def test_ted_zoned_date_is_not_turned_into_a_clock_time():
    from src.normalize import to_iso

    assert to_iso("2026-09-21+02:00") == "2026-09-21"
    assert to_iso("2026-11-04+01:00") == "2026-11-04"
    assert to_iso("2026-10-19T11:45:09+01:00") == "2026-10-19T11:45:09+01:00"


def test_description_is_truncated_to_1000_chars():
    item = finalize(
        {"title": "Long", "description": "x" * 1500, "source": "ted", "noticeId": "1"},
        FETCHED,
    )
    assert len(item["description"]) == 1000


def test_missing_numbers_stay_null():
    assert coerce_number(None) is None
    assert coerce_number("") is None
    assert coerce_number("not-a-number") is None
    assert coerce_number("5300000") == 5300000
    assert coerce_number("352209.00") == 352209
    assert coerce_number("10.5") == 10.5
    assert coerce_number("1,250,000") == 1250000
    item = finalize({"title": "No value", "value": None, "currency": None, "source": "canadabuys"}, FETCHED)
    assert item["value"] is None
    assert item["currency"] is None


def test_ocds_release_maps_notice_url_and_cpv():
    release = json.loads((FIXTURES / "ocds_release.json").read_text(encoding="utf-8"))
    partial = ocds_tender_partial(
        release,
        source="uk_fts",
        country="GBR",
        url=find_tender_url(release),
    )
    item = finalize(partial, FETCHED)
    assert item["title"] == "Oakham Town Centre Flower Displays"
    assert item["buyer"] == "Oakham Town Council"
    assert item["country"] == "GBR"
    assert item["value"] == 250000
    assert item["currency"] == "GBP"
    assert "77300000" in item["category"]
    assert item["url"] == "https://www.find-tender.service.gov.uk/Notice/098407-2026"
    assert item["deadline"] == "2026-10-27"
    assert item["source"] == "uk_fts"


def test_open_only_drops_past_deadline_and_keeps_null():
    filters = dict(keywords=[], cpv_codes=[], countries=[], open_only=True, published_within_days=30, now=NOW)
    assert deadline_passed(None, NOW) is False
    assert deadline_passed("2026-10-19", NOW) is True
    assert deadline_passed("2026-10-20", NOW) is False
    assert deadline_passed("2026-10-20T11:00:00+00:00", NOW) is True
    assert deadline_passed("2026-10-20T13:00:00+00:00", NOW) is False
    base = {
        "title": "Notice",
        "country": "DEU",
        "publishedDate": "2026-10-10",
        "source": "ted",
    }
    assert notice_matches({**base, "deadline": None}, **filters) is True
    assert notice_matches({**base, "deadline": "2026-10-01"}, **filters) is False
    assert notice_matches({**base, "deadline": "2026-11-01"}, **filters) is True
    closed = dict(keywords=[], cpv_codes=[], countries=[], open_only=False, published_within_days=30, now=NOW)
    assert notice_matches({**base, "deadline": "2026-10-01"}, **closed) is True


def test_keyword_and_cpv_filters():
    item = {
        "title": "Campus IT network",
        "description": "Server room fit-out",
        "category": "CPV 72200000 IT services",
        "country": "CZE,DEU",
        "publishedDate": "2026-10-18",
        "deadline": "2026-11-01",
    }
    common = dict(open_only=True, published_within_days=30, now=NOW, countries=[], cpv_codes=[])
    assert notice_matches(item, keywords=["server", "cctv"], **common) is True
    assert notice_matches(item, keywords=["furniture"], **common) is False
    assert notice_matches(item, keywords=["IT"], **common) is True
    assert notice_matches(
        item,
        keywords=[],
        cpv_codes=["72"],
        countries=["FRA", "DEU"],
        open_only=True,
        published_within_days=30,
        now=NOW,
    ) is True
    assert notice_matches(
        item,
        keywords=[],
        cpv_codes=["45000000"],
        countries=[],
        open_only=True,
        published_within_days=30,
        now=NOW,
    ) is False
    assert notice_matches(
        item,
        keywords=[],
        cpv_codes=[],
        countries=["FRA"],
        open_only=True,
        published_within_days=30,
        now=NOW,
    ) is False
    assert notice_matches(
        {**item, "publishedDate": None},
        keywords=[],
        cpv_codes=[],
        countries=[],
        open_only=True,
        published_within_days=30,
        now=NOW,
    ) is False


def test_canada_csv_filters_and_leaves_value_null():
    text = (FIXTURES / "canada_sample.csv").read_text(encoding="utf-8")
    ctx = make_ctx(keywords=["server", "network", "software", "cctv", "IT"])
    items = canadabuys.items_from_csv(text, ctx)
    assert [item["noticeId"] for item in items] == ["CB-100"]
    assert items[0]["value"] is None
    assert items[0]["currency"] is None
    assert items[0]["country"] == "CAN"
    assert "43211500" in items[0]["category"]
    open_rows = canadabuys.items_from_csv(text, make_ctx())
    assert [item["noticeId"] for item in open_rows] == ["CB-100"]


def test_ccgp_html_parser_and_block_page():
    html_text = (FIXTURES / "ccgp_result.html").read_text(encoding="utf-8")
    parsed, blocked = ccgp.parse_ccgp_html(html_text)
    assert blocked is None
    assert len(parsed) == 1
    assert parsed[0]["noticeId"] == "t20261020_27521197"
    assert parsed[0]["buyer"] == "深圳理工大学"
    assert parsed[0]["country"] == "CHN"
    assert parsed[0]["publishedDate"] == "2026-10-20T01:50:38"
    assert parsed[0]["deadline"] == "2026-10-30T13:30:00"
    assert parsed[0]["category"] == "公开招标公告"
    assert parsed[0]["value"] is None
    assert ccgp.parse_deadline("并于2026年11月11日下午2点00分开标") == "2026-11-11T14:00:00"
    empty, reason = ccgp.parse_ccgp_html("<html>请输入验证码</html>")
    assert empty == []
    assert reason == "not reachable / blocked"


def test_sam_missing_key_skips_without_http():
    class Exploding:
        async def request(self, *args, **kwargs):
            raise AssertionError("SAM.gov must not be called without a key")

    ctx = make_ctx(client=Exploding(), sam_api_key=None)
    outcome = asyncio.run(sam_gov.fetch(ctx))
    assert outcome.items == []
    assert outcome.status == "skipped"
    assert "samGovApiKey" in outcome.reason

    opportunity = json.loads((FIXTURES / "sam_opportunity.json").read_text(encoding="utf-8"))
    item = finalize(sam_gov.parse_opportunity(opportunity), FETCHED)
    assert item["description"] is None
    assert item["country"] == "USA"
    assert "541512" in item["category"]
    assert item["value"] is None
    assert item["url"] == "https://sam.gov/opp/abc123/view"
    assert item["publishedDate"] == "2026-10-15"


def test_ted_query_keeps_notices_with_no_deadline():
    ctx = make_ctx(keywords=["server", 'bad"quote'], cpv_codes=["72000000"], countries=["deu"])
    query = ted.build_query(ctx)
    assert "deadline-receipt-tender-date-lot" not in query
    assert 'notice-title ~ "server"' in query
    assert 'description-lot ~ "server"' in query
    assert "classification-cpv IN (72000000)" in query
    assert "buyer-country IN (DEU)" in query
    assert "publication-date >= 20260920" in query
    assert 'bad"quote' not in query


def test_interleave_respects_global_cap():
    chosen = interleave(
        [[{"source": "ted", "n": 1}, {"source": "ted", "n": 2}], [{"source": "uk_fts", "n": 1}]],
        3,
    )
    assert [item["source"] for item in chosen] == ["ted", "uk_fts", "ted"]
    assert interleave([[{"source": "ted"}]], 0) == []


def test_parse_input_defaults():
    settings = parse_input({})
    assert settings["sources"] == ["ted", "uk_fts", "uk_contracts_finder", "canadabuys"]
    assert settings["open_only"] is True
    assert settings["published_within_days"] == 30
    assert settings["max_items"] == 100
    assert settings["sam_api_key"] is None
    explicit = parse_input({"openOnly": False, "sources": ["sam_gov", "nope"], "maxItems": 20})
    assert explicit["open_only"] is False
    assert explicit["sources"] == ["sam_gov"]
    assert explicit["unknown"] == ["nope"]
    assert explicit["max_items"] == 20


def test_charge_failure_is_tolerated_and_limit_stops():
    class Actor:
        def __init__(self, charge):
            self.charge_impl = charge
            self.items = []
            self.log = logging.getLogger("charge-test")

        async def push_data(self, item):
            self.items.append(item)

        async def charge(self, event_name, count=1):
            assert event_name == "tender-item"
            assert count == 1
            return self.charge_impl(len(self.items))

    broken = Actor(lambda _count: (_ for _ in ()).throw(RuntimeError("pricing is not configured")))
    assert asyncio.run(push_notice(broken, {"title": "one"})) is True
    assert len(broken.items) == 1

    class Result:
        def __init__(self, reached):
            self.event_charge_limit_reached = reached

    limited = Actor(lambda count: Result(count >= 1))
    assert asyncio.run(push_notice(limited, {"title": "one"})) is False

    dict_limit = Actor(lambda _count: {"eventChargeLimitReached": True})
    assert asyncio.run(push_notice(dict_limit, {"title": "one"})) is False


class FakeResponse:
    def __init__(self, status, body="ok"):
        self.status_code = status
        self.text = body
        self.url = "https://example.test/search?api_key=SECRET"
        self.content = body.encode()


class FakeAsyncClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def request(self, method, url, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_http_retries_429_and_5xx_only(monkeypatch):
    slept = []

    async def instant(seconds):
        slept.append(seconds)

    monkeypatch.setattr("src.http_client.asyncio.sleep", instant)
    client = FakeAsyncClient([
        FakeResponse(500, "busy"),
        FakeResponse(429, "slow"),
        FakeResponse(200, "ok"),
    ])
    polite = PoliteClient(client)
    response = asyncio.run(polite.request("ted", "GET", "https://example.test/search"))
    assert response.status_code == 200
    assert client.calls == 3
    assert slept  # backoff between retries

    denied = FakeAsyncClient([FakeResponse(404, "missing api_key=SECRET")])
    polite = PoliteClient(denied)
    with pytest.raises(SourceHTTPError) as caught:
        asyncio.run(polite.request("ted", "GET", "https://example.test/search?api_key=SECRET"))
    assert caught.value.status == 404
    assert denied.calls == 1
    assert "SECRET" not in str(caught.value)

    exhausted = FakeAsyncClient([FakeResponse(503), FakeResponse(502), FakeResponse(500)])
    polite = PoliteClient(exhausted)
    with pytest.raises(SourceHTTPError) as caught:
        asyncio.run(polite.request("uk_fts", "GET", "https://example.test/ocds"))
    assert caught.value.status == 500
    assert exhausted.calls == 3

    flaky = FakeAsyncClient([
        httpx.ConnectError("reset"),
        FakeResponse(200, "ok"),
    ])
    polite = PoliteClient(flaky)
    response = asyncio.run(polite.request("canadabuys", "GET", "https://example.test/file.csv"))
    assert response.status_code == 200
    assert flaky.calls == 2
