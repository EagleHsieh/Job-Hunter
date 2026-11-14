import pytest

from jobhunter import backfill, jd
from jobhunter.filters import Config
from jobhunter.models import Job
from jobhunter.pipeline import process

LONG = "Responsibilities: design and verify digital logic for new products. " * 8


class Resp:
    def __init__(self, data=None, text="", status=200):
        self._data, self.text, self.status_code = data, text, status
        self.ok = status < 400

    def json(self):
        return self._data


class Session:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, **kw):
        self.calls.append(url)
        for prefix, resp in self.routes.items():
            if url.startswith(prefix):
                return resp
        return Resp(status=404)


@pytest.fixture(autouse=True)
def real_fetch(monkeypatch):
    # undo the autouse no-network stub from conftest for this module
    import importlib
    monkeypatch.undo()
    importlib.reload(jd)


def test_workday_uses_cxs_endpoint_and_strips_html():
    s = Session({"https://dexcom.wd1.myworkdayjobs.com/wday/cxs/dexcom/Dexcom/job/San-Diego/Eng_JR1":
                 Resp({"jobPostingInfo": {"jobDescription": f"<p>{LONG}</p><ul><li>Python</li></ul>"}})})
    text = jd.fetch_description("https://dexcom.wd1.myworkdayjobs.com/Dexcom/job/San-Diego/Eng_JR1", s)
    assert "Python" in text and "<" not in text


def test_workday_locale_prefix_is_ignored():
    s = Session({"https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/external/job/US-Texas/Eng_1":
                 Resp({"jobPostingInfo": {"jobDescription": LONG}})})
    assert jd.fetch_description("https://intel.wd1.myworkdayjobs.com/en-us/external/job/US-Texas/Eng_1", s)


def test_greenhouse_api():
    s = Session({"https://boards-api.greenhouse.io/v1/boards/reach3insights/jobs/5433674008":
                 Resp({"content": f"&lt;p&gt;{LONG}&lt;/p&gt;"})})
    text = jd.fetch_description("https://job-boards.greenhouse.io/reach3insights/jobs/5433674008", s)
    assert text.startswith("Responsibilities") and "<" not in text


def test_lever_and_smartrecruiters_and_workable():
    s = Session({
        "https://api.lever.co/v0/postings/acme/0b1c2d3e-0000-1111-2222-333344445555":
            Resp({"descriptionPlain": LONG, "lists": [{"text": "Requirements", "content": "<li>C++</li>"}]}),
        "https://api.smartrecruiters.com/v1/companies/Acme/postings/744000155825610":
            Resp({"jobAd": {"sections": {"jobDescription": {"text": f"<p>{LONG}</p>"}}}}),
        "https://apply.workable.com/api/v2/accounts/acme/jobs/E8AF3CDFB3":
            Resp({"description": f"<p>{LONG}</p>", "requirements": "<p>Python</p>"}),
    })
    assert "C++" in jd.fetch_description("https://jobs.lever.co/acme/0b1c2d3e-0000-1111-2222-333344445555/apply", s)
    assert jd.fetch_description("https://jobs.smartrecruiters.com/Acme/744000155825610", s)
    assert "Python" in jd.fetch_description("https://apply.workable.com/acme/j/E8AF3CDFB3/apply", s)


def test_json_ld_fallback_for_other_sites():
    page = ('<html><script type="application/ld+json">{"@type":"JobPosting","description":"'
            + LONG.replace('"', "'") + '"}</script></html>')
    s = Session({"https://careers.example.com/job/1": Resp(text=page)})
    assert jd.fetch_description("https://careers.example.com/job/1", s).startswith("Responsibilities")


def test_unreadable_posting_returns_empty_not_error():
    s = Session({})
    assert jd.fetch_description("https://dexcom.wd1.myworkdayjobs.com/Dexcom/job/x/y", s) == ""
    assert jd.fetch_description("", s) == ""
    assert jd.fetch_description("https://careers.example.com/job/1", Session({"https://careers.example.com": Resp(text="<html>nav</html>")})) == ""


def test_short_stub_is_not_a_jd():
    s = Session({"https://api.lever.co/v0/postings/acme/0b1c2d3e-0000-1111-2222-333344445555": Resp({"descriptionPlain": "Apply now"})})
    assert jd.fetch_description("https://jobs.lever.co/acme/0b1c2d3e-0000-1111-2222-333344445555", s) == ""


CFG = Config(title_keywords=["engineer"], trusted_categories=["Hardware"], fetch_descriptions=True, check_open=False)


def make_job(**kw):
    base = dict(company="Acme", title="Hardware Engineer", location="Austin, TX", url="https://x.example/1",
                source="simplify", category="Hardware")
    base.update(kw)
    return Job(**base)


def test_process_fills_jd_from_posting_and_drops_citizens_only():
    good, bad = make_job(), make_job(company="Beta", url="https://x.example/2")
    texts = {"https://x.example/1": LONG + " We welcome F-1 OPT candidates.",
             "https://x.example/2": LONG + " U.S. citizenship is required."}
    records, stats = process([good, bad], CFG, set(), describe=lambda url: texts[url])
    assert len(records) == 1 and records[0]["Company Name"] == "Acme"
    assert "F-1 OPT" in records[0]["Job Description"] and "\n" not in records[0]["Job Description"]
    assert "OPT" in records[0]["OPT availability"]
    assert stats["JD fetched from posting"] == 2
    assert stats["rejected: US citizenship/person or clearance required"] == 1


def test_process_keeps_row_when_jd_unreadable():
    records, stats = process([make_job()], CFG, set(), describe=lambda url: "")
    assert len(records) == 1 and records[0]["Job Description"] == ""
    assert stats["JD not readable (row added without a JD)"] == 1


class FakeSpreadsheet:
    def __init__(self):
        self.batches = []

    def values_batch_update(self, body):
        self.batches.append(body)


class FakeWorksheet:
    def __init__(self, rows):
        self._rows, self.spreadsheet = rows, FakeSpreadsheet()

    def get_all_values(self):
        return self._rows


def test_backfill_fills_only_blank_status_blank_jd_rows():
    head = ["Status", "Company Name", "Role", "Posting Link", "Job Description"]
    rows = [head,
            ["", "A", "Eng", "https://a/1", ""],
            ["Applied", "B", "Eng", "https://b/1", ""],
            ["", "C", "Eng", "https://c/1", "already here"],
            ["", "D", "Eng", "https://d/1", ""]]
    ws = FakeWorksheet(rows)
    out = backfill.run(ws, describe=lambda url: ("line one\nline two U.S. citizenship is required" if "a/" in url else ""))
    assert out["filled"] == 1 and out["unreadable"] == ["row 5: D - Eng"] and len(out["ineligible"]) == 1
    sent = ws.spreadsheet.batches[0]
    assert sent["valueInputOption"] == "RAW"
    assert sent["data"] == [{"range": "Jobs!E2", "values": [["line one line two U.S. citizenship is required"]]}]


def test_backfill_dry_run_writes_nothing():
    ws = FakeWorksheet([["Status", "Company Name", "Role", "Posting Link", "Job Description"], ["", "A", "E", "https://a/1", ""]])
    backfill.run(ws, dry_run=True, describe=lambda url: "x" * 300)
    assert ws.spreadsheet.batches == []


def test_column_letter():
    assert backfill.column_letter(19) == "S" and backfill.column_letter(27) == "AA"
