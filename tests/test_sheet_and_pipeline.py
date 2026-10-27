from jobhunter.filters import Config
from jobhunter.main import targets_from_watchlist
from jobhunter.models import Job
from jobhunter.pipeline import process
from jobhunter.sheet import Sheet, build_row, normalize_url

HEADERS = [
    "Status", "Decision", "Company Name", "Role", "Industry", "Role Posting Date",
    "Submission Deadline", "Date Applied", "Match Score", "Requirement Met Count",
    "Top Matching Keywords", "Gaps", "Level", "Location", "Salary Range (from JD)",
    "Posting Link", "Resume Filename", "OPT availability", "Visa Sponsorship",
]
CFG = Config(title_keywords=["hardware"], title_exclude=[], max_required_years=3)


class FakeWorksheet:
    def __init__(self, rows):
        self.rows = rows
        self.appended = []
        self.options = None

    def row_values(self, index):
        return self.rows[index - 1]

    def col_values(self, column):
        return [row[column - 1] if len(row) >= column else "" for row in self.rows]

    def get_all_records(self):
        header, *body = self.rows
        return [dict(zip(header, row)) for row in body]

    def append_rows(self, rows, value_input_option=None):
        self.appended.extend(rows)
        self.options = value_input_option


class FakeSpreadsheet:
    def __init__(self, tabs):
        self.tabs = tabs

    def worksheet(self, name):
        return self.tabs[name]


def make_job(**overrides):
    base = dict(
        company="Acme", title="Hardware Engineer, New Grad", location="Austin, TX",
        url="https://boards.greenhouse.io/acme/jobs/1", source="greenhouse",
        posted="2026-10-20", description="We welcome F-1 OPT candidates.", salary="$100,000 - $120,000",
    )
    base.update(overrides)
    return Job(**base)


def test_normalize_url():
    assert normalize_url("HTTPS://Boards.Greenhouse.io/acme/jobs/1/?utm=x") == "boards.greenhouse.io/acme/jobs/1"
    assert normalize_url("https://careers.acme.com/jobs?gh_jid=77&utm=x") == "careers.acme.com/jobs?gh_jid=77"
    assert normalize_url("") == ""
    assert normalize_url("not a url") == ""


def test_build_row_follows_sheet_column_order_and_blanks_unknowns():
    row = build_row(["B", "A", "Unknown"], {"A": 1, "B": 2})
    assert row == [2, 1, ""]


def test_process_dedupes_and_reports_reasons():
    seen = {normalize_url("https://boards.greenhouse.io/acme/jobs/9")}
    jobs = [
        make_job(),
        make_job(),  # same link twice in one run
        make_job(url="https://boards.greenhouse.io/acme/jobs/9"),  # already in sheet
        make_job(url="https://boards.greenhouse.io/acme/jobs/2", location="Taipei, Taiwan"),
        make_job(url=""),
    ]
    records, stats = process(jobs, CFG, seen)
    assert len(records) == 1
    assert stats["new"] == 1
    assert stats["skipped: already in sheet"] == 2
    assert stats["rejected: non-US or unspecified location"] == 1
    assert stats["skipped: no link"] == 1
    assert records[0]["OPT availability"].startswith("We welcome F-1 OPT")
    # The sentence mentions OPT but says nothing about sponsorship, so that column stays unstated.
    assert records[0]["Visa Sponsorship"] == "Not stated, verify"


def test_export_control_flag_lands_in_visa_column():
    records, _ = process([make_job(description="Subject to export control laws.")], CFG, set())
    assert records[0]["Visa Sponsorship"] == "Not stated, verify [export-control language]"


def test_sheet_writer_roundtrip():
    jobs_tab = FakeWorksheet([HEADERS, [""] * 15 + ["https://boards.greenhouse.io/acme/jobs/9"]])
    sheet = Sheet(FakeSpreadsheet({"Jobs": jobs_tab}))
    assert sheet.existing_links() == {"boards.greenhouse.io/acme/jobs/9"}

    records, _ = process([make_job()], CFG, sheet.existing_links())
    assert sheet.append_jobs(records) == 1
    row = dict(zip(HEADERS, jobs_tab.appended[0]))
    assert row["Company Name"] == "Acme"
    assert row["Role Posting Date"] == "2026-10-20"
    assert row["Posting Link"] == "https://boards.greenhouse.io/acme/jobs/1"
    assert row["Status"] == "" and row["Decision"] == ""  # left for the user
    assert jobs_tab.options == "USER_ENTERED"
    assert sheet.append_jobs([]) == 0


def test_from_env_uses_keyless_default_credentials_when_no_key(monkeypatch):
    import google.auth
    import gspread

    calls = {}
    fake_creds = object()
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.setenv("SHEET_ID", "sheet-123")
    monkeypatch.setattr(
        google.auth, "default", lambda scopes=None: (calls.setdefault("scopes", scopes) and fake_creds, "proj")
    )

    class FakeClient:
        def open_by_key(self, key):
            calls["key"] = key
            return FakeSpreadsheet({})

    monkeypatch.setattr(gspread, "authorize", lambda creds: calls.setdefault("creds", creds) and FakeClient())
    Sheet.from_env()
    assert calls["key"] == "sheet-123"
    assert calls["scopes"] == ["https://www.googleapis.com/auth/spreadsheets"]
    assert calls["creds"] is fake_creds


def test_targets_from_watchlist_skips_unready_and_excluded():
    rows = [
        {"Company": "Ready", "ATS Type": "Greenhouse", "Board URL / Token": "ready", "Industry": "AI", "Sponsorship Notes": ""},
        {"Company": "Pending", "ATS Type": "TBD", "Board URL / Token": "", "Sponsorship Notes": ""},
        {"Company": "NoToken", "ATS Type": "lever", "Board URL / Token": "", "Sponsorship Notes": ""},
        {"Company": "Out", "ATS Type": "ashby", "Board URL / Token": "out", "Sponsorship Notes": "Excluded: does not sponsor visas"},
        {"Company": "ByUrl", "ATS Type": "lever", "Board URL / Token": "https://jobs.lever.co/byurl", "Sponsorship Notes": ""},
    ]
    targets = targets_from_watchlist(rows)
    assert [(t.company, t.ats, t.token) for t in targets] == [
        ("Ready", "greenhouse", "ready"),
        ("ByUrl", "lever", "byurl"),
    ]
    assert targets[0].industry == "AI"
