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
            # citizen / permanent-resident only (not the F-1/OPT candidates you are)
            r"(?:citizens?|permanent\s+residents?|green\s*card(?:\s+holders?)?)\s+only",
            r"(?:u\.?s\.?\s+)?citizens?\s+(?:or|and|/)\s+(?:lawful\s+)?(?:u\.?s\.?\s+)?permanent\s+residents?\s+(?:only|are\s+eligible|required)",
            r"must\s+be\s+a\s+(?:u\.?s\.?\s+)?(?:citizen|(?:lawful\s+)?permanent\s+resident)",
            r"(?:lawful\s+)?permanent\s+resident\s+(?:status\s+)?(?:is\s+)?required",
        ]
    ),
    re.IGNORECASE,
)
# The posting itself says it will not take F-1/OPT candidates or sponsor visas: a clear no.
NO_SPONSORSHIP = re.compile(
    "|".join(
        [
            r"(?:will|do(?:es)?|can|could|would)\s+not\s+(?:be\s+able\s+to\s+)?(?:provide\s+|offer\s+)?(?:visa\s+|work\s+visa\s+|immigration\s+)?sponsor",
            r"(?:unable|not\s+able)\s+to\s+(?:provide\s+|offer\s+)?(?:visa\s+|immigration\s+)?sponsor",
            r"\bcannot\s+(?:provide\s+|offer\s+)?(?:visa\s+|immigration\s+)?sponsor",
            r"\bno\s+(?:visa\s+|work\s+visa\s+|immigration\s+)?sponsorship",
            r"(?:without|not\s+(?:require|need))\s+(?:the\s+need\s+for\s+)?(?:current\s+or\s+future\s+|now\s+or\s+in\s+the\s+future\s+)?(?:visa\s+|immigration\s+|employer\s+)?sponsorship",
            r"not\s+(?:eligible|available)\s+for\s+(?:visa\s+|immigration\s+)?sponsorship",
            r"sponsorship\s+(?:is\s+)?(?:not\s+(?:available|offered|provided)|unavailable)",
            r"\bno\s+(?:opt|cpt|f-?1)\b",
            r"\b(?:opt|cpt|f-?1)(?:\s+(?:visa|students?|candidates?|status))?\s+(?:is|are)?\s*not\s+(?:accepted|eligible|available|considered|supported|permitted)",
            r"not\s+(?:accept|consider|hire)\w*\s+(?:\w+\s+){0,3}(?:opt|cpt|f-?1|student\s+visa)",
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
# Shift-based monitoring/operations work, not an engineering role.
SHIFT_WORK = re.compile(
    r"shift work|work shifts?|shift schedule|\b(?:rotating|night|overnight|weekend|swing|12[- ]hour)\s+shifts?\b",
    re.IGNORECASE,
)
# PhD-level language, and the degrees that would make a role open to a master's student.
PHD_MENTION = re.compile(r"\bph\.?d\.?\b|\bdoctorate\b|\bdoctoral\b|\bpost-?doc\w*", re.IGNORECASE)
NON_PHD_DEGREE = re.compile(
    r"\bmaster'?s?\b|\bm\.?s\.?\b|\bmeng\b|\bbachelor'?s?\b|\bb\.?s\.?\b|\bundergraduate\b|\bbsc\b|\bmsc\b",
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
    official_links: dict[str, str] = field(default_factory=dict)  # company (lowercase) -> URL with {id}
    max_per_company: int = 5
    max_per_company_total: int = 0  # roles per company in the whole sheet (0 = no limit)
    max_new_per_day: int = 0  # 0 = no overall cap
    title_weights: dict[str, int] = field(default_factory=dict)
    early_career_bonus: int = 3
    trusted_category_bonus: int = 3
    min_score: int = 0
    match_score_full: int = 25  # title score that counts as 100 in the Match Score column
    great_match_score: int = 15  # a company fed recently may reappear only with a role at least this good
    cooldown_days: int = 7  # "recently" = shown in the sheet within this many days (or already applied/engaged)
    recent_company_max: int = 1  # roles per run for a company in cooldown
    exclude_company_patterns: list[str] = field(default_factory=list)
    blocked_companies: list[str] = field(default_factory=list)  # flagged employers (citizen/PR only): never fed
    keep_companies: list[str] = field(default_factory=list)
    discovery_categories: list[str] = field(default_factory=list)  # lists to scan for unknown companies
    trusted_categories: list[str] = field(default_factory=list)  # skip the title-keyword check for these

    @classmethod
    def from_yaml(cls, path) -> "Config":
        data = yaml.safe_load(Path(path).read_text()) or {}
        return cls(
            title_keywords=[k.lower() for k in data.get("title_keywords", [])],
            title_exclude=[k.lower() for k in data.get("title_exclude", [])],
            max_required_years=int(data.get("max_required_years", 3)),
            official_links={k.lower(): v for k, v in (data.get("official_links") or {}).items()},
            max_per_company=int(data.get("max_per_company", 5)),
            max_per_company_total=int(data.get("max_per_company_total", 0)),
            max_new_per_day=int(data.get("max_new_per_day", 0)),
            title_weights={k.lower(): int(v) for k, v in (data.get("title_weights") or {}).items()},
            early_career_bonus=int(data.get("early_career_bonus", 3)),
            trusted_category_bonus=int(data.get("trusted_category_bonus", 3)),
            min_score=int(data.get("min_score", 0)),
            match_score_full=int(data.get("match_score_full", 25)),
            great_match_score=int(data.get("great_match_score", 15)),
            cooldown_days=int(data.get("cooldown_days", 7)),
            recent_company_max=int(data.get("recent_company_max", 1)),
            exclude_company_patterns=[str(x).lower() for x in data.get("exclude_company_patterns", [])],
            blocked_companies=[str(x).strip().lower() for x in data.get("blocked_companies", [])],
            keep_companies=[str(x).lower() for x in data.get("keep_companies", [])],
            discovery_categories=list((data.get("discovery") or {}).get("categories", [])),
            trusted_categories=list((data.get("discovery") or {}).get("trusted_categories", [])),
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


def is_excluded_employer(company: str, cfg: Config) -> bool:
    """Schools and universities: you want industry roles."""
    low = company.strip().lower()
    if low in cfg.keep_companies:
        return False
    return any(re.search(pattern, low) for pattern in cfg.exclude_company_patterns)


def is_blocked_company(company: str, cfg: Config) -> bool:
    return company.strip().lower() in cfg.blocked_companies


def evaluate(job: Job, cfg: Config) -> Evaluation:
    if is_blocked_company(job.company, cfg):
        return Evaluation(False, "flagged company (citizen / permanent-resident only)")
    if is_excluded_employer(job.company, cfg):
        return Evaluation(False, "school/university employer")
    text = f"{job.title}\n{job.description}"
    if HARD_EXCLUDE.search(text):
        return Evaluation(False, "US citizenship/person or clearance required")
    if NO_SPONSORSHIP.search(text):
        return Evaluation(False, "says no OPT / F-1 / visa sponsorship")
    if not is_us_location(job.location):
        return Evaluation(False, "non-US or unspecified location")
    if NOT_FULL_TIME.search(job.title) or NOT_FULL_TIME.search(job.commitment or ""):
        return Evaluation(False, "not full-time")
    if SENIOR_TITLE.search(job.title):
        return Evaluation(False, "senior title")
    if SHIFT_WORK.search(job.description):
        return Evaluation(False, "shift work")
    if PHD_MENTION.search(job.description) and not NON_PHD_DEGREE.search(job.description):
        return Evaluation(False, "PhD-level role")
    years = required_years(job.description)
    if years is not None and years > cfg.max_required_years:
        return Evaluation(False, f"requires more than {cfg.max_required_years} years")
    title_low = job.title.lower()
    if any(word in title_low for word in cfg.title_exclude):
        return Evaluation(False, "excluded title keyword")
    if job.category not in cfg.trusted_categories and not any(
        word in title_low for word in cfg.title_keywords
    ):
        return Evaluation(False, "title off-target")

    if job.source == "simplify" or EARLY_TITLE.search(job.title) or EARLY_DESCRIPTION.search(job.description[:2000]):
        level = "New grad / entry"
    elif years is not None:
        level = f"Unspecified (JD asks {years}y)"
    else:
        level = "Unspecified, verify"
    flags = ["export-control language"] if EXPORT_CONTROL.search(text) else []
    return Evaluation(True, "", level, flags)
