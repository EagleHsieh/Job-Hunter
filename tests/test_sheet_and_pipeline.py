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

    def col_values(self, column, value_render_option=None):
        return [row[column - 1] if len(row) >= column else "" for row in self.rows]

    def get_all_records(self):
        header, *body = self.rows
        return [dict(zip(header, row)) for row in body]

    def insert_rows(self, rows, row=1, value_input_option=None, inherit_from_before=False):
        self.rows[row - 1 : row - 1] = [list(r) for r in rows]
        self.inserted = getattr(self, "inserted", []) + [(row, inherit_from_before)]

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


def test_job_id_and_link_keys():
    from jobhunter.sheet import job_id, link_keys

    assert job_id("https://job-boards.eu.greenhouse.io/imc/jobs/4823805101") == "4823805101"
    assert job_id("https://www.jumptrading.com/hr/job?gh_jid=8052343") == "8052343"
    assert job_id("https://jobs.ashbyhq.com/crusoe/1e02db37-9329-42f3-b55b-2c9631414661") == "1e02db37-9329-42f3-b55b-2c9631414661"
    assert job_id("https://optiver.com/join-us/jobs/technology/chicago/graduate-fpga-engineer-2027-start-chicago/") == ""
    assert "id:4823805101" in link_keys("https://www.imc.com/us/careers/jobs/4823805101")
    assert link_keys("") == set()


def test_official_link_swap_and_dedupe_across_link_styles():
    from jobhunter.sheet import link_keys

    cfg = Config(title_keywords=["hardware"], title_exclude=[], max_required_years=3,
                 official_links={"imc": "https://www.imc.com/us/careers/jobs/{id}"})
    greenhouse = make_job(company="IMC", url="https://job-boards.eu.greenhouse.io/imc/jobs/4823805101")
    records, _ = process([greenhouse], cfg, set())
    assert records[0]["Posting Link"] == "https://www.imc.com/us/careers/jobs/4823805101"

    # The sheet already holds the official link; the feed's job-board link must not look new.
    seen = link_keys("https://www.imc.com/us/careers/jobs/4823805101")
    records, stats = process(
        [make_job(company="IMC", url="https://job-boards.eu.greenhouse.io/imc/jobs/4823805101")], cfg, seen
    )
    assert records == [] and stats["skipped: already in sheet"] == 1
    # A company without a template keeps the feed link.
    other, _ = process([make_job(url="https://boards.greenhouse.io/acme/jobs/4823805999")], cfg, set())
    assert other[0]["Posting Link"] == "https://boards.greenhouse.io/acme/jobs/4823805999"


def test_targets_yaml_excludes_first_dry_run_noise():
    from pathlib import Path

    from jobhunter.filters import evaluate

    cfg = Config.from_yaml(Path(__file__).resolve().parents[1] / "config" / "targets.yaml")
    assert cfg.official_links["imc"].startswith("https://www.imc.com/")
    for title in [
        "IT Systems Engineer, M&A", "Customer Service Systems Engineer, Government",
        "Web Design Engineer", "Data Center Hardware Technician", "Associate, Capital Markets",
        "Graduate Quantitative Researcher (PhD)", "Research Associate, Biology",
    ]:
        assert not evaluate(make_job(title=title, location="Austin, TX"), cfg).keep, title
    assert evaluate(make_job(title="Silicon Engineer", location="San Francisco, CA"), cfg).keep
    assert evaluate(make_job(title="Graduate Hardware Engineer", location="Chicago, United States"), cfg).keep


def test_discovery_job_in_trusted_category_passes_title_check_and_is_new_grad():
    cfg = Config(title_keywords=["quant"], title_exclude=[], max_required_years=3, trusted_categories=["Hardware"])
    job = make_job(source="simplify", title="Graduate Engineer, Power Delivery", category="Hardware", description="")
    records, _ = process([job], cfg, set())
    assert records[0]["Level"] == "New grad / entry"
    assert records[0]["OPT availability"] == "Not stated, verify"
    off, stats = process([make_job(source="simplify", title="Graduate Engineer", category="Software", description="",
                                   url="https://x.test/9")], cfg, set())
    assert off == [] and stats["rejected: title off-target"] == 1


def test_excluded_companies_from_watchlist():
    from jobhunter.main import excluded_companies

    rows = [{"Company": "Epic", "Sponsorship Notes": "Excluded: does not sponsor"}, {"Company": "IMC", "Sponsorship Notes": ""}]
    assert excluded_companies(rows) == {"epic"}


def test_new_rows_are_grouped_under_their_company():
    def row(company, role):
        out = [""] * len(HEADERS)
        out[HEADERS.index("Company Name")], out[HEADERS.index("Role")] = company, role
        return out

    tab = FakeWorksheet([HEADERS, row("IMC", "a"), row("IMC", "b"), row("Optiver", "c"), row("NVIDIA", "d")])
    sheet = Sheet(FakeSpreadsheet({"Jobs": tab}))
    records = [
        {"Company Name": "Optiver", "Role": "c2"},
        {"Company Name": "IMC", "Role": "a2"},
        {"Company Name": "IMC", "Role": "a3"},
        {"Company Name": "Apple", "Role": "x"},
        {"Company Name": "Apple", "Role": "y"},
    ]
    assert sheet.append_jobs(records) == 5
    order = [(r[HEADERS.index("Company Name")], r[HEADERS.index("Role")]) for r in tab.rows[1:]]
    assert order == [("IMC", "a"), ("IMC", "b"), ("IMC", "a2"), ("IMC", "a3"), ("Optiver", "c"), ("Optiver", "c2"),
                     ("NVIDIA", "d")]
    # New company Apple goes at the end together, in the order given.
    assert [(r[HEADERS.index("Company Name")], r[HEADERS.index("Role")]) for r in tab.appended] == [("Apple", "x"), ("Apple", "y")]
    assert all(flag for _, flag in tab.inserted)  # inherit dropdowns/formats from the row above


