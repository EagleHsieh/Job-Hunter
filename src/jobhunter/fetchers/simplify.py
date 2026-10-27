"""Discovery source: SimplifyJobs' public new-grad list (community-maintained JSON).

Unlike the company boards, this covers employers that are not on the Watchlist. Each entry links to
the employer's own application page. It has no job description, so OPT/visa cells stay "Not stated,
verify"; the one signal it carries is a "U.S. Citizenship is Required" flag, which we honour.
"""

from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..models import Job
from .base import get_json

URL = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json"
INDUSTRY = {"Hardware": "Hardware", "Quant": "Quant Trading", "AI/ML/Data": "AI / Data", "Software": "Software"}
_TRACKING = ("utm_", "ref")


def clean_url(url: str) -> str:
    """Drop Simplify's tracking parameters so the link is the employer's own page."""
    parts = urlsplit((url or "").strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(_TRACKING)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def parse(item: dict):
    """Return a Job, or None for closed/hidden listings and ones that require US citizenship."""
    if not item.get("active") or not item.get("is_visible", True):
        return None
    if "citizenship" in str(item.get("sponsorship", "")).lower():
        return None
    posted = item.get("date_posted")
    category = item.get("category", "")
    return Job(
        company=(item.get("company_name") or "").strip(),
        title=(item.get("title") or "").strip(),
        location=" | ".join(item.get("locations") or []),
        url=clean_url(item.get("url", "")),
        source="simplify",
        posted=datetime.fromtimestamp(posted, timezone.utc).strftime("%Y-%m-%d") if posted else "",
        industry=INDUSTRY.get(category, category),
        category=category,
    )


def fetch(categories=None, session=None) -> list[Job]:
    wanted = set(categories or [])
    jobs = []
    for item in get_json(URL, session=session):
        if wanted and item.get("category") not in wanted:
            continue
        job = parse(item)
        if job:
            jobs.append(job)
    return jobs
