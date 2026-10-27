"""Entry point.

  python -m jobhunter.main                       # read Watchlist, fetch, filter, append to sheet
  python -m jobhunter.main --dry-run             # same, but print instead of writing
  python -m jobhunter.main --dry-run --board greenhouse:stripe:Stripe
                                                 # no Google credentials needed
"""

import argparse
import logging
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .fetchers import FETCHERS, board_token, simplify
from .fetchers.base import BoardNotFound, FetchError
from .filters import Config
from .pipeline import process
from .rank import limit_per_company

log = logging.getLogger("jobhunter")
DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "targets.yaml"


@dataclass
class Target:
    company: str
    ats: str
    token: str
    industry: str = ""


def targets_from_watchlist(rows: list[dict]) -> list[Target]:
    """Companies with a known ATS and board token; skips rows marked Excluded."""
    targets = []
    for row in rows:
        company = str(row.get("Company", "")).strip()
        ats = str(row.get("ATS Type", "")).strip().lower()
        token = board_token(ats, str(row.get("Board URL / Token", "")))
        notes = str(row.get("Sponsorship Notes", "")).strip().lower()
        if not company or ats not in FETCHERS or not token or notes.startswith("excluded"):
            continue
        targets.append(Target(company, ats, token, str(row.get("Industry", "")).strip()))
    return targets


def excluded_companies(rows: list[dict]) -> set[str]:
    """Watchlist companies marked Excluded (no sponsorship, passed, ignore): never surfaced by discovery."""
    return {
        str(r.get("Company", "")).strip().lower()
        for r in rows
        if str(r.get("Sponsorship Notes", "")).strip().lower().startswith("excluded")
    }


def parse_board_args(values: list[str]) -> list[Target]:
    targets = []
    for value in values:
        ats, token, company = (value.split(":", 2) + [""])[:3]
        if ats not in FETCHERS or not token:
            raise SystemExit(f"--board expects ats:token[:Company] with ats in {sorted(FETCHERS)}")
        targets.append(Target(company or token, ats, token))
    return targets


def run(args) -> int:
    cfg = Config.from_yaml(args.config)
    sheet = None
    excluded: set[str] = set()
    if args.board:
        targets = parse_board_args(args.board)
    else:
        from .sheet import Sheet

        sheet = Sheet.from_env()
        watchlist = sheet.watchlist()
        targets = targets_from_watchlist(watchlist)
        excluded = excluded_companies(watchlist)
        log.info("%d watchlist companies have a known job-board feed", len(targets))

    if not args.dry_run and sheet is None:
        from .sheet import Sheet

        sheet = Sheet.from_env()
    seen = sheet.existing_links() if sheet else set()

    all_records: list[dict] = []
    totals: Counter = Counter()
    for target in targets:
        try:
            jobs = FETCHERS[target.ats](target.company, target.token)
        except BoardNotFound:
            log.warning("%s: no %s board named %r", target.company, target.ats, target.token)
            totals["boards not found"] += 1
            continue
        except FetchError as exc:
            log.warning("%s: fetch failed: %s", target.company, exc)
            totals["fetch errors"] += 1
            continue
        for job in jobs:
            job.industry = target.industry
        records, stats = process(jobs, cfg, seen)
        totals.update(stats)
        all_records.extend(records)
        log.info("%s: %d postings, %d new", target.company, len(jobs), len(records))

    if cfg.discovery_categories and not args.no_discovery:
        try:
            found = [j for j in simplify.fetch(cfg.discovery_categories) if j.company.lower() not in excluded]
        except FetchError as exc:
            log.warning("discovery list unavailable: %s", exc)
            totals["fetch errors"] += 1
        else:
            records, stats = process(found, cfg, seen)
            totals.update(stats)
            all_records.extend(records)
            log.info("discovery: %d listings, %d new", len(found), len(records))

    all_records, dropped = limit_per_company(all_records, cfg.max_per_company)
    if dropped:
        totals[f"skipped: beyond top {cfg.max_per_company} per company (or same title again)"] += dropped

    if args.max_new:
        all_records = all_records[: args.max_new]

    for key, count in sorted(totals.items()):
        log.info("%6d  %s", count, key)

    if args.dry_run or sheet is None:
        for record in all_records:
            print(" | ".join([str(record.get("_score", ""))] + [str(record[k]) for k in ("Company Name", "Role", "Location", "Posting Link")]))
        log.info("dry run: %d rows would be added", len(all_records))
        return 0

    added = sheet.append_jobs(all_records)
    log.info("added %d rows to the Jobs tab", added)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print rows instead of writing the sheet")
    parser.add_argument("--board", action="append", default=[], help="ats:token[:Company]; skips the sheet")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--no-discovery", action="store_true", help="skip the unknown-company discovery list")
    parser.add_argument("--max-new", type=int, default=0, help="cap rows written in one run (0 = no cap)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
