from jobhunter.extract import NOT_STATED, snippets
from jobhunter.text_utils import epoch_ms_date, find_salary, iso_date, strip_html


def test_strip_html_handles_escaped_markup():
    raw = "&lt;p&gt;Design &amp;amp; validate boards.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;C&lt;/li&gt;&lt;/ul&gt;"
    assert strip_html(raw) == "Design & validate boards.\nC"


def test_find_salary():
    assert find_salary("Pay range: $120,000 - $150,000 per year") == "$120,000 - $150,000"
    assert find_salary("between $110k to $140k") == "$110k - $140k"
    assert find_salary("competitive pay") == ""


def test_dates():
    assert iso_date("2026-10-21T14:03:00-04:00") == "2026-10-21"
    assert iso_date("") == ""
    assert iso_date(None) == ""
    assert epoch_ms_date(1792000000000) == "2026-10-14"
    assert epoch_ms_date("bad") == ""


def test_snippets_quote_the_posting():
    text = (
        "We are hiring new grads. Candidates on F-1 OPT or STEM OPT are welcome to apply. "
        "We do not sponsor work visas at this time."
    )
    opt, visa = snippets(text)
    assert "STEM OPT" in opt
    assert visa.startswith("We do not sponsor")


def test_snippets_default_when_silent():
    assert snippets("Build great hardware with us.") == (NOT_STATED, NOT_STATED)


def test_lowercase_opt_is_not_the_visa_program():
    opt, _ = snippets("Feel free to opt in to our newsletter.")
    assert opt == NOT_STATED
