import pathlib

import pytest

from jobhunter.filters import Config, evaluate, is_us_location, required_years
from jobhunter.models import Job

CFG = Config(
    title_keywords=["hardware", "validation", "quant", "associate"],
    title_exclude=["sales"],
    max_required_years=3,
)


CFG_FROM_FILE = Config.from_yaml(pathlib.Path(__file__).resolve().parents[1] / "config" / "targets.yaml")


def job(**overrides):
    base = dict(
        company="Acme",
        title="Hardware Engineer, New Grad",
        location="Austin, TX",
        url="https://x.test/1",
        source="greenhouse",
        description="Join our team.",
    )
    base.update(overrides)
    return Job(**base)


@pytest.mark.parametrize(
    "location,expected",
    [
        ("Austin, TX", True),
        ("Remote - US", True),
        ("United States", True),
        ("San Francisco, California", True),
        ("London, UK; San Francisco, CA", True),
        ("Toronto, ON, CA", False),
        ("Vancouver, BC; San Francisco, CA", True),
        ("Toronto, Canada", False),
        ("Taipei, Taiwan", False),
        ("Remote", False),
        ("", False),
    ],
)
def test_is_us_location(location, expected):
    assert is_us_location(location) is expected


def test_keeps_a_clean_new_grad_role():
    result = evaluate(job(), CFG)
    assert result.keep and result.level == "New grad / entry"


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"description": "Must be a U.S. citizen."}, "US citizenship"),
        ({"description": "Subject to ITAR."}, "US citizenship"),
        ({"description": "Active TS/SCI clearance."}, "US citizenship"),
        ({"location": "Taipei, Taiwan"}, "non-US"),
        ({"title": "Hardware Engineering Intern"}, "not full-time"),
        ({"commitment": "Contract"}, "not full-time"),
        ({"title": "Senior Hardware Engineer"}, "senior"),
        ({"title": "Hardware Engineer II"}, "senior"),
        ({"description": "5+ years of experience in PCB design."}, "more than 3 years"),
        ({"title": "Hardware Sales Engineer"}, "excluded title"),
        ({"title": "Barista"}, "off-target"),
    ],
)
def test_rejections_carry_a_reason(overrides, reason):
    result = evaluate(job(**overrides), CFG)
    assert not result.keep
    assert reason in result.reason


def test_experience_in_context_only():
    # "10 years" about the company, not a requirement
    assert required_years("We were founded 10 years ago and love hardware.") is None
    assert required_years("2-4 years of experience with Python") == 2
    assert required_years("3+ years of professional experience; 5 years experience preferred") == 5


def test_unspecified_level_and_export_control_flag():
    result = evaluate(
        job(title="Validation Engineer", description="Work is subject to export control laws."), CFG
    )
    assert result.keep
    assert result.level == "Unspecified, verify"
    assert result.flags == ["export-control language"]


def test_level_mentions_years_when_stated():
    result = evaluate(job(title="Validation Engineer", description="2 years of experience required."), CFG)
    assert result.level == "Unspecified (JD asks 2y)"


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"title": "Hardware Technician"}, "excluded title"),
        ({"title": "Data Center Hardware Engineer"}, "excluded title"),
        ({"title": "Hardware Operations Engineer"}, "excluded title"),
        ({"title": "Hardware Engineer", "description": "Includes rotating shifts and weekend coverage."}, "shift work"),
        ({"title": "Hardware Engineer", "description": "This role requires a PhD in EE."}, "PhD-level"),
        ({"title": "Hardware Engineer", "description": "Postdoctoral researchers welcome."}, "PhD-level"),
    ],
)
def test_technician_shift_and_phd_roles_are_dropped(overrides, reason):
    result = evaluate(job(**overrides), CFG_FROM_FILE)
    assert not result.keep and reason in result.reason


def test_masters_or_phd_stays_open():
    assert evaluate(job(description="MS or PhD in Electrical Engineering."), CFG_FROM_FILE).keep
    assert evaluate(job(description="Bachelor's degree in EE; shifts of focus change often."), CFG_FROM_FILE).keep


@pytest.mark.parametrize(
    "sentence",
    [
        "We do not sponsor visas.",
        "Unfortunately we will not be able to sponsor employment visas for this role.",
        "Visa sponsorship is not available for this position.",
        "No visa sponsorship is offered.",
        "Candidates must be authorized to work in the US without sponsorship now or in the future.",
        "Applicants must not require sponsorship to work in the United States.",
        "We are unable to provide immigration sponsorship.",
        "F-1 OPT candidates are not eligible.",
        "No OPT or CPT candidates.",
        "We cannot sponsor H-1B.",
        "We do not accept candidates on F-1 visas.",
        "This role is not eligible for sponsorship.",
    ],
)
def test_no_sponsorship_language_is_a_clear_no(sentence):
    result = evaluate(job(description=f"Join our team. {sentence}"), CFG)
    assert not result.keep and "sponsorship" in result.reason


@pytest.mark.parametrize(
    "sentence",
    [
        "We welcome F-1 OPT candidates.",
        "Optiver is supportive of US immigration sponsorship for this role.",
        "We sponsor H-1B visas for eligible hires.",
        "Our sponsorship of local events is generous.",
        "Visa sponsorship is available.",
    ],
)
def test_sponsorship_friendly_language_stays(sentence):
    assert evaluate(job(description=f"Join our team. {sentence}"), CFG).keep


def test_blocked_company_is_never_kept():
    cfg = Config(title_keywords=["hardware"], blocked_companies=["rtx"])
    assert not evaluate(job(company="RTX"), cfg).keep
    assert evaluate(job(company="Acme"), cfg).keep


@pytest.mark.parametrize(
    "text",
    ["Open to U.S. citizens or permanent residents only.", "Must be a U.S. citizen.", "Green card holders only", "Permanent resident status required"],
)
def test_citizen_or_permanent_resident_only_is_dropped(text):
    assert not evaluate(job(description=text), CFG).keep


def test_rd_design_outranks_fab_packaging_equipment():
    from jobhunter.rank import title_score

    cfg = CFG_FROM_FILE
    assert title_score("Semiconductor R&D Design Engineer", cfg) > title_score("Packaging Process Engineer", cfg)
    assert title_score("Equipment Engineer, Fabrication", cfg) < cfg.min_score
    assert "rtx" in cfg.blocked_companies
