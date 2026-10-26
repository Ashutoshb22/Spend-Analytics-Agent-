"""Seed the savings tracker with a realistic demo pipeline.

Run after the spend DB is seeded (init_db.py + seed_demo.py):
    python scripts/seed_savings.py

It detects real opportunities from the ledger, then spreads them across the
lifecycle. Contracted/realised items get a baseline dated in the past, chosen so
the app *measures* a believable share of the target as already realised — the
realised amount itself is still computed by the agent from the ledger.
"""
import datetime as dt

from dotenv import load_dotenv

load_dotenv()

import os  # noqa: E402
import sys  # noqa: E402

# Make the backend package importable when run as a plain script (python scripts/...).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import savings  # noqa: E402
from db import DB_LOCK, get_rw_conn, run_select  # noqa: E402

# (status, days since the change took effect, desired % of target realised so far).
# Only a few opportunities are tracked, so the rest stay as live "found" suggestions.
_PLAN = [
    ("realised", 300, 0.88),
    ("contracted", 160, 0.45),
    ("negotiating", None, None),
    ("identified", None, None),
]
_OWNERS = ["A. Kumar", "J. Chen", "M. Alvarez", "S. Okafor"]


def _post_spend(category, supplier, item, since) -> float:
    """Actual spend on a slice after ``since`` — the number the app measures against."""
    clause, params = savings._slice_clause(category, supplier, item)
    row = run_select(
        f"SELECT COALESCE(SUM(amount), 0) AS s FROM vw_spend WHERE invoice_date > ?{clause}",
        [since] + params,
    )[0]
    return float(row["s"])


def main() -> None:
    savings._ensure()
    # Clear first so detection sees a clean slate (it hides already-tracked items).
    with DB_LOCK:
        con = get_rw_conn()
        try:
            con.execute("DELETE FROM savings_opportunity")
        finally:
            con.close()

    suggestions = savings.detect_opportunities()
    if not suggestions:
        print("seed_savings: no opportunities detected — is the spend DB seeded?")
        return

    today = dt.date.today()
    rows = []
    for i, sug in enumerate(suggestions[: len(_PLAN)]):
        status, days_ago, frac = _PLAN[i]
        cat, sup, item = sug.get("category"), sug.get("supplier"), sug.get("item")
        baseline_date = baseline_annual = None
        if days_ago is not None and (cat or sup or item):
            baseline_date = today - dt.timedelta(days=days_ago)
            # Pick the captured baseline so the app measures realised == frac * target:
            #   realised = baseline_annual * days/365 - post_spend  ->  solve for baseline_annual.
            post = _post_spend(cat, sup, item, baseline_date)
            baseline_annual = round((frac * sug["target_annual"] + post) * 365.0 / days_ago, 2)
        rows.append((
            i + 1, sug["title"], sug["kind"], cat, sup, item,
            status, sug["target_annual"], baseline_annual, baseline_date,
            _OWNERS[i % len(_OWNERS)], sug.get("rationale"), "auto",
        ))

    with DB_LOCK:
        con = get_rw_conn()
        try:
            con.executemany(
                "INSERT INTO savings_opportunity (id, title, kind, category, supplier, item, status, "
                "target_annual, baseline_annual, baseline_date, owner, rationale, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        finally:
            con.close()

    print(f"seed_savings: inserted {len(rows)} savings opportunities across the pipeline.")


if __name__ == "__main__":
    main()
