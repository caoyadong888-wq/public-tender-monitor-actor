# Public Tender Monitor

Public Tender Monitor collects **open** public-procurement notices from official free APIs and feeds. One dataset item is one notice. Filters cover keywords, CPV or category text, country, publication age, and whether the deadline is still open.

Missing fields stay `null`. The actor does not fill in a value, currency, buyer, or deadline that the source did not publish.

## Sources

Checked on 2026-10-20 with keywords `server`, `network`, `software`, `cctv`, and `IT`, `openOnly` true, `publishedWithinDays` 30, and `maxItems` 20. `sam_gov` was not selected.

| Source | What it calls | Status on that run |
| --- | --- | --- |
| `ted` | `POST https://api.ted.europa.eu/v3/notices/search` | Returned notices. |
| `uk_fts` | `GET https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages?stages=tender` | Returned notices. Pagination follows `links.next`. |
| `uk_contracts_finder` | `GET https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search?stages=tender` | Returned notices. Pagination follows `links.next`. |
| `canadabuys` | CanadaBuys open-tender CSV `openTenderNotice-ouvertAvisAppelOffres.csv` | Returned notices. The CSV has no value or currency column, so those fields are null. |
| `sam_gov` | `GET https://api.sam.gov/opportunities/v2/search` | Not called. If `sam_gov` is selected and `samGovApiKey` is empty, the source is skipped with a warning and the run continues. |
| `austender` | Open ATM RSS, then the OCDS API | Experimental. The RSS feed `https://www.tenders.gov.au/public_data/rss/rss.xml` returned HTTP 403. The OCDS API answered HTTP 200 and only publishes contract notices (`contractPublished`, `contractLastModified`, `contractStart`, `contractEnd`). With `openOnly` true those contracts are not emitted, so the source returned 0 items. |
| `ccgp` | Plain GET of `https://search.ccgp.gov.cn/bxsearch` | Returned notices from the public HTML search. If that page is blocked or shows a captcha, the source logs `not reachable / blocked` and returns 0. There is no captcha bypass. |

A failure in one source is logged. The other sources still run.

Requests send `User-Agent: public-tender-monitor/0.1 (Apify Actor)`, time out after 60 seconds, wait at least 1.5 seconds between pages of the same source, and retry at most twice on HTTP 429 or 5xx.

## Input

```json
{
  "sources": ["ted", "uk_fts", "uk_contracts_finder", "canadabuys", "austender", "ccgp"],
  "keywords": ["server", "network", "software", "cctv", "IT"],
  "cpvCodes": ["72000000"],
  "countries": ["DEU", "FRA", "GBR"],
  "openOnly": true,
  "publishedWithinDays": 30,
  "maxItems": 20,
  "samGovApiKey": ""
}
```

`sources` defaults to `ted`, `uk_fts`, `uk_contracts_finder`, and `canadabuys`.

`keywords` are matched against the title and description, case-insensitive. Any keyword is enough. The match is a substring, so a short keyword such as `IT` also matches words that contain those letters.

`cpvCodes` match CPV codes on TED and the UK sources, including a prefix such as `72`. On other sources the same strings are matched against the published category text or codes.

`countries` are ISO 3166-1 alpha-3 codes. TED filters on the buyer country. An empty list keeps every country.

`openOnly` defaults to true. A notice whose deadline is already past is dropped. A notice with no deadline is kept.

`publishedWithinDays` defaults to 30. A notice with no published date is dropped, because the window cannot be checked.

`maxItems` defaults to 100. That number is also the cap for each source. Matching notices are then interleaved across sources until the global cap is reached, so one busy source does not take every row.

`samGovApiKey` is optional and secret. It is used only for `sam_gov`.

## Output

Fields: `title`, `buyer`, `country`, `category`, `value`, `currency`, `publishedDate`, `deadline`, `url`, `noticeId`, `source`, `description`, `fetchedAt`.

`description` is at most 1000 characters. `value` is a number or null.

This item is from the 2026-10-20 local run (`storage/datasets/default/000000001.json`):

```json
{
  "title": "Norway – IT services: consulting, software development, Internet and support – 26182 Case handling system",
  "buyer": "Innkjøpskontoret AS, Nordre Follo kommune",
  "country": "NOR",
  "category": "72000000 48000000",
  "value": null,
  "currency": null,
  "publishedDate": "2026-09-21",
  "deadline": "2026-10-27T00:00:00",
  "url": "https://ted.europa.eu/en/notice/-/detail/646367-2026",
  "noticeId": "646367-2026",
  "source": "ted",
  "description": "The competition is for the delivery of a cloud system for general case handling. The procurement ́s value is estimated to: above the EEA threshold. The volume is an estimate and is not binding for the contracting authority. See the procurement documents for further information. The contracting authority reserves the right to cancel the competition, i.a. in connection with budgetary coverage. This procurement is considered to have an immaterial impact on climate and the environment, cf. the Public Procurement Act § 5b third paragraph. The justification for this is that the procurement concerns the procurement of a digital system, where the procurement ́s nature means that the contracting authority has been cut off from affecting climate and environmental impact, as the requirements and criteria targeting these elements will not have sufficient connection to the delivery, cf. DFØ's environment supervisor. The obligation to make requirements for apprentices is considered to apply for this",
  "fetchedAt": "2026-10-20T02:02:34.492193+00:00"
}
```

`value` and `currency` are null because this TED notice did not publish a numeric estimated value in the fields that were requested. The description mentions a threshold and is cut at 1000 characters.

## Pricing

Pay per result. Each notice pushed to the dataset charges one `tender-item` event (`Actor.push_data`, then `Actor.charge`). Set the event price in the Apify Console when you publish the Actor. This package does not set a price.

If pay-per-event pricing is not configured, the charge call is ignored and the run continues. If the charge result reports that the event limit is reached, the run stops pushing further items.

## Run locally

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest
sh scripts/local_run.sh
```

`scripts/local_run.sh` writes a small input file under `storage/key_value_stores/default/INPUT.json`, runs `python -m src` with `APIFY_LOCAL_STORAGE_DIR=./storage`, and prints the dataset count per source.

## Limitations

- AusTender has no open-tender feed on the official OCDS API. The current ATM RSS was HTTP 403 from this client. Contract notices are returned only when `openOnly` is false, and they are awarded contracts, not open approaches to market.
- CCGP is an HTML search page. A blocked or captcha response yields no items. The actor does not try to get around that.
- SAM.gov search rows often put a URL in `description` instead of the notice text. That URL is not copied into `description`. The search payload also does not include a contract value.
- Find a Tender and Contracts Finder HTML notice pages can refuse an automated client. The dataset URL is still the public notice link. The fields come from the OCDS APIs.
- Each source scans at most 30 pages of 100 notices (CCGP uses the portal page size). CanadaBuys is a single CSV.
- A TED notice with several lot deadlines keeps the latest published lot deadline. The value is the procedure estimate when TED publishes one, otherwise the first lot estimate. Lot values are not added together.
- A date-only deadline remains open through the end of that UTC date. A clock time with no timezone is compared as UTC. TED dates published as `YYYY-MM-DD+HH:MM` with no clock time are stored as the calendar date.
- Country on UK notices is `GBR`. CanadaBuys is `CAN`, SAM.gov defaults to `USA`, AusTender is `AUS`, and CCGP is `CHN`. TED uses the published buyer-country codes.
- The run is a snapshot of what those services returned. It is not legal advice and it is not a complete archive of every notice.
