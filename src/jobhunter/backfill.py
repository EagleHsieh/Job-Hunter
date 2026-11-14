"""Fill the empty "Job Description" cells of rows already in the Jobs tab.

  python -m jobhunter.backfill --dry-run     # report what would be filled
  python -m jobhunter.backfill               # write the JDs (only blank cells; never overwrites)

Only rows with a blank Status (not applied yet) are touched unless --all-status is given. Nothing else in the
row changes, and the text is flattened to one line so row heights stay as they are. Rows whose JD says
citizenship / clearance / no sponsorship are listed at the end (they are NOT deleted here).
"""

import argparse
import logging
import sys

from . import jd
from .filters import HARD_EXCLUDE, NO_SPONSORSHIP
from .pipeline import clip_description
from .sheet import COMPANY_HEADER, JOBS_TAB, LINK_HEADER

log = logging.getLogger("jobhunter.backfill")
JD_HEADER = "Job Description"


def column_letter(index: int) -> str:
    """1 -> A, 27 -> AA."""
    letters = ""
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def run(worksheet, dry_run=False, all_status=False, limit=0, describe=None) -> dict:
    describe = describe or jd.fetch_description
    values = worksheet.get_all_values()
    headers = values[0]
    for name in (JD_HEADER, LINK_HEADER, COMPANY_HEADER, "Status"):
        if name not in headers:
            raise SystemExit(f"Jobs tab has no '{name}' column")
    col = {name: headers.index(name) for name in (JD_HEADER, LINK_HEADER, COMPANY_HEADER, "Status", "Role")}
    updates, unreadable, ineligible = [], [], []
    for number, row in enumerate(values[1:], start=2):
        row = row + [""] * (len(headers) - len(row))
        if not row[col[COMPANY_HEADER]].strip() or not row[col[LINK_HEADER]].strip() or row[col[JD_HEADER]].strip():
            continue
        if row[col["Status"]].strip() and not all_status:
            continue
        if limit and len(updates) + len(unreadable) >= limit:
            break
        label = f"{row[col[COMPANY_HEADER]]} - {row[col['Role']]}"
        text = describe(row[col[LINK_HEADER]].strip())
        if not text:
            unreadable.append(f"row {number}: {label}")
            continue
        flat = clip_description(text)
        updates.append({"range": f"{JOBS_TAB}!{column_letter(col[JD_HEADER] + 1)}{number}", "values": [[flat]]})
        if HARD_EXCLUDE.search(text) or NO_SPONSORSHIP.search(text):
            ineligible.append(f"row {number}: {label}")
    if updates and not dry_run:
        for start in range(0, len(updates), 20):  # small batches keep each API call well under the size limit
            worksheet.spreadsheet.values_batch_update(
                {"valueInputOption": "RAW", "data": updates[start:start + 20]})
    result = {"filled": len(updates), "unreadable": unreadable, "ineligible": ineligible}
    log.info("%s %d job descriptions", "would fill" if dry_run else "filled", len(updates))
    for title, rows in (("JD not readable", unreadable), ("JD says citizenship/clearance/no sponsorship (review)", ineligible)):
        if rows:
            log.info("%s:\n  %s", title, "\n  ".join(rows))
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--all-status", action="store_true", help="also rows whose Status is already set")
    parser.add_argument("--limit", type=int, default=0, help="stop after this many rows (0 = all)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    from .sheet import Sheet

    worksheet = Sheet.from_env()._sheet.worksheet(JOBS_TAB)
    run(worksheet, args.dry_run, args.all_status, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
