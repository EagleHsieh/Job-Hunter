from ..models import Job
from ..text_utils import find_salary, iso_date, strip_html
from .base import get_json

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


def parse(item: dict, company: str) -> Job:
    description = strip_html(item.get("content", ""))
    # first_published is the original posting date when present; updated_at is only a fallback.
    posted = iso_date(item.get("first_published") or item.get("updated_at"))
    return Job(
        company=company,
        title=(item.get("title") or "").strip(),
        location=(item.get("location") or {}).get("name", ""),
        url=item.get("absolute_url", ""),
        source="greenhouse",
        posted=posted,
        description=description,
        salary=find_salary(description),
    )


def fetch(company: str, token: str, session=None) -> list[Job]:
    data = get_json(API.format(token=token), params={"content": "true"}, session=session)
    return [parse(item, company) for item in data.get("jobs", [])]
