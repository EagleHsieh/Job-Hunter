import logging
from collections import Counter
from datetime import date

from .extract import NOT_STATED, find_deadline, snippets
from .filters import Config, Evaluation, evaluate
from .models import Job
from .rank import match_percent, matched_keywords, title_score
from . import window
from .sheet import job_id, link_keys, role_key

log = logging.getLogger(__name__)


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
        "Date Added": date.today().isoformat(),
    }


def official_url(job: Job, cfg: Config) -> str:
    """The company's own posting page when config/targets.yaml knows its URL pattern, else the feed link."""
    template = cfg.official_links.get(job.company.strip().lower())
    ident = job_id(job.url)
    return template.format(id=ident) if template and ident else job.url


def process(jobs: list[Job], cfg: Config, seen_links: set[str], live=None):
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
        score = title_score(job.title, cfg, job.category)
        if score < cfg.min_score:
            stats[f"rejected: low title match (score under {cfg.min_score})"] += 1
            continue
        rkey = role_key(job.company, job.title)
        if rkey in seen_links:
            stats["skipped: same role already in sheet (other city)"] += 1
            continue
        check = (live or window.live_closed) if cfg.check_open else None
        reason = window.closed_reason(job, official_url(job, cfg), cfg.max_posting_age_days, live=check)
        if reason:
            log.info("not open: %s %s (%s)", job.company, job.title, reason)
            stats["rejected: application window closed"] += 1
            continue
        opt, visa = snippets(job.description)
        if evaluation.flags:
            suffix = f"[{', '.join(evaluation.flags)}]"
            visa = f"{NOT_STATED} {suffix}" if visa == NOT_STATED else f"{visa} {suffix}"
        seen_links |= keys
        seen_links.add(rkey)
        job.url = official_url(job, cfg)
        seen_links |= link_keys(job.url)
        record = to_record(job, evaluation, opt, visa)
        record["_score"] = score  # internal: used to rank, never written to the sheet
        record["Match Score"] = match_percent(score, cfg)  # title-based for now; JD-based matcher comes later
        record["Top Matching Keywords"] = matched_keywords(job.title, cfg)
        record["Submission Deadline"] = find_deadline(job.description)
        records.append(record)
        stats["new"] += 1
    return records, stats
