from collections import Counter

from .extract import NOT_STATED, snippets
from .filters import Config, Evaluation, evaluate
from .models import Job
from .sheet import job_id, link_keys


def to_record(job: Job, evaluation: Evaluation, opt: str, visa: str) -> dict:
    """Keys are the exact column headers of the Jobs tab."""
    return {
        "Company Name": job.company,
        "Role": job.title,
        "Industry": job.industry,
        "Role Posting Date": job.posted,
        "Level": evaluation.level,
        "Location": job.location,
        "Salary Range (from JD)": job.salary,
        "Posting Link": job.url,
        "OPT availability": opt,
        "Visa Sponsorship": visa,
    }


def official_url(job: Job, cfg: Config) -> str:
    """The company's own posting page when config/targets.yaml knows its URL pattern, else the feed link."""
    template = cfg.official_links.get(job.company.strip().lower())
    ident = job_id(job.url)
    return template.format(id=ident) if template and ident else job.url


def process(jobs: list[Job], cfg: Config, seen_links: set[str]):
    """Filter jobs, skip links already in the sheet, and return (records, stats)."""
    records: list[dict] = []
    stats: Counter = Counter()
    for job in jobs:
        keys = link_keys(job.url)
        if not keys:
            stats["skipped: no link"] += 1
            continue
        if keys & seen_links:
            stats["skipped: already in sheet"] += 1
            continue
        evaluation = evaluate(job, cfg)
        if not evaluation.keep:
            stats[f"rejected: {evaluation.reason}"] += 1
            continue
        opt, visa = snippets(job.description)
        if evaluation.flags:
            suffix = f"[{', '.join(evaluation.flags)}]"
            visa = f"{NOT_STATED} {suffix}" if visa == NOT_STATED else f"{visa} {suffix}"
        seen_links |= keys
        job.url = official_url(job, cfg)
        seen_links |= link_keys(job.url)
        records.append(to_record(job, evaluation, opt, visa))
        stats["new"] += 1
    return records, stats
