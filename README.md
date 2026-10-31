# Finance Radar — deployable event collector and static website

Independent UNSW student project. Not endorsed by UNSW, any event organiser, or any employer.

## What this does

- Checks **five public web endpoints**: UNIT homepage, UNIT events archive, FMAA events index/detail, UNSW Employability, FINSOC homepage.
- Extracts source-backed, future-dated listings when page markup exposes sufficient evidence. It will NOT invent missing dates or blindly change the year on old events.
- Prioritises finance, investment banking, markets, consulting and student career skills. Checks text for restricted eligibility.
- Combines duplicate listings, flags source failures, and marks previously reviewed events `last_known` if they weren't found during the latest run. Records expire after seven days without a fresh confirmation.
- Makes a static website including upcoming listings, original organiser links, bookmarks, calendar view and personal `.ics` downloads.
- Has an **optional**, single-recipient Resend alert sender. Only new, fresh, unrestricted events on *subsequent* scans are emailed; the initial import does not send alerts. This is **not** a public newsletter system.

## Important operational truth

This package is **built and tested**, but **not deployed** until you authorise a GitHub repo and turn on Pages. The coding environment used to create it cannot directly access external websites through Python, so its parser tests replay sample HTML fixtures modeled on the verified public site structure, **not a live production HTTP integration test**. Once deployed, check the first actual GitHub Actions run, `data/health.json`, and the organiser URLs before relying on coverage.

Some UNSW pages may load dates dynamically (a regular HTTP collector may not see those cards). A successful HTTP request with no parseable events is not proof that the page has no events. If a source contains likely event links but not parseable dates, inspect it before calling the feed complete. FINSOC also advertises some events on private/social channels that cannot be accessed reliably. The site is intentionally a *partial public-source feed*.

## One-time GitHub deployment

