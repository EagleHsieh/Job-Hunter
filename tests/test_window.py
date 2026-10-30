from datetime import date

from jobhunter import window
from jobhunter.models import Job
from jobhunter.pipeline import process
from test_sheet_and_pipeline import CFG, make_job

ORIG_LIVE = window.live_closed
TODAY = date(2026, 10, 29)


def job(**kw):
    return Job(company="Acme", title="Engineer", location="", url="https://x.com/1", source="s", **kw)


def test_deadline_passed():
    j = job(description="Apply by Oct 17, 2026.")
    assert "deadline" in window.closed_reason(j, j.url, 0, TODAY, live=None)


def test_deadline_future_is_open():
    assert window.closed_reason(job(description="Apply by Nov 30, 2026"), "u", 0, TODAY, live=None) == ""


def test_old_posting():
    assert "days ago" in window.closed_reason(job(posted="2026-07-01"), "u", 60, TODAY, live=None)
    assert window.closed_reason(job(posted="2026-10-01"), "u", 60, TODAY, live=None) == ""


def test_live_reason_used():
    assert window.closed_reason(job(), "u", 0, TODAY, live=lambda url: "posting page gone") == "posting page gone"


class Resp:
    def __init__(self, status=200, text="", data=None):
        self.status_code, self.text, self._d = status, text, data
        self.ok = status < 400

    def json(self):
        return self._d


class Sess:
    def __init__(self, resp):
        self.resp = resp

    def get(self, url, **kw):
        return self.resp


def test_live_closed_text_404_and_open():
    assert ORIG_LIVE("https://a.com/j", Sess(Resp(404))) == "posting page gone"
    assert ORIG_LIVE("https://a.com/j", Sess(Resp(text="Sorry, this job is no longer available"))) != ""
    assert ORIG_LIVE("https://a.com/j", Sess(Resp(text="Apply now"))) == ""


def test_workday_can_apply_false():
    url = "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/ASIC_JR1"
    assert ORIG_LIVE(url, Sess(Resp(data={"jobPostingInfo": {"canApply": False}}))) != ""
    assert ORIG_LIVE(url, Sess(Resp(data={"jobPostingInfo": {"canApply": True}}))) == ""


def test_process_rejects_closed():
    records, stats = process([make_job()], CFG, set(), live=lambda url: "posting page gone")
    assert not records and stats["rejected: application window closed"] == 1
