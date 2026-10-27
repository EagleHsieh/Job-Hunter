import html
import re
from datetime import datetime, timezone

_BLOCK_END = re.compile(r"</(?:p|div|li|ul|ol|h[1-6]|tr)>|<br\s*/?>", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\r\f\v]+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_SALARY = re.compile(
    r"\$\s?(\d{2,3}(?:,\d{3})+|\d{2,3}\s?[kK])\s*(?:-|–|—|to)\s*\$?\s?(\d{2,3}(?:,\d{3})+|\d{2,3}\s?[kK])"
)


def strip_html(raw: str) -> str:
    """Turn (possibly entity-escaped) HTML into plain text, one block per line."""
    if not raw:
        return ""
    text = html.unescape(raw)  # Greenhouse returns escaped HTML
    text = _BLOCK_END.sub("\n", text)
    text = _TAGS.sub(" ", text)
    text = html.unescape(text)
    text = _SPACES.sub(" ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip()]


def iso_date(value) -> str:
    """Return YYYY-MM-DD from an ISO timestamp, or '' when unavailable."""
    if not value:
        return ""
    match = _DATE.match(str(value))
    return match.group(1) if match else ""


def epoch_ms_date(value) -> str:
    try:
        moment = datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return ""
    return moment.strftime("%Y-%m-%d")


def find_salary(text: str) -> str:
    """Return the first '$X - $Y' range stated in the text, or ''."""
    match = _SALARY.search(text or "")
    if not match:
        return ""
    low, high = (part.replace(" ", "") for part in match.groups())
    return f"${low} - ${high}"
