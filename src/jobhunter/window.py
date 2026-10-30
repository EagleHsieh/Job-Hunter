"""Is a posting still open for applications? Cheap checks first, then one live look at the posting page."""
import logging
import re
from datetime import date, datetime

import requests

from .extract import find_deadline
from .fetchers.base import USER_AGENT
from .models import Job

log = logging.getLogger(__name__)

_CLOSED_TEXT = re.compile(
    r"no\s+longer\s+(?:accepting|available|open|active)|position\s+(?:has\s+been|is)\s+filled|"
    r"job\s+(?:has\s+)?(?:expired|been\s+(?:closed|removed|filled))|posting\s+(?:has\s+)?(?:expired|closed)|"
    r"(?:this\s+)?(?:job|position|role|requisition)\s+is\s+(?:closed|no\s+longer)|"
    r"applications?\s+(?:are\s+)?(?:now\s+)?closed|page\s+you\s+are\s+looking\s+for\s+doesn.?t\s+exist|"
    r"couldn.?t\s+find\s+(?:that|this)\s+(?:job|page)",
    re.IGNORECASE,
)
_WORKDAY = re.compile(r"^https?://([^/.]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)/job/(.+)$")


def _posted_age_days(posted: str, today: date) -> int | None:
    try:
        return (today - datetime.strptime(posted, "%Y-%m-%d").date()).days
    except ValueError:
        return None


def live_closed(url: str, session=None, timeout: int = 15) -> str:
    """Reason the posting page says it is closed, or '' when open or when it cannot be told (fail open)."""
    client = session or requests
    try:
        match = _WORKDAY.match(url)
        if match:  # Workday pages are JavaScript; its JSON endpoint says whether the job can still be applied to
            tenant, pod, site, tail = match.groups()
            api = f"https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{tail}"
            response = client.get(api, timeout=timeout, headers={"User-Agent": USER_AGENT})
            if response.status_code in (404, 410):
                return "posting page gone"
            if response.ok:
                info = response.json().get("jobPostingInfo", {})
                if info.get("canApply") is False or info.get("posted") is False:
                    return "posting closed"
                return ""
        response = client.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
    except (requests.RequestException, ValueError) as exc:
        log.info("open-check skipped for %s: %s", url, exc)
        return ""
    if response.status_code in (404, 410):
        return "posting page gone"
    if response.ok and _CLOSED_TEXT.search(response.text[:200_000]):
        return "posting page says closed"
    return ""


def closed_reason(job: Job, url: str, max_age_days: int, today: date | None = None, live=live_closed) -> str:
    """Why this posting is not open to apply to (empty string = open or unknown)."""
    today = today or date.today()
    deadline = find_deadline(job.description, today)
    if deadline and deadline < today.isoformat():
        return f"application deadline {deadline} has passed"
    age = _posted_age_days(job.posted, today)
    if max_age_days and age is not None and age > max_age_days:
        return f"posted {age} days ago (over {max_age_days})"
    return live(url) if live else ""
