import re

from . import ashby, greenhouse, lever

FETCHERS = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
}

_URL_PATTERNS = {
    "greenhouse": re.compile(r"greenhouse\.io/(?:v1/boards/)?([^/?#]+)"),
    "lever": re.compile(r"jobs\.lever\.co/([^/?#]+)"),
    "ashby": re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)"),
}


def board_token(ats: str, value: str) -> str:
    """Accept either a bare board token or a careers-page URL; return the token."""
    value = (value or "").strip()
    if not value:
        return ""
    if "/" not in value and "." not in value:
        return value
    pattern = _URL_PATTERNS.get(ats)
    match = pattern.search(value) if pattern else None
    return match.group(1) if match else ""
