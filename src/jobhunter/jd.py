"""Fetch the full job description for a posting link.

The Simplify discovery list carries no description, so rows found through it used to land in the sheet
with an empty "Job Description" cell. This module reads the employer's own posting through the public
JSON endpoint of its applicant-tracking system (Workday, Greenhouse, Lever, Ashby, SmartRecruiters,
Workable, Oracle HCM, Eightfold) and falls back to the schema.org JobPosting data embedded in the page.
It never raises: an unreadable posting simply returns "" and the row is written without a JD.
"""

import html as htmllib
import json
import logging
import re
from urllib.parse import urlsplit

import requests

from .fetchers.base import USER_AGENT
from .text_utils import strip_html

log = logging.getLogger(__name__)

TIMEOUT = 20
MIN_JD_CHARS = 200  # shorter than this is a stub or an error page, not a job description

_WORKDAY = re.compile(r"^/(?:[a-z]{2}-[a-z]{2}/)?([^/]+)/job/(.+)$", re.I)
_GREENHOUSE_PATH = re.compile(r"^/(?:embed/job_app/?)?([^/]+)/jobs/(\d+)")
_LEVER_PATH = re.compile(r"^/([^/]+)/([0-9a-f]{8}-[0-9a-f-]{27})", re.I)
_ASHBY_PATH = re.compile(r"^/([^/]+)/([0-9a-f]{8}-[0-9a-f-]{27})", re.I)
_SMARTRECRUITERS_PATH = re.compile(r"^/([^/]+)/(\d{6,})")
_WORKABLE_PATH = re.compile(r"/(?:j|jobs)/([0-9A-Fa-f]{8,})")
_ORACLE_PATH = re.compile(r"/sites/([^/]+)/job/(\d+)")
_EIGHTFOLD_PATH = re.compile(r"/careers/job/(\d+)")
_JSON_LD = re.compile(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.I | re.S)


def _get(url, session, params=None, as_json=True):
    client = session or requests
    response = client.get(
        url, params=params, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/html"}
    )
    if not response.ok:
        raise requests.HTTPError(f"HTTP {response.status_code}")
    return response.json() if as_json else response.text


def _join(*parts: str) -> str:
    return "\n".join(part for part in (strip_html(p) if "<" in (p or "") or "&" in (p or "") else (p or "").strip()
                                       for p in parts) if part)


def _workday(parts, session):
    host = parts.netloc.lower()
    tenant = host.split(".")[0]
    match = _WORKDAY.match(parts.path)
    if not match:
        return ""
    site, tail = match.groups()
    api = f"https://{host}/wday/cxs/{tenant}/{site}/job/{tail}"
    info = _get(api, session).get("jobPostingInfo", {})
    return _join(info.get("jobDescription", ""))


def _greenhouse(parts, session):
    match = _GREENHOUSE_PATH.match(parts.path)
    if not match:
        return ""
    token, ident = match.groups()
    data = _get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{ident}", session)
    return _join(data.get("content", ""))


def _lever(parts, session):
    match = _LEVER_PATH.match(parts.path)
    if not match:
        return ""
    company, ident = match.groups()
    data = _get(f"https://api.lever.co/v0/postings/{company}/{ident}", session)
    sections = [data.get("descriptionPlain", "")]
    for block in data.get("lists") or []:
        sections.append(block.get("text", ""))
        sections.append(block.get("content", ""))
    sections.append(data.get("additionalPlain", ""))
    return _join(*sections)


def _ashby(parts, session):
    match = _ASHBY_PATH.match(parts.path)
    if not match:
        return ""
    company, ident = match.groups()
    data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{company}", session, params={"includeCompensation": "true"})
    for item in data.get("jobs", []):
        if ident.lower() in str(item.get("jobUrl", "")).lower() or ident.lower() == str(item.get("id", "")).lower():
            return item.get("descriptionPlain") or strip_html(item.get("descriptionHtml", ""))
    return ""


def _smartrecruiters(parts, session):
    match = _SMARTRECRUITERS_PATH.match(parts.path)
    if not match:
        return ""
    company, ident = match.groups()
    data = _get(f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{ident}", session)
    sections = (data.get("jobAd") or {}).get("sections") or {}
    order = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")
    return _join(*((sections.get(key) or {}).get("text", "") for key in order))


def _workable(parts, session):
    match = _WORKABLE_PATH.search(parts.path)
    account = parts.path.strip("/").split("/")[0]
    if not match or not account or account == "api":
        return ""
    data = _get(f"https://apply.workable.com/api/v2/accounts/{account}/jobs/{match.group(1)}", session)
    return _join(data.get("description", ""), data.get("requirements", ""), data.get("benefits", ""))


def _oracle(parts, session):
    match = _ORACLE_PATH.search(parts.path)
    if not match:
        return ""
    site, ident = match.groups()
    api = (f"https://{parts.netloc}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
           f"?expand=all&onlyData=true&finder=ById;Id=%22{ident}%22,siteNumber={site}")
    items = _get(api, session).get("items") or []
    if not items:
        return ""
    item = items[0]
    return _join(*(item.get(key, "") or "" for key in (
        "ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")))


def _eightfold(parts, session):
    match = _EIGHTFOLD_PATH.search(parts.path)
    if not match:
        return ""
    company = parts.netloc.split(".")[0]
    data = _get(f"https://{parts.netloc}/api/apply/v2/jobs/{match.group(1)}", session, params={"domain": f"{company}.com"})
    return _join(data.get("job_description", ""))


def _walk_json_ld(node):
    if isinstance(node, list):
        for item in node:
            yield from _walk_json_ld(item)
    elif isinstance(node, dict):
        yield node
        for value in node.values():
            if isinstance(value, (list, dict)):
                yield from _walk_json_ld(value)


def _json_ld(url, session):
    """schema.org JobPosting description embedded in the posting page (iCIMS and many company sites)."""
    page = _get(url, session, as_json=False)
    for block in _JSON_LD.findall(page):
        try:
            data = json.loads(htmllib.unescape(block).strip())
        except ValueError:
            continue
        for node in _walk_json_ld(data):
            kind = node.get("@type")
            if (kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind)) and node.get("description"):
                return _join(node["description"])
    return ""


def _handler(host: str):
    if host.endswith("myworkdayjobs.com"):
        return _workday
    if "greenhouse.io" in host:
        return _greenhouse
    if host == "jobs.lever.co":
        return _lever
    if host == "jobs.ashbyhq.com":
        return _ashby
    if host in ("jobs.smartrecruiters.com", "careers.smartrecruiters.com"):
        return _smartrecruiters
    if host == "apply.workable.com":
        return _workable
    if host.endswith("oraclecloud.com"):
        return _oracle
    if host.endswith(".eightfold.ai"):
        return _eightfold
    return None


def fetch_description(url: str, session=None) -> str:
    """Plain-text job description for a posting link, or "" when it cannot be read."""
    parts = urlsplit((url or "").strip())
    if not parts.netloc:
        return ""
    host = parts.netloc.lower()
    handler = _handler(host)
    attempts = [lambda: handler(parts, session)] if handler else []
    attempts.append(lambda: _json_ld(url, session))
    for attempt in attempts:
        try:
            text = attempt()
        except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
            log.info("JD fetch failed for %s: %s", url, exc)
            continue
        # keep one block per line (the OPT / deadline finders read sentences); the sheet writer flattens it
        text = "\n".join(" ".join(line.split()) for line in (text or "").splitlines() if line.strip())
        if len(text) >= MIN_JD_CHARS:
            return text
    return ""