1. Create a **new public GitHub repository** called e.g. `finance-radar` (you control its name).
2. Unzip this project and upload **the files inside the project directory** to your repository root, including `.github/` (the leading dot must be preserved). Push to the default branch `main`.
3. Go to **Settings → Pages → Build and deployment → Source: GitHub Actions**. Make sure the repository's Actions are enabled and that GitHub Actions has permission to publish Pages.
4. Go to **Actions → Refresh and publish Finance Radar → Run workflow**. Open the log. The job should run 17 parser tests, fetch pages, record source health, and publish the site. The workflow also commits its last snapshot to the repository so the next run can reliably detect new events.
5. Open **Actions → latest workflow → deploy** to find the Pages URL (normally `https://YOURNAME.github.io/finance-radar/`, but use GitHub's actual reported URL rather than guessing).
6. Subsequent runs are scheduled approximately every six hours (`17 */6 * * *` in UTC). GitHub may delay scheduled runs, and scheduled workflows can be disabled on inactive repositories; inspect Actions if updates stop. An all-source outage causes a failing run and will **not** publish misleading results. A source that has no future listings does **not** by itself cause failure.

### Faster publication from a Mac (optional)

If you are comfortable with Terminal, download and unzip the project, open a terminal in the project folder, and run `bash scripts/publish_github.sh`. The script opens GitHub browser login if needed, creates a **public** repository, enables Pages via GitHub's API, and requests an initial refresh. Requires `git` and GitHub CLI (`brew install gh`). It refuses to overwrite an existing repository or a directory with an existing `origin` remote. This is a *local user-run* script; running it has not been done from ChatGPT.

The workflow also triggers automatically on first push to `main` and uploads `source-health-and-feed` diagnostics to its Actions run, including on collector failure. Confirm real source counts in `data/health.json`; a page serving successfully is not proof that the source parser found all public events.

## Email setup (optional)

Use Resend and verify a sender domain or address supported by your account. In the GitHub repo, add **Settings → Secrets and variables → Actions**:

- `RESEND_API_KEY` — your email provider's API key
- `RADAR_FROM_EMAIL` — verified sender
- `RADAR_RECIPIENT_EMAIL` — your email address

Never put keys in `index.html`, `live.js`, GitHub Pages, or a commit. If not configured, the notifier cleanly skips email. To disable later, remove the recipient secret or disable the workflow. The site does not accept user subscriptions or store private data.

## Run locally

```bash
python3 -m pip install -r requirements.txt
python3 -m pytest -q tests/test_collector.py
python3 scripts/collect.py            # requires actual internet access
python3 -m http.server 8000
# browse http://localhost:8000/
```

Without running the collector, opening `index.html` shows its labelled *reviewed snapshot*. The reviewed event sample is not an automatic feed.

## Outputs

- `data/feed.json` — generated event list, sources and timestamp
- `data/live.js` — same data to power the static HTML (placeholder before first run)
- `data/health.json` — explicit status and error per public endpoint
- `data/new_events.json` — only events not in the previous scan; empty on first run
- `data/notified.json` — sent alert IDs (not email addresses)

## Tests / limits

Test suite checks: dynamic UNSW content flagged rather than mistaken for an empty event list; UNIT real-style homepage parsing, UNIT past calendar archive, FMAA detail eligibility, FINSOC past vs upcoming filtering, UNSW public-style event text, invalid HTML, deduping and eligibility, repeated scans (no duplicate alerts), source outages/stale expiration, notifier disabled without credentials.

Before expanding: add live HTML integration fixtures from the actual GitHub runner, handle client-rendered sources with permitted feeds/official APIs where available, and explore organiser-provided calendars/newsletters. Don't scrape authentication-protected Instagram or Facebook data.

Optional browser smoke check (requires Playwright + a local Chromium binary): `python tests/browser_smoke.py`.

See [LIVE_SOURCE_AUDIT.md](LIVE_SOURCE_AUDIT.md) and [TEST_REPORT.md](TEST_REPORT.md) for current evidence and the exact remaining deployment proof.

## Public social bio-link monitoring (v5)

The six-hour collector checks the public link-in-bio pages for FINSOC, UNIT, FinTechSoc, QuantSoc and BSOC. This is **not** direct Instagram, Facebook, LinkedIn, or private story/post access. Social platform APIs typically require access tokens and permissions from the account owners; ordinary student credentials do not grant third-party society feed access.

- `data/signals.json`: social bio registration links **without a verified future date**. They are displayed in a clearly separate section and never trigger confirmed-event alerts or calendar entries.
- A link becomes a verified upcoming event only when its public destination supplies a future-dated Schema.org `Event` entry and passes finance relevance screening.
- Public bio-page errors, no-date links, empty results and confirmed events have separate source-health states.
- An old link kept in a society bio may still be in the review section; check its destination before applying.
- To capture social-only posts and stories reliably, ask organisers for an approved public event feed, iCal export, newsletters or social-platform API authorization. Do not bypass login walls.

The front end includes separate dated-event and undated-link sections. Email alerts via Resend are optional and unconfigured by default.

Public Facebook event metadata is also inspected only for specific event links already published on FINSOC's official website. This is not access to Facebook Page feeds, private groups, Instagram stories, or a logged-in Facebook session; missing metadata is ignored.

## Additional public sources (no social-media login)

- FMAA UNSW's official Linktree is monitored, including permitted public event registration links behind Facebook's outbound URL wrapper.
- BSOC's public Beehiiv newsletter and UNIT's Market Wrap RSS are checked for **recent clearly event-related publications**. Newsletter article mentions are **review-only leads**, not calendar events or alerts; published dates are never misrepresented as event dates.
- This approach cannot read private Facebook/Instagram feeds. Search-engine RSS results are not republished.

## Public subscription feeds

- The GitHub Actions collector writes `data/events.ics` and `data/events.xml` from **only current, future-dated, confirmed events**. Previously listed events and undated social leads are excluded.
- GitHub Pages publishes these at `/Finance-Radar/events.ics` (calendar subscriptions) and `/Finance-Radar/events.xml` (RSS).
- Dates with no advertised start time become all-day entries with no invented clock time. Times are converted from Sydney offsets to UTC; missing end times are omitted.
- A `webcal:` link allows subscribing in supporting calendar applications. Updates depend on each calendar provider; Google Calendar subscriptions may need the HTTPS URL added manually.
- RSS has stable event GUIDs and never claims events are newly published simply because a scan rechecked them.

## Expanded university society coverage

- Official event indexes: UNSW Capital W, Capital Markets Association (CMA), Accounting and Taxation Society, Business Society event recaps, and UNSW Fintech AI Innovation Consortium (FAIC).
- Each listed event needs a source-backed future date. BSOC recap posts are **not** upcoming events; social-only, undated entries never enter the verified calendar.
- FAIC's published November 2026 industry showcase is collected with its official date and registration link, subject to the organiser's published eligibility.
