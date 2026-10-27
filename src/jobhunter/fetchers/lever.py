from ..models import Job
from ..text_utils import epoch_ms_date, find_salary, strip_html
from .base import get_json

API = "https://api.lever.co/v0/postings/{token}"


def _salary(item: dict) -> str:
    salary_range = item.get("salaryRange")
    if isinstance(salary_range, dict) and salary_range.get("min") and salary_range.get("max"):
        currency = salary_range.get("currency", "USD")
        return f"{currency} {int(salary_range['min']):,} - {int(salary_range['max']):,}"
    return ""


def parse(item: dict, company: str) -> Job:
    categories = item.get("categories") or {}
    locations = categories.get("allLocations") or [categories.get("location", "")]
    parts = [item.get("descriptionPlain", "")]
    for block in item.get("lists") or []:
        parts.append(block.get("text", ""))
        parts.append(strip_html(block.get("content", "")))
    parts.append(item.get("additionalPlain", ""))
    description = "\n".join(part for part in parts if part)
    return Job(
        company=company,
        title=(item.get("text") or "").strip(),
        location="; ".join(loc for loc in locations if loc),
        url=item.get("hostedUrl", ""),
        source="lever",
        posted=epoch_ms_date(item.get("createdAt")),
        description=description,
        salary=_salary(item) or find_salary(description),
        commitment=categories.get("commitment", ""),
    )


def fetch(company: str, token: str, session=None) -> list[Job]:
    data = get_json(API.format(token=token), params={"mode": "json"}, session=session)
    return [parse(item, company) for item in data]
