from collections import Counter

from .extract import NOT_STATED, snippets
from .filters import Config, Evaluation, evaluate
from .models import Job
from .sheet import normalize_url


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


def process(jobs: list[Job], cfg: Config, seen_links: set[str]):
    """Filter jobs, skip links already in the sheet, and return (records, stats)."""
    records: list[dict] = []
    stats: Counter = Counter()
    for job in jobs:
        key = normalize_url(job.url)
        if not key:
            stats["skipped: no link"] += 1
            continue
        if key in seen_links:
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
        seen_links.add(key)
        records.append(to_record(job, evaluation, opt, visa))
        stats["new"] += 1
    return records, stats
