"""Rank roles within a company so only the best few reach the sheet each day.

This is a transparent keyword score on the job title (weights live in config/targets.yaml), not the
JD-based Match Score; that column stays blank until the resume matcher exists.
"""

from collections import defaultdict

from .filters import EARLY_TITLE, Config


def title_score(title: str, cfg: Config, category: str = "") -> int:
    low = title.lower()
    score = sum(weight for word, weight in cfg.title_weights.items() if word in low)
    score += cfg.early_career_bonus if EARLY_TITLE.search(title) else 0
    return score + (cfg.trusted_category_bonus if category in cfg.trusted_categories else 0)


def limit_per_company(records: list[dict], cap: int, recent=frozenset(), great_score=0, recent_cap=1):
    """Group records by company, best score first (ties: newest posting), keep at most `cap` each.

    Returns (kept records grouped by company with the strongest company first, number dropped).
    Duplicate titles at one company (same role in several cities) are collapsed to the first.
    A company in `recent` (fed to you lately, or already applied/engaged) only gets roles scoring at least
    `great_score`, and at most `recent_cap` of them: no flooding one employer's HR with applications.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        groups[record["Company Name"].strip().lower()].append(record)
    dropped = 0
    ordered = []
    for rows in groups.values():
        rows.sort(key=lambda r: (-r.get("_score", 0), _neg_date(r.get("Role Posting Date", "")), r["Role"]))
        kept, titles = [], set()
        in_cooldown = rows[0]["Company Name"].strip().lower() in recent
        limit = recent_cap if in_cooldown else cap
        for row in rows:
            title = row["Role"].strip().lower()
            if in_cooldown and row.get("_score", 0) < great_score:
                dropped += 1
                continue
            if title in titles or (limit and len(kept) >= limit):
                dropped += 1
                continue
            titles.add(title)
            kept.append(row)
        ordered.append(kept)
    ordered = [rows for rows in ordered if rows]
    ordered.sort(key=lambda rows: -max(r.get("_score", 0) for r in rows))
    return [record for rows in ordered for record in rows], dropped


def limit_company_total(records: list[dict], existing: dict[str, list[float]], cap: int):
    """Cap how many roles one company can have in the sheet overall (not just per day).

    `existing` maps a lower-case company name to the Match Scores of its rows already in the sheet.
    Once a company has `cap` rows, a new role is added only if its Match Score beats every role the
    company already has (a better role than anything you have seen there). Returns (kept, dropped).
    """
    scores = {company: list(values) for company, values in existing.items()}
    kept, dropped = [], 0
    for record in records:  # arrives best first within each company
        company = record["Company Name"].strip().lower()
        have = scores.setdefault(company, [])
        score = _number(record.get("Match Score"))
        if cap and len(have) >= cap and not (have and score > max(have)):
            dropped += 1
            continue
        have.append(score)
        kept.append(record)
    return kept, dropped


def _number(value) -> float:
    try:
        return float(str(value).strip().rstrip("%"))
    except ValueError:
        return 0.0


def _neg_date(value: str):
    # Newer first: invert the digits of YYYY-MM-DD; blank dates sort last.
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return -int(digits) if digits else 0


def limit_total(records: list[dict], cap: int):
    """Keep the `cap` highest-scoring records overall (ties: newest posting), preserving the grouped order.

    Roles that miss the cut are not marked as seen, so they come back on later days as the queue drains.
    Returns (kept, number dropped).
    """
    if not cap or len(records) <= cap:
        return records, 0
    ranked = sorted(
        range(len(records)),
        key=lambda i: (-records[i].get("_score", 0), _neg_date(records[i].get("Role Posting Date", "")), i),
    )
    keep = set(ranked[:cap])
    return [r for i, r in enumerate(records) if i in keep], len(records) - cap


def matched_keywords(title: str, cfg: Config) -> str:
    """The title keywords that earned points, strongest first (e.g. "asic, digital design")."""
    low = title.lower()
    hits = sorted(((w, word) for word, w in cfg.title_weights.items() if w > 0 and word in low), reverse=True)
    return ", ".join(word for _, word in hits)


def match_percent(score: int, cfg: Config) -> int:
    """Title score on a 0-100 scale (cfg.match_score_full points = 100)."""
    return max(0, min(100, round(score * 100 / cfg.match_score_full)))
