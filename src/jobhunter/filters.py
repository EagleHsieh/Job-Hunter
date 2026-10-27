"""Rule-based filtering. Every rejection returns a reason so it can be audited in logs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .models import Job

US_STATE_ABBR = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH "
    "NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)
US_STATE_NAMES = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire",
    "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington", "west virginia",
    "wisconsin", "wyoming", "district of columbia",
]

CANADIAN_PROVINCE_THEN_CA = re.compile(r"\b(?:AB|BC|MB|NB|NL|NS|ON|PE|QC|SK|NT|NU|YT),\s*CA\b")

# Roles that cannot be done on F-1/OPT: dropped outright.
HARD_EXCLUDE = re.compile(
    "|".join(
        [
            r"u\.?s\.?\s+citizen(?:ship)?s?",
            r"united states citizen(?:ship)?",
            r"\bu\.?s\.?\s+persons?\b",
            r"\bitar\b",
            r"security clearance",
            r"secret clearance",
            r"\bts/sci\b",
            r"top secret",
            r"public trust",
        ]
    ),
    re.IGNORECASE,
)
# Ambiguous language: kept, but flagged in the sheet.
EXPORT_CONTROL = re.compile(r"export[- ]control", re.IGNORECASE)

NOT_FULL_TIME = re.compile(
    r"\b(intern|interns|internship|co-?op|apprentice\w*|contractor|contract|part[- ]time|temporary|temp)\b",
    re.IGNORECASE,
)
SENIOR_TITLE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|manager|director|head|vp|vice president|"
    r"architect|fellow|distinguished|ii|iii|iv)\b",
    re.IGNORECASE,
)
EARLY_TITLE = re.compile(
    r"new[- ]?grad|new graduate|entry[- ]level|early[- ]career|recent grad|university grad|"
    r"graduate|junior|associate|\bengineer (?:i|1)\b|\b202[67]\b|rotational",
    re.IGNORECASE,
)
EARLY_DESCRIPTION = re.compile(
    r"new[- ]?grad|new graduate|recent graduate|class of 202[67]|entry[- ]level|"
    r"\b0\s*(?:-|–|to)\s*[123]\s*years",
    re.IGNORECASE,
)
YEARS_REQUIRED = re.compile(
    r"(\d{1,2})(?:\s*(?:-|–|to)\s*\d{1,2})?\s*\+?\s*(?:years?|yrs?)[^.\n]{0,80}?experience",
    re.IGNORECASE,
)


@dataclass
class Config:
    title_keywords: list[str] = field(default_factory=list)
    title_exclude: list[str] = field(default_factory=list)
    max_required_years: int = 3

    @classmethod
    def from_yaml(cls, path) -> "Config":
        data = yaml.safe_load(Path(path).read_text()) or {}
        return cls(
            title_keywords=[k.lower() for k in data.get("title_keywords", [])],
            title_exclude=[k.lower() for k in data.get("title_exclude", [])],
            max_required_years=int(data.get("max_required_years", 3)),
        )


@dataclass
class Evaluation:
    keep: bool
    reason: str = ""
    level: str = ""
    flags: list[str] = field(default_factory=list)


def is_us_location(location: str) -> bool:
    if not location:
        return False
    low = location.lower()
    if "u.s." in low or re.search(r"\b(united states|usa|us)\b", low):
        return True
    if any(re.search(rf"\b{name}\b", low) for name in US_STATE_NAMES):
        return True
    # "Toronto, ON, CA" uses CA for Canada: drop province + ", CA" before reading state codes.
    cleaned = CANADIAN_PROVINCE_THEN_CA.sub("", location)
    abbreviations = set(re.findall(r",\s*([A-Z]{2})\b", cleaned))
    if "canada" in low:
        abbreviations.discard("CA")
    return bool(abbreviations & US_STATE_ABBR)


def required_years(description: str):
    """Largest stated lower bound of 'N+ years ... experience', or None."""
    years = [int(match.group(1)) for match in YEARS_REQUIRED.finditer(description or "")]
    return max(years) if years else None


def evaluate(job: Job, cfg: Config) -> Evaluation:
    text = f"{job.title}\n{job.description}"
    if HARD_EXCLUDE.search(text):
        return Evaluation(False, "US citizenship/person or clearance required")
    if not is_us_location(job.location):
        return Evaluation(False, "non-US or unspecified location")
    if NOT_FULL_TIME.search(job.title) or NOT_FULL_TIME.search(job.commitment or ""):
        return Evaluation(False, "not full-time")
    if SENIOR_TITLE.search(job.title):
        return Evaluation(False, "senior title")
    years = required_years(job.description)
    if years is not None and years > cfg.max_required_years:
        return Evaluation(False, f"requires more than {cfg.max_required_years} years")
    title_low = job.title.lower()
    if any(word in title_low for word in cfg.title_exclude):
        return Evaluation(False, "excluded title keyword")
    if not any(word in title_low for word in cfg.title_keywords):
        return Evaluation(False, "title off-target")

    if EARLY_TITLE.search(job.title) or EARLY_DESCRIPTION.search(job.description[:2000]):
        level = "New grad / entry"
    elif years is not None:
        level = f"Unspecified (JD asks {years}y)"
    else:
        level = "Unspecified, verify"
    flags = ["export-control language"] if EXPORT_CONTROL.search(text) else []
    return Evaluation(True, "", level, flags)
