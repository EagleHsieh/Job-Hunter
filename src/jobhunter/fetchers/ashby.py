from ..models import Job
from ..text_utils import find_salary, iso_date, strip_html
from .base import get_json

API = "https://api.ashbyhq.com/posting-api/job-board/{token}"


def parse(item: dict, company: str) -> Job:
    description = item.get("descriptionPlain") or strip_html(item.get("descriptionHtml", ""))
    locations = [item.get("location", "")]
    for extra in item.get("secondaryLocations") or []:
        locations.append(extra.get("location", "") if isinstance(extra, dict) else str(extra))
    compensation = item.get("compensation") or {}
    salary = compensation.get("compensationTierSummary") or find_salary(description)
    return Job(
        company=company,
        title=(item.get("title") or "").strip(),
        location="; ".join(loc for loc in locations if loc),
        url=item.get("jobUrl", ""),
        source="ashby",
        posted=iso_date(item.get("publishedAt")),
        description=description,
        salary=salary,
        commitment=item.get("employmentType", ""),
    )


def fetch(company: str, token: str, session=None) -> list[Job]:
    data = get_json(
        API.format(token=token), params={"includeCompensation": "true"}, session=session
    )
    return [
        parse(item, company) for item in data.get("jobs", []) if item.get("isListed") is not False
    ]
