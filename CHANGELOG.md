# Changelog

## 0.1 - 2026-10-20

- Initial release of Public Tender Monitor.
- Reads open notices from TED, UK Find a Tender, UK Contracts Finder, and CanadaBuys.
- Optional SAM.gov search when an API key is provided. The source is skipped when the key is missing.
- AusTender is included as an experimental source. The reachable official OCDS API publishes contract notices, not open approaches to market.
- CCGP is queried with a plain GET of the public search page. A blocked or captcha response returns no items and does not fail the run.
- Each pushed notice charges one `tender-item` event when pay-per-event pricing is configured.