def test_limit_per_company_keeps_best_five_and_collapses_same_title():
    from jobhunter.rank import limit_per_company, title_score

    cfg = Config(title_keywords=[], title_exclude=[], title_weights={"verification": 7, "software": -4})
    assert title_score("Software Engineer", cfg) == -4
    assert title_score("ASIC Verification Engineer", cfg) == 7
    rows = [{"Company Name": "Apple", "Role": f"R{i}", "_score": i, "Role Posting Date": ""} for i in range(8)]
    rows += [{"Company Name": "Apple", "Role": "R7", "_score": 7, "Role Posting Date": ""}]  # same title, other city
    rows += [{"Company Name": "IMC", "Role": "Q", "_score": 20, "Role Posting Date": "2026-10-01"}]
    kept, dropped = limit_per_company(rows, 5)
    assert [r["Company Name"] for r in kept] == ["IMC"] + ["Apple"] * 5  # strongest company first
    assert [r["Role"] for r in kept[1:]] == ["R7", "R6", "R5", "R4", "R3"]
    assert dropped == 4  # R0-R2 beyond five, plus the repeated R7


def test_school_employers_are_dropped_but_company_named_university_is_kept():
    from pathlib import Path

    from jobhunter.filters import evaluate

    cfg = Config.from_yaml(Path(__file__).resolve().parents[1] / "config" / "targets.yaml")
    school = evaluate(make_job(company="Pennsylvania State University", title="Hardware Engineer"), cfg)
    assert not school.keep and "school" in school.reason
    assert not evaluate(make_job(company="Boston College", title="Hardware Engineer"), cfg).keep
    assert evaluate(make_job(company="Akuna Capital University", title="Hardware Engineer"), cfg).keep


def test_low_scoring_titles_are_left_out_of_the_sheet():
    cfg = Config(
        title_keywords=["engineer"], title_exclude=[], max_required_years=3, min_score=3,
        title_weights={"embedded": 3, "software": -4, "hardware": 7},
    )
    jobs = [
        make_job(title="Software Engineer, New Grad", url="https://x.test/1000001"),   # -4 + 3 = -1
        make_job(title="Embedded Software Engineer", url="https://x.test/1000002"),    # 3 - 4 = -1
        make_job(title="Hardware Engineer, New Grad", url="https://x.test/1000003"),   # 7 + 3 = 10
    ]
    records, stats = process(jobs, cfg, set())
    assert [r["Role"] for r in records] == ["Hardware Engineer, New Grad"]
    assert records[0]["_score"] == 10
    assert stats["rejected: low title match (score under 3)"] == 2


def test_daily_limit_keeps_top_scores_in_grouped_order():
    from jobhunter.rank import limit_total

    rows = [
        {"Company Name": "A", "Role": "a1", "_score": 9},
        {"Company Name": "A", "Role": "a2", "_score": 3},
        {"Company Name": "B", "Role": "b1", "_score": 7},
        {"Company Name": "C", "Role": "c1", "_score": 8},
    ]
    kept, over = limit_total(rows, 3)
    assert [r["Role"] for r in kept] == ["a1", "b1", "c1"] and over == 1
    assert limit_total(rows, 0) == (rows, 0)
    assert limit_total(rows, 10) == (rows, 0)


def test_recent_companies_from_date_added_and_status():
    from datetime import date

    class UnformattedWorksheet(FakeWorksheet):
        def col_values(self, column, value_render_option=None):
            assert value_render_option == "UNFORMATTED_VALUE"
            return super().col_values(column, value_render_option)

    headers = HEADERS + ["Date Added"]

    def row(company, added="", status=""):
        out = [""] * len(headers)
        out[headers.index("Company Name")] = company
        out[headers.index("Date Added")] = added
        out[headers.index("Status")] = status
        return out

    today = date(2026, 10, 27)
    serial = (date(2026, 10, 25) - date(1899, 12, 30)).days  # Sheets stores dates as serial numbers
    tab = UnformattedWorksheet([
        headers,
        row("Apple", serial),
        row("IMC", "2026-10-26"),
        row("Old Co", "2026-09-01"),
        row("Applied Co", "2026-09-01", "Applied"),
        row("No Date Co"),
    ])
    sheet = Sheet(FakeSpreadsheet({"Jobs": tab}))
    assert sheet.recent_companies(7, today) == {"apple", "imc", "applied co"}
    assert Sheet(FakeSpreadsheet({"Jobs": FakeWorksheet([["Company Name"]])})).recent_companies(7, today) == set()


def test_company_fed_recently_only_returns_for_a_great_match():
    from jobhunter.rank import limit_per_company

    def rec(company, role, score):
        return {"Company Name": company, "Role": role, "_score": score, "Role Posting Date": ""}

    rows = [rec("Apple", "a1", 20), rec("Apple", "a2", 18), rec("Apple", "a3", 9),
            rec("IMC", "i1", 12), rec("IMC", "i2", 8), rec("NVIDIA", "n1", 10), rec("NVIDIA", "n2", 9)]
    kept, dropped = limit_per_company(rows, 2, recent={"apple", "imc"}, great_score=15, recent_cap=1)
    assert [r["Role"] for r in kept] == ["a1", "n1", "n2"]  # Apple: one great role; IMC: nothing good enough
    assert dropped == 4


def test_applied_companies_from_watchlist():
    from jobhunter.main import applied_companies

    rows = [{"Company": "McKinsey", "Already Applied?": "Yes - Specialist"}, {"Company": "IMC", "Already Applied?": ""}]
    assert applied_companies(rows) == {"mckinsey"}
