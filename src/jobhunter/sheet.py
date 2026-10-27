"""Google Sheets access. Columns are matched by header name, so reordering columns is safe."""

import json
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
        worksheet = self._sheet.worksheet(JOBS_TAB)
        headers = worksheet.row_values(1)
        column = headers.index(LINK_HEADER) + 1
        seen: set[str] = set()
        for value in worksheet.col_values(column)[1:]:
            if value:
                seen |= link_keys(value)
        return seen

    def append_jobs(self, records: list[dict]) -> int:
        """Add rows, keeping each company's roles together: a company already in the sheet gets its new
        rows right under its existing ones (inheriting dropdowns and formats); new companies go at the end."""
        if not records:
            return 0
        worksheet = self._sheet.worksheet(JOBS_TAB)
        headers = worksheet.row_values(1)
        name_column = headers.index(COMPANY_HEADER) + 1
        last_row: dict[str, int] = {}
        for row_number, name in enumerate(worksheet.col_values(name_column), start=1):
            if row_number > 1 and name.strip():
                last_row[name.strip().lower()] = row_number

        by_company: dict[str, list[list]] = {}
        for record in records:
            key = str(record.get(COMPANY_HEADER, "")).strip().lower()
            by_company.setdefault(key, []).append(build_row(headers, record))

        # USER_ENTERED lets Sheets parse YYYY-MM-DD as a real date (displayed as "Oct 27").
        # Insert from the bottom up so earlier insert positions stay valid.
        existing = sorted((k for k in by_company if k in last_row), key=lambda k: -last_row[k])
        for key in existing:
            worksheet.insert_rows(
                by_company[key], row=last_row[key] + 1, value_input_option="USER_ENTERED", inherit_from_before=True
            )
        fresh = [row for key, rows in by_company.items() if key not in last_row for row in rows]
        if fresh:
            worksheet.append_rows(fresh, value_input_option="USER_ENTERED")
        return len(records)
