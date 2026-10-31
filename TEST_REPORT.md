# Test report — 31 October 2026

## Automated parser tests

`python -m pytest -q tests/test_collector.py`

**17 passed** (local fixture-based tests). Scenarios include structured Schema.org event fallback, a generic-index URL not causing false deduplication, an event appearing on the second run, no duplicate notification on the third, past archive exclusion, restricted eligibility, deliberate source outages, stale-record expiry, and disabled unconfigured email. The fixtures resemble source layouts confirmed through public retrieval but are not unmodified live website HTML. New cases check UNSW "Read more"-only links, an expired-but-readable FMAA archive, irrelevant career cards, and rejection of deceptive URLs.

## Browser smoke check

`python tests/browser_smoke.py`

**Passed.** Chromium desktop and mobile render, no runtime JavaScript exceptions, live event search/filters, saved events, modal detail and calendar navigation work. Desktop shows 6 reviewed example listings (not claimed as live), mobile viewport 390 px has no horizontal overflow.

## Not yet tested (requires deployment)

- Real `requests` access and site-specific parser success on the GitHub Actions runner.
- Scheduled execution history beyond a single run.
- Resend email delivery (credentials not supplied).
- New event detected and published from an actual live organiser update rather than a fixture change.
- Public GitHub Pages URL, until user authorises repository connection.

**Production acceptance criteria:** Three consecutive scheduled runs with no unexpected source parser failures; at least one actual new organiser event discovered and recorded in `new_events.json`; duplicate-free email after explicit opt-in; visible source health for every run; and a published Pages URL that updates after a scan. Do not claim those criteria have been met yet.
