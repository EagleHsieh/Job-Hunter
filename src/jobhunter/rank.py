"""Rank roles within a company so only the best few reach the sheet each day.

This is a transparent keyword score on the job title (weights live in config/targets.yaml), not the
JD-based Match Score; that column stays blank until the resume matcher exists.
"""

from collections import defaultdict

from .filters import EARLY_TITLE, Config


def title_score(title: str, cfg: Config) -> int:
    low = title.lower()
    score = sum(weight for word, weight in cfg.title_weights.items() if word in low)
    return score + (cfg.early_career_bonus if EARLY_TITLE.search(title) else 0)


def limit_per_company(records: list[dict], cap: int):
    """Group records by company, best score first (ties: newest posting), keep at most `cap` each.

    Returns (kept records grouped by company with the strongest company first, number dropped).
    Duplicate titles at one company (same role in several cities) are collapsed to the first.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        groups[record["Company Name"].strip().lower()].append(record)
    dropped = 0
    ordered = []
    for rows in groups.values():
        rows.sort(key=lambda r: (-r.get("_score", 0), _neg_date(r.get("Role Posting Date", "")), r["Role"]))
        kept, titles = [], set()
        for row in rows:
            title = row["Role"].strip().lower()
            if title in titles or (cap and len(kept) >= cap):
                dropped += 1
                continue
            titles.add(title)
            kept.append(row)
        ordered.append(kept)
    ordered.sort(key=lambda rows: -max(r.get("_score", 0) for r in rows))
    return [record for rows in ordered for record in rows], dropped


def _neg_date(value: str):
    # Newer first: invert the digits of YYYY-MM-DD; blank dates sort last.
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return -int(digits) if digits else 0
