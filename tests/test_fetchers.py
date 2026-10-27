from jobhunter.fetchers import ashby, board_token, greenhouse, lever


def test_greenhouse_parse():
    item = {
        "title": " Hardware Engineer, New Grad ",
        "location": {"name": "Austin, TX"},
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
        "first_published": "2026-10-20T10:00:00-04:00",
        "updated_at": "2026-10-25T10:00:00-04:00",
        "content": "&lt;p&gt;Pay range $100,000 - $130,000.&lt;/p&gt;",
    }
    job = greenhouse.parse(item, "Acme")
    assert job.title == "Hardware Engineer, New Grad"
    assert job.location == "Austin, TX"
    assert job.posted == "2026-10-20"  # first_published wins over updated_at
    assert job.salary == "$100,000 - $130,000"
    assert job.source == "greenhouse"


def test_greenhouse_falls_back_to_updated_at():
    job = greenhouse.parse({"title": "X", "updated_at": "2026-10-25T10:00:00Z"}, "Acme")
    assert job.posted == "2026-10-25"


def test_lever_parse():
    item = {
        "text": "Validation Engineer",
        "hostedUrl": "https://jobs.lever.co/acme/abc",
        "createdAt": 1792000000000,
        "categories": {"location": "Remote", "allLocations": ["Boston, MA", "Remote - US"], "commitment": "Full-time"},
        "descriptionPlain": "Validate silicon.",
        "lists": [{"text": "Requirements", "content": "<li>C</li><li>Python</li>"}],
        "additionalPlain": "Equal opportunity employer.",
        "salaryRange": {"currency": "USD", "min": 120000, "max": 150000, "interval": "per-year-salary"},
    }
    job = lever.parse(item, "Acme")
    assert job.location == "Boston, MA; Remote - US"
    assert job.commitment == "Full-time"
    assert job.posted == "2026-10-14"
    assert job.salary == "USD 120,000 - 150,000"
    assert "Requirements" in job.description and "Python" in job.description


def test_ashby_parse_and_unlisted_filter(monkeypatch):
    listed = {
        "title": "FPGA Engineer",
        "location": "New York, NY",
        "secondaryLocations": [{"location": "Chicago, IL"}],
        "jobUrl": "https://jobs.ashbyhq.com/acme/1",
        "publishedAt": "2026-10-22T09:00:00.000+00:00",
        "employmentType": "FullTime",
        "descriptionPlain": "Build trading hardware.",
        "compensation": {"compensationTierSummary": "$150K – $200K"},
    }
    job = ashby.parse(listed, "Acme")
    assert job.location == "New York, NY; Chicago, IL"
    assert job.salary == "$150K – $200K"
    assert job.posted == "2026-10-22"

    monkeypatch.setattr(
        ashby, "get_json", lambda *a, **k: {"jobs": [listed, {**listed, "title": "Hidden", "isListed": False}]}
    )
    assert [j.title for j in ashby.fetch("Acme", "acme")] == ["FPGA Engineer"]


def test_board_token_accepts_urls_and_bare_tokens():
    assert board_token("greenhouse", "acme") == "acme"
    assert board_token("greenhouse", "https://boards.greenhouse.io/acme/jobs/1") == "acme"
    assert board_token("greenhouse", "https://job-boards.greenhouse.io/acme") == "acme"
    assert board_token("lever", "https://jobs.lever.co/acme/abc") == "acme"
    assert board_token("ashby", "https://jobs.ashbyhq.com/acme") == "acme"
    assert board_token("lever", "") == ""
    assert board_token("lever", "https://example.com/careers") == ""


def test_simplify_parse_and_filters():
    from jobhunter.fetchers import simplify

    item = {
        "company_name": "Acme Silicon", "title": "Hardware Engineer", "active": True, "is_visible": True,
        "category": "Hardware", "locations": ["Austin, TX", "Remote in USA"], "sponsorship": "Other",
        "date_posted": 1792000000, "url": "https://jobs.acme.com/123?utm_source=Simplify&ref=Simplify&gh_jid=77",
    }
    job = simplify.parse(item)
    assert job.company == "Acme Silicon" and job.industry == "Hardware" and job.category == "Hardware"
    assert job.location == "Austin, TX | Remote in USA"
    assert job.url == "https://jobs.acme.com/123?gh_jid=77"
    assert job.posted == "2026-10-14" and job.source == "simplify"
    assert simplify.parse({**item, "active": False}) is None
    assert simplify.parse({**item, "is_visible": False}) is None
    assert simplify.parse({**item, "sponsorship": "U.S. Citizenship is Required"}) is None
