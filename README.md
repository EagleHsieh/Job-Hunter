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
| Discovery of companies not on the Watchlist (SimplifyJobs new-grad list: Hardware and Quant categories) | Written and tested; first live run is the real check |
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

## Finding companies you don't know
The Watchlist is a reference, not a limit. Each run also reads the public SimplifyJobs new-grad list
(`config/targets.yaml` → `discovery`), which covers thousands of employers, and sends those listings
through the same filters. Entries link to the employer's own application page; the list has no job
description, so OPT/Visa stay "Not stated, verify" (listings flagged "U.S. Citizenship is Required" are
dropped). Watchlist companies marked Excluded are never surfaced. Turn it off with `--no-discovery`.
It is community-maintained, so treat a listing as a lead and confirm on the employer's page.

## Rules worth knowing
- **Dropped:** US citizenship / "US person", ITAR, security-clearance language; non-US or unspecified
  location; internships, co-ops, contracts; senior/staff/lead/II+ titles; JDs requiring more than 3 years.
- **Also dropped:** postings that say they will not sponsor visas or take OPT/F-1/CPT candidates
  ("no visa sponsorship", "without sponsorship now or in the future", "no OPT", ...).
- **Also dropped:** citizen / permanent-resident-only language, and employers listed in `blocked_companies` (config/targets.yaml).
- **Lower priority:** fabrication, packaging, equipment, process, manufacturing and yield titles score negative; every other target role (R&D, design, IC design, hardware, quant) has equal priority.
- **Flagged, not dropped:** "export control" language (noted in the Visa Sponsorship cell).
- **Limits:** at most `max_per_company` (2) roles per company and `max_new_per_day` (20) overall, best score first.
  A company shown in the last `cooldown_days` days, or already applied/interviewing/rejected (Watchlist
  "Already Applied?", Jobs "Status"), only returns for a role scoring at least `great_match_score`, one per run.
  The Jobs tab needs a **Date Added** column for the cooldown; the run fills it.
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

## Authentication
Never commit credentials. The sheet writer picks its credentials like this:
1. `GOOGLE_SERVICE_ACCOUNT_JSON` set → service-account key (only works where key creation is allowed).
2. Otherwise → Application Default Credentials. In GitHub Actions this is keyless, via Workload
   Identity Federation (`google-github-actions/auth`), so no key file exists to leak.

GitHub secrets/variables (Settings → Secrets and variables → Actions): `SHEET_ID`; for keyless auth
`GCP_WORKLOAD_IDENTITY_PROVIDER` and `GCP_SERVICE_ACCOUNT`; later, for scoring, `ANTHROPIC_API_KEY`.
Share the sheet with the service account's email (Editor) in either case.
