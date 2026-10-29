import pytest


@pytest.fixture(autouse=True)
def no_network_open_check(monkeypatch):
    monkeypatch.setattr("jobhunter.window.live_closed", lambda url, **kw: "")
