"""Google Sheets access. Columns are matched by header name, so reordering columns is safe."""

import json
import os
import re
from urllib.parse import urlsplit

JOBS_TAB = "Jobs"
WATCHLIST_TAB = "Watchlist"
LINK_HEADER = "Posting Link"
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
        if not records:
            return 0
        worksheet = self._sheet.worksheet(JOBS_TAB)
        headers = worksheet.row_values(1)
        rows = [build_row(headers, record) for record in records]
        # USER_ENTERED lets Sheets parse YYYY-MM-DD as a real date (displayed as "Oct 27").
        worksheet.append_rows(rows, value_input_option="USER_ENTERED")
        return len(rows)
