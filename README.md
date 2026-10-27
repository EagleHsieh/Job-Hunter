# Job-Hunter
Job Hunting Engine based on my experience and qualification.

Finds new full-time, early-career postings on public job-board feeds, filters them for F-1/OPT fit,
and appends them to the **Jobs** tab of a Google Sheet. Match scoring and resume generation come in
later steps.

## Status
| Piece | State |
|---|---|
| Greenhouse, Lever, Ashby fetchers | Written; verified against fixtures only (see below) |
| Filters (US, full-time, early career, US-person/clearance) | Written and tested |
| OPT / sponsorship quoting, salary capture | Written and tested |
| Google Sheet writer (dedupe by posting link, columns matched by header) | Written; tested against a fake sheet |
| Workday and custom career-site adapters | Not started |
| Match scoring (Anthropic API) | Not started |
| 7 AM Central schedule (GitHub Actions) | Not started |

**Not yet verified live:** the build sandbox cannot reach job-board sites, so the three feed parsers are
tested against sample payloads modeled on each API's documented shape. The first real run (locally or
in Actions) is the true check; if a field name differs, the fix is a one-line change in that fetcher.

## How a run works
1. Read the **Watchlist** tab: companies with an ATS Type (`greenhouse`/`lever`/`ashby`) and a Board
   URL/Token. Rows whose Sponsorship Notes start with `Excluded` are skipped.
2. Fetch every posting from each board.
3. Drop postings already in the sheet (matched on posting link).
4. Apply filters; every rejection has a logged reason (printed as counts at the end of a run).
5. Append survivors to **Jobs**, filling Company, Role, Industry, Posting Date, Level, Location, Salary
   (only if the JD states it), Posting Link, OPT availability and Visa Sponsorship (quoted from the JD, else
   "Not stated, verify"). Status and Decision are left blank for you.

Filter rules live in `src/jobhunter/filters.py`; the role keywords you want live in
`config/targets.yaml`.

## Rules worth knowing
- **Dropped:** US citizenship / "US person", ITAR, security-clearance language; non-US or unspecified
  location; internships, co-ops, contracts; senior/staff/lead/II+ titles; JDs requiring more than 3 years.
- **Flagged, not dropped:** "export control" language (noted in the Visa Sponsorship cell) and
  "no sponsorship" language (quoted, because OPT may still apply).
- **Dates:** `Role Posting Date` is the feed's first-published date when it exists, otherwise the last-updated
  date, which can be later than the real posting date.

## Run locally
```bash
pip install -r requirements-dev.txt
python -m pytest

# No Google credentials needed:
PYTHONPATH=src python -m jobhunter.main --dry-run --board greenhouse:<token>:<Company>

# Full run (reads Watchlist, writes Jobs):
export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat path/to/service-account.json)"
export SHEET_ID=<id from the sheet URL>
PYTHONPATH=src python -m jobhunter.main --dry-run     # preview
PYTHONPATH=src python -m jobhunter.main               # write
```
Share the sheet with the service account's email (Editor) before the first full run.

## Secrets
Never commit credentials. In GitHub: Settings → Secrets and variables → Actions:
`GOOGLE_SERVICE_ACCOUNT_JSON`, `SHEET_ID`, and (later, for scoring) `ANTHROPIC_API_KEY`.
