"""Google Sheets access. Columns are matched by header name, so reordering columns is safe."""

import json
import logging
import os
import re
from datetime import date, timedelta
from urllib.parse import urlsplit

JOBS_TAB = "Jobs"
WATCHLIST_TAB = "Watchlist"
LINK_HEADER = "Posting Link"
COMPANY_HEADER = "Company Name"
ADDED_HEADER = "Date Added"
ENGAGED_STATUSES = {"applied", "interview", "offer", "rejected"}
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_KEEP_QUERY_KEYS = ("gh_jid=", "jid=", "id=")


def normalize_url(url: str) -> str:
    """Stable key for de-duplication: host + path (+ job-id query param when that is the job id)."""
    parts = urlsplit((url or "").strip())
    if not parts.netloc:
        return ""
    keep = [kv for kv in parts.query.split("&") if kv.startswith(_KEEP_QUERY_KEYS)]
    key = f"{parts.netloc}{parts.path.rstrip('/')}"
    if keep:
        key += "?" + "&".join(keep)
    return key.lower()


_JOB_ID = re.compile(r"(?:gh_jid=|jid=|/)(\d{6,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:[/?#&]|$)", re.I)


def job_id(url: str) -> str:
    """The posting's id (Greenhouse number, Lever/Ashby UUID), or "" when the link has none."""
    match = _JOB_ID.search((url or "").strip())
    return match.group(1).lower() if match else ""


def link_keys(url: str) -> set[str]:
    """Keys that identify a posting. The id key makes the ATS link and the company's own link
    for the same job match each other, so switching a sheet link to the official page does not
    make the job look new."""
    keys = set()
    normalized = normalize_url(url)
    if normalized:
        keys.add(normalized)
        ident = job_id(url)
        if ident:
            keys.add(f"id:{ident}")
    return keys


def _to_date(value):
    """A Sheets date serial number, or an ISO 'YYYY-MM-DD' string; None when unreadable."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return date(1899, 12, 30) + timedelta(days=int(value))
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


log = logging.getLogger(__name__)

ROLE_FILLER = {"graduate", "grad", "new", "college", "i", "1", "early", "career", "entry", "level",
               "and", "the", "for", "of", "a", "ii", "2027", "2026", "university"}


def role_key(company: str, title: str) -> str:
    """Same role at the same company (it may be posted once per city): one key."""
    clean = lambda text: re.sub(r"[^a-z0-9]", "", str(text).lower())  # ignore spacing and punctuation
    # Ignore word order and level/new-grad filler, so "Electrical Hardware Engineer 1 Graduate" and
    # "Graduate Electrical Hardware Engineer 1" are the same role.
    words = re.findall(r"[a-z0-9]+", str(title).lower())
    core = sorted({w for w in words if w not in ROLE_FILLER})
    return f"role:{clean(company)}|{''.join(core)}"


def build_row(headers: list[str], record: dict) -> list:
    """Align a record (keyed by header name) to the sheet's current column order."""
    return [record.get(header, "") for header in headers]


