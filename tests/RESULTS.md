# Acceptance results

Date: 2026-10-20

Environment: Python 3.13.5, `apify` 4.1.0, `httpx` 0.28.1, `pytest` 9.1.1, `jsonschema` 4.26.0 (`requirements-dev.txt`). Virtualenv: `tender_monitor_actor/.venv` (not in the zip).

## Pytest

Command: `.venv/bin/python -m pytest -q`

```
16 passed in 0.55s
```

Covered offline, with fixture JSON, CSV, and HTML and with no network:

- TED and OCDS normalization, including null value/currency and a 1000-character description cap
- TED `YYYY-MM-DD+HH:MM` dates stored as a calendar date
- Open-only filter: past deadline dropped, deadline today kept, null deadline kept
- Keyword any-match and CPV/country filters
- CanadaBuys CSV parsing
- CCGP HTML parsing, and a captcha page reported as `not reachable / blocked`
- SAM.gov skipped when `samGovApiKey` is empty, with no HTTP call
- `Actor.charge` exception tolerated; `event_charge_limit_reached` stops the run
- HTTP 429/5xx retried at most twice; HTTP 404 not retried; `api_key` redacted
- Dataset schema: TED, UK FTS (`url` null), CanadaBuys, SAM.gov, and an all-null `finalize` item validate; schema properties match `finalize` keys

## Local run

Command: `sh scripts/local_run.sh`

Input:

```json
{
  "sources": ["ted", "uk_fts", "uk_contracts_finder", "canadabuys", "austender", "ccgp"],
  "keywords": ["server", "network", "software", "cctv", "IT"],
  "openOnly": true,
  "publishedWithinDays": 30,
  "maxItems": 20
}
```

`sam_gov` was not selected.

Actor exit code: 0.

Dataset items: 20. Five sources contributed items.

| Source | Status | Fetched | Pushed to dataset |
| --- | --- | --- | --- |
| ted | ok | 20 | 4 |
| uk_fts | ok | 20 | 4 |
| uk_contracts_finder | ok | 20 | 4 |
| canadabuys | ok | 20 | 4 |
| ccgp | ok | 5 | 4 |
| austender | empty | 0 | 0 |

Dataset counts printed by the script:

```
dataset_items 20
dataset canadabuys 4
dataset ccgp 4
dataset ted 4
dataset uk_contracts_finder 4
dataset uk_fts 4
```

Charge: the SDK logged `Ignored attempt to charge for an event - the Actor does not use the pay-per-event pricing` and the run continued. `chargeLimitReached` was false.

## Empty source

`austender` returned 0 items. Exact reason from `SOURCE_REPORT`:

```
open ATM feed https://www.tenders.gov.au/public_data/rss/rss.xml HTTP 403 for https://www.tenders.gov.au/public_data/rss/rss.xml: <!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<HTML><HEAD><META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=iso-8. Official OCDS date types are contractPublished, contractLastModified, contractStart, and contractEnd. OCDS contractPublished HTTP 200 (100 contract notices on the first page; not open tenders). openOnly=true, so contract notices were not returned.
```

The HTTP 403 body is the start of a CloudFront error page (truncated in the error text). The OCDS `contractPublished` call returned HTTP 200 with 100 contract notices on the first page. Those were not written because `openOnly` was true.

`sam_gov` was not part of this query, so it has no live HTTP status. The offline test checks the missing-key skip.

No other source failed.
