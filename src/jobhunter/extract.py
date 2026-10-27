"""Pull OPT / sponsorship wording out of a JD. Quote the posting; never guess."""

import re
from datetime import date

from .text_utils import sentences

NOT_STATED = "Not stated, verify"

# Case-sensitive on purpose: "OPT" the acronym, not the word "opt".
_OPT = re.compile(r"\b(?:STEM[ -]OPT|OPT|CPT|F-?1)\b")
_SPONSOR = re.compile(r"sponsor|work authori[sz]ation|authori[sz]ed to work|\bvisa\b|H-?1B", re.IGNORECASE)


def _clip(sentence: str, limit: int = 220) -> str:
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rstrip() + "…"


def snippets(description: str) -> tuple[str, str]:
    """Return (opt_text, visa_text): first matching sentence of each, or NOT_STATED."""
    opt = visa = ""
    for sentence in sentences(description):
        if not opt and _OPT.search(sentence):
            opt = _clip(sentence)
        if not visa and _SPONSOR.search(sentence):
            visa = _clip(sentence)
        if opt and visa:
            break
    return opt or NOT_STATED, visa or NOT_STATED


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_DEADLINE = re.compile(
    r"(?:apply\s+by|application\s+deadline|deadline\s+to\s+apply|applications?\s+(?:close|due)|"
    r"closing\s+date|submit\s+(?:your\s+)?application\s+by)\W{0,12}(?:on\W{0,3})?"
    r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?",
    re.IGNORECASE,
)


def find_deadline(description: str, today: date | None = None) -> str:
    """YYYY-MM-DD when the JD states an application deadline with a month and day, else ''."""
    today = today or date.today()
    match = _DEADLINE.search(description or "")
    if not match:
        return ""
    month = _MONTHS.get(match.group(1)[:3].lower())
    if not month:
        return ""
    day = int(match.group(2))
    year = int(match.group(3)) if match.group(3) else today.year
    try:
        found = date(year, month, day)
    except ValueError:
        return ""
    if not match.group(3) and found < today.replace(day=1):  # "Jan 5" seen in December means next year
        found = date(year + 1, month, day)
    return found.isoformat()