class Sheet:
    def __init__(self, spreadsheet):
        self._sheet = spreadsheet

    @classmethod
    def from_env(cls) -> "Sheet":
        """Authenticate with a service-account key if GOOGLE_SERVICE_ACCOUNT_JSON is set,
        otherwise with Application Default Credentials (keyless: Workload Identity Federation)."""
        import gspread

        raw_key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if raw_key:
            client = gspread.service_account_from_dict(json.loads(raw_key))
        else:
            import google.auth

            credentials, _ = google.auth.default(scopes=SCOPES)
            client = gspread.authorize(credentials)
        return cls(client.open_by_key(os.environ["SHEET_ID"]))

    def watchlist(self) -> list[dict]:
        return self._sheet.worksheet(WATCHLIST_TAB).get_all_records()

    def recent_companies(self, days: int, today: date | None = None) -> set[str]:
        """Companies shown in the sheet within `days` days (Date Added), or whose Status shows you applied,
        interviewed, got an offer or a rejection. Used to avoid feeding the same employer day after day."""
        worksheet = self._sheet.worksheet(JOBS_TAB)
        headers = worksheet.row_values(1)
        if COMPANY_HEADER not in headers:
            return set()
        today = today or date.today()
        raw = {"value_render_option": "UNFORMATTED_VALUE"}  # dates come back as serial numbers, not "Oct 27"

        def column(name):
            return worksheet.col_values(headers.index(name) + 1, **raw)[1:] if name in headers else []

        companies, added, status = column(COMPANY_HEADER), column(ADDED_HEADER), column("Status")
        recent: set[str] = set()
        for i, company in enumerate(companies):
            key = str(company).strip().lower()
            if not key:
                continue
            when = _to_date(added[i]) if i < len(added) else None
            if when and today - when <= timedelta(days=days):
                recent.add(key)
            if i < len(status) and str(status[i]).strip().lower() in ENGAGED_STATUSES:
                recent.add(key)
        return recent

    def existing_links(self) -> set[str]:
        """Keys of everything already in the Jobs tab: posting links, posting ids, and company+title pairs
        (so the same role posted in another city is not added again)."""
        worksheet = self._sheet.worksheet(JOBS_TAB)
        headers = worksheet.row_values(1)
        column = headers.index(LINK_HEADER) + 1
        seen: set[str] = set()
        for value in worksheet.col_values(column)[1:]:
            if value:
                seen |= link_keys(value)
        if COMPANY_HEADER in headers and "Role" in headers:
            companies = worksheet.col_values(headers.index(COMPANY_HEADER) + 1)[1:]
            roles = worksheet.col_values(headers.index("Role") + 1)[1:]
            for company, role in zip(companies, roles):
                if company.strip() and role.strip():
                    seen.add(role_key(company, role))
        return seen

    def company_match_scores(self) -> dict[str, list[float]]:
        """Match Scores of the rows already in the Jobs tab, by lower-case company name."""
        worksheet = self._sheet.worksheet(JOBS_TAB)
        headers = worksheet.row_values(1)
        if COMPANY_HEADER not in headers or "Match Score" not in headers:
            return {}
        raw = {"value_render_option": "UNFORMATTED_VALUE"}
        companies = worksheet.col_values(headers.index(COMPANY_HEADER) + 1, **raw)[1:]
        scores = worksheet.col_values(headers.index("Match Score") + 1, **raw)[1:]
        result: dict[str, list[float]] = {}
        for i, company in enumerate(companies):
            key = str(company).strip().lower()
            if not key:
                continue
            try:
                value = float(scores[i]) if i < len(scores) else 0.0
            except (TypeError, ValueError):
                value = 0.0
            result.setdefault(key, []).append(value)
        return result

    def count_added_on(self, day: date) -> int:
        """Rows whose Date Added is `day`: lets repeated runs on one day respect the daily limit."""
        worksheet = self._sheet.worksheet(JOBS_TAB)
        headers = worksheet.row_values(1)
        if ADDED_HEADER not in headers:
            return 0
        values = worksheet.col_values(headers.index(ADDED_HEADER) + 1, value_render_option="UNFORMATTED_VALUE")[1:]
        return sum(1 for value in values if _to_date(value) == day)

    def append_jobs(self, records: list[dict]) -> int:
        """Append today's rows below the last row, so the sheet reads oldest to newest (Date Added).
        Within the batch the records arrive grouped by company, strongest first. Appending (rather than
        inserting between rows) keeps the pre-formatted rows' dropdowns and date formats intact."""
        if not records:
            return 0
        worksheet = self._sheet.worksheet(JOBS_TAB)
        headers = worksheet.row_values(1)
        rows = [build_row(headers, record) for record in records]
        # USER_ENTERED lets Sheets parse YYYY-MM-DD as a real date (displayed as "Oct 27").
        worksheet.append_rows(rows, value_input_option="USER_ENTERED")
        self._group_by_company(worksheet, headers)
        return len(rows)

    @staticmethod
    def _group_by_company(worksheet, headers: list[str]) -> None:
        """Keep every company's roles together: sort by company, then strongest match first."""
        if "Company Name" not in headers or "Match Score" not in headers:
            return
        company = headers.index("Company Name") + 1
        score = headers.index("Match Score") + 1
        last_column = chr(64 + len(headers))
        try:
            # gspread needs an explicit end row ("A2:R" alone raises), so use the sheet's row count.
            worksheet.sort((company, "asc"), (score, "des"), range=f"A2:{last_column}{worksheet.row_count}")
        except Exception as exc:  # the rows are already written: never fail the whole run over ordering
            log.warning("could not group rows by company: %s", exc)
