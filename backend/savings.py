"""Savings realisation tracker.

Turns the agent's spend findings into tracked savings opportunities and follows
each one through its lifecycle:

    identified -> negotiating -> contracted -> realised

The headline feature — and the honest answer to the tail-spend problem (lots of
small, fragmented buys across too many suppliers) — is that the *realised* saving
is **measured from the ledger**, never stored: once a change takes effect we
compare what the affected slice would have cost at the old run-rate against what
it actually cost. So ROI is provable, not just "here's an opportunity".

Design notes:
* The table lives in the same DuckDB file as the spend data and is created lazily
  (``_ensure``) so it works on an already-seeded database without a re-seed.
* Writes take ``DB_LOCK`` and use a read-write connection, mirroring ingest.
* Reads go through ``run_select`` (read-only). Slice values are always bound
  parameters, never string-interpolated.
"""
from __future__ import annotations

import datetime as dt

from db import DB_LOCK, get_ro_conn, get_rw_conn, run_select

STATUSES = ("identified", "negotiating", "contracted", "realised", "dismissed")
# The active pipeline, in order. "dismissed" is hidden; "realised" is terminal.
FLOW = ("identified", "negotiating", "contracted", "realised")
_STATUS_RANK = {s: i for i, s in enumerate(FLOW)}
_REALISING = ("contracted", "realised")

# Heuristic used only to *estimate* a consolidation target. It is surfaced verbatim
# in each opportunity's rationale, so the assumption behind the number is transparent.
# Heuristic rates used only to *estimate* savings targets. Each is surfaced verbatim in
# the opportunity's rationale so the assumption behind the number is transparent.
CONSOLIDATION_RATE = 0.10   # of spend on non-primary suppliers in a fragmented category
MAVERICK_RATE = 0.08        # of off-contract spend recoverable by going on-contract
TAIL_RATE = 0.10            # of long-tail spend recoverable by rationalising small suppliers
LOW_VALUE_THRESHOLD = 500.0    # a purchase below this is "low value" (process-cost heavy)
LOW_VALUE_PROCESS_COST = 60.0  # assumed cost to raise/process one purchase order
LOW_VALUE_REDUCTION = 0.5   # share of low-value POs assumed removable by consolidation

MIN_TARGET = 1000.0         # ignore trivially small suggestions
MAX_SUGGESTIONS = 24        # overall cap across all detection types
MAX_PER_KIND = 6            # cap per detection type so one kind can't flood the list
_MIN_SUPPLIERS = 3          # a category counts as "fragmented" at/above this many suppliers
_MIN_ITEM_SUPPLIERS = 2     # an item shows price variance at/above this many suppliers

_COLUMNS = (
    "id", "title", "kind", "category", "supplier", "item", "status", "target_annual",
    "baseline_annual", "baseline_date", "owner", "rationale", "source",
    "created_at", "updated_at",
)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS savings_opportunity (
    id              BIGINT PRIMARY KEY,
    title           TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'custom',
    category        TEXT,
    supplier        TEXT,
    item            TEXT,
    status          TEXT NOT NULL DEFAULT 'identified',
    target_annual   DOUBLE,
    baseline_annual DOUBLE,
    baseline_date   DATE,
    owner           TEXT,
    rationale       TEXT,
    source          TEXT NOT NULL DEFAULT 'manual',
    created_at      TIMESTAMP DEFAULT current_timestamp,
    updated_at      TIMESTAMP DEFAULT current_timestamp
)
"""


# --------------------------------------------------------------------------- helpers
def _ensure() -> None:
    """Create/upgrade the savings table lazily on the *existing* spend DB (idempotent).

    Only ever touches a database file that already exists, so we never leave behind a
    half-initialised DB missing the spend fact/views. Also migrates older tables that
    predate the ``item`` slice column.
    """
    con = get_ro_conn()  # raises if the DB file is missing -> the caller surfaces it
    try:
        con.execute("SELECT item FROM savings_opportunity LIMIT 1").fetchone()
        return  # table exists and already has the newest columns
    except Exception:  # noqa: BLE001 - table missing or missing a column
        pass
    finally:
        con.close()
    with DB_LOCK:
        con = get_rw_conn()
        try:
            con.execute(_CREATE_SQL)
            cols = {row[1] for row in con.execute("PRAGMA table_info('savings_opportunity')").fetchall()}
            if "item" not in cols:
                con.execute("ALTER TABLE savings_opportunity ADD COLUMN item TEXT")
        finally:
            con.close()


def _annual_factor() -> float:
    """Scale a whole-dataset total to an annual run-rate based on the date span."""
    row = run_select(
        "SELECT date_diff('day', MIN(invoice_date), MAX(invoice_date)) AS d "
        "FROM vw_spend WHERE invoice_date IS NOT NULL"
    )[0]
    span = int(row["d"] or 0)
    return 365.0 / span if span > 0 else 1.0


def _slice_clause(category, supplier, item=None) -> tuple[str, list]:
    """Build a parameterised WHERE fragment for an opportunity's measurement slice."""
    clauses, params = [], []
    if category:
        clauses.append("category_level2 = ?")
        params.append(category)
    if supplier:
        clauses.append("supplier_name = ?")
        params.append(supplier)
    if item:
        clauses.append("item = ?")
        params.append(item)
    clause = (" AND " + " AND ".join(clauses)) if clauses else ""
    return clause, params


def _slice_annual(category, supplier, item=None) -> float:
    """Annualised spend run-rate for a slice over the whole dataset."""
    clause, params = _slice_clause(category, supplier, item)
    row = run_select(
        f"SELECT COALESCE(SUM(amount), 0) AS spend FROM vw_spend WHERE 1=1{clause}",
        params,
    )[0]
    return round(float(row["spend"]) * _annual_factor(), 2)


def _realised(opp: dict) -> float:
    """Measure the saving realised so far for an opportunity, from the ledger.

    ``expected`` is what the slice would have cost since ``baseline_date`` at the
    captured run-rate; the realised saving is that minus what was actually spent
    (floored at 0, capped at the target so the demo can't show >100%).
    """
    if opp.get("status") not in _REALISING:
        return 0.0
    category, supplier, item = opp.get("category"), opp.get("supplier"), opp.get("item")
    if not (category or supplier or item):
        return 0.0  # portfolio-wide estimates (long-tail, low-value) aren't slice-measurable
    bdate, bannual = opp.get("baseline_date"), opp.get("baseline_annual")
    if not bdate or not bannual:
        return 0.0
    clause, params = _slice_clause(category, supplier, item)
    row = run_select(
        "SELECT COALESCE(SUM(amount), 0) AS spend, "
        "GREATEST(date_diff('day', ?, current_date), 0) AS days "
        f"FROM vw_spend WHERE invoice_date > ?{clause}",
        [bdate, bdate] + params,
    )[0]
    days = int(row["days"] or 0)
    post_spend = float(row["spend"] or 0.0)
    expected = float(bannual) * days / 365.0
    realised = max(0.0, expected - post_spend)
    target = opp.get("target_annual")
    if target:
        realised = min(realised, float(target))
    return round(realised, 2)


def _serialise(r: dict) -> dict:
    """Convert a raw DB row into a JSON-friendly dict (dates -> ISO strings)."""
    def d(v):
        return v.isoformat() if hasattr(v, "isoformat") else v

    def f(v):
        return float(v) if v is not None else None

    return {
        "id": int(r["id"]),
        "title": r["title"],
        "kind": r["kind"],
        "category": r["category"],
        "supplier": r["supplier"],
        "item": r["item"],
        "status": r["status"],
        "target_annual": f(r["target_annual"]),
        "baseline_annual": f(r["baseline_annual"]),
        "baseline_date": d(r["baseline_date"]),
        "owner": r["owner"],
        "rationale": r["rationale"],
        "source": r["source"],
        "created_at": d(r.get("created_at")),
        "updated_at": d(r.get("updated_at")),
    }


def _decorate(r: dict) -> dict:
    """Serialise a row and attach the measured realised amount + progress."""
    out = _serialise(r)
    realised = _realised(r)
    target = float(r["target_annual"]) if r["target_annual"] is not None else 0.0
    out["realised"] = realised
    out["pct_to_target"] = round(realised / target, 4) if target else None
    return out


# ----------------------------------------------------------------------------- reads
def list_opportunities() -> dict:
    """Every tracked opportunity (excluding dismissed) plus the pipeline rollup."""
    _ensure()
    rows = run_select(f"SELECT {', '.join(_COLUMNS)} FROM savings_opportunity WHERE status != 'dismissed'")
    items = [_decorate(r) for r in rows]
    items.sort(key=lambda o: (_STATUS_RANK.get(o["status"], 99), -(o["target_annual"] or 0.0)))
    return {"opportunities": items, "rollup": _rollup(items)}


def _rollup(items: list[dict]) -> dict:
    def target_sum(status: str) -> float:
        return round(sum(o["target_annual"] or 0.0 for o in items if o["status"] == status), 2)

    identified = target_sum("identified")
    negotiating = target_sum("negotiating")
    contracted = target_sum("contracted")
    realised = round(sum(o["realised"] for o in items), 2)
    return {
        "identified": identified,
        "negotiating": negotiating,
        "contracted": contracted,
        "realised": realised,
        "pipeline": round(identified + negotiating + contracted, 2),
        "count": len(items),
    }


def get_opportunity(opp_id: int) -> dict | None:
    rows = run_select(
        f"SELECT {', '.join(_COLUMNS)} FROM savings_opportunity WHERE id = ?", [int(opp_id)]
    )
    return _decorate(rows[0]) if rows else None


def detect_opportunities() -> list[dict]:
    """Scan the ledger for savings opportunities not already being tracked.

    Six grounded families, all aimed at the tail-spend problem:
      * consolidation   - a category bought from many suppliers (fragmentation);
      * price_variance  - the same item bought at different prices across suppliers;
      * maverick        - off-contract / non-preferred spend to route on-contract;
      * tail            - the long tail of small suppliers (last 20% of spend);
      * low_value       - many tiny purchase orders that are process-cost heavy;
      * overpayment     - invoices billed above an agreed contract price.
    """
    _ensure()
    factor = _annual_factor()
    existing = run_select("SELECT kind, category, supplier, item FROM savings_opportunity")
    taken = {(e["kind"], e["category"], e["supplier"], e["item"]) for e in existing}
    out: list[dict] = []

    def add(sug: dict) -> None:
        key = (sug["kind"], sug.get("category"), sug.get("supplier"), sug.get("item"))
        if key not in taken and sug["target_annual"] >= MIN_TARGET:
            out.append(sug)

    # 1) Fragmented categories -> consolidate onto the primary supplier.
    frag = run_select(
        "WITH per AS ("
        "  SELECT category_level2 AS category, supplier_name, SUM(amount) AS sup_spend "
        "  FROM vw_spend WHERE category_level2 IS NOT NULL AND supplier_name IS NOT NULL "
        "  GROUP BY 1, 2) "
        "SELECT category, COUNT(*) AS suppliers, SUM(sup_spend) AS spend, "
        "MAX(sup_spend) AS top_spend, arg_max(supplier_name, sup_spend) AS primary_supplier "
        f"FROM per GROUP BY category HAVING COUNT(*) >= {_MIN_SUPPLIERS} "
        "ORDER BY (SUM(sup_spend) - MAX(sup_spend)) DESC"
    )
    for f in frag[:MAX_PER_KIND]:
        spend_annual = float(f["spend"]) * factor
        addressable = (float(f["spend"]) - float(f["top_spend"])) * factor
        target = round(addressable * CONSOLIDATION_RATE, 2)
        suppliers = int(f["suppliers"])
        add({
            "kind": "consolidation",
            "title": f"Consolidate {f['category']}: {suppliers} suppliers \u2192 1 preferred",
            "category": f["category"],
            "supplier": None,
            "item": None,
            "target_annual": target,
            "rationale": (
                f"{f['category']} is fragmented across {suppliers} suppliers "
                f"(~${spend_annual:,.0f}/yr). Moving the ~${addressable:,.0f}/yr spread across "
                f"secondary suppliers onto {f['primary_supplier']} could save about "
                f"{int(CONSOLIDATION_RATE * 100)}% (~${target:,.0f}/yr) through better pricing "
                "and lower processing cost."
            ),
            "source": "auto",
        })

    # 2) Item price variance -> standardise to the cheapest supplier's price (exact gap).
    variance = run_select(
        "WITH per AS ("
        "  SELECT item, supplier_name, SUM(amount) AS spend, SUM(qty) AS qty "
        "  FROM vw_spend WHERE item IS NOT NULL AND qty > 0 AND unit_price IS NOT NULL "
        "  GROUP BY 1, 2 HAVING SUM(qty) > 0), "
        "agg AS ("
        "  SELECT item, COUNT(*) AS suppliers, SUM(spend) AS spend, "
        "         MIN(spend / qty) AS best_price, MAX(spend / qty) AS worst_price "
        f"  FROM per GROUP BY item HAVING COUNT(*) >= {_MIN_ITEM_SUPPLIERS}) "
        "SELECT a.item, a.suppliers, a.spend, a.best_price, a.worst_price, "
        "       SUM((p.spend / p.qty - a.best_price) * p.qty) AS savings "
        "FROM per p JOIN agg a USING (item) "
        "GROUP BY a.item, a.suppliers, a.spend, a.best_price, a.worst_price "
        "ORDER BY savings DESC"
    )
    for v in variance[:MAX_PER_KIND]:
        target = round(float(v["savings"]) * factor, 2)
        suppliers = int(v["suppliers"])
        spend_annual = float(v["spend"]) * factor
        add({
            "kind": "price_variance",
            "title": f"Standardise price of {v['item']} across {suppliers} suppliers",
            "category": None,
            "supplier": None,
            "item": v["item"],
            "target_annual": target,
            "rationale": (
                f"{v['item']} is bought from {suppliers} suppliers at "
                f"${float(v['best_price']):,.2f}\u2013${float(v['worst_price']):,.2f} per unit "
                f"(~${spend_annual:,.0f}/yr). Matching the lowest price on every purchase "
                f"would save ~${target:,.0f}/yr."
            ),
            "source": "auto",
        })

    # 3) Off-contract / maverick spend by category -> route on-contract.
    mav = run_select(
        "SELECT category_level2 AS category, "
        "SUM(amount) FILTER (WHERE is_maverick) AS maverick, SUM(amount) AS spend "
        "FROM vw_spend WHERE category_level2 IS NOT NULL GROUP BY 1 "
        "HAVING SUM(amount) FILTER (WHERE is_maverick) > 0 ORDER BY 2 DESC"
    )
    for m in mav[:MAX_PER_KIND]:
        maverick_annual = float(m["maverick"]) * factor
        target = round(maverick_annual * MAVERICK_RATE, 2)
        add({
            "kind": "maverick",
            "title": f"Bring off-contract {m['category']} on-contract",
            "category": m["category"],
            "supplier": None,
            "item": None,
            "target_annual": target,
            "rationale": (
                f"~${maverick_annual:,.0f}/yr of {m['category']} is bought off-contract or from "
                f"non-preferred suppliers. Routing it onto preferred contracts could save "
                f"~{int(MAVERICK_RATE * 100)}% (~${target:,.0f}/yr)."
            ),
            "source": "auto",
        })

    # 4) Long-tail suppliers -> rationalise the many small vendors (last 20% of spend).
    pareto = run_select(
        "WITH s AS (SELECT supplier_name, SUM(amount) AS spend FROM vw_spend "
        "WHERE supplier_name IS NOT NULL GROUP BY 1), "
        "r AS (SELECT supplier_name, spend, "
        "SUM(spend) OVER (ORDER BY spend DESC) AS running, SUM(spend) OVER () AS tot FROM s) "
        "SELECT supplier_name, spend, running / NULLIF(tot, 0) AS cumulative FROM r "
        "ORDER BY spend DESC"
    )
    tail = [p for p in pareto if (p["cumulative"] or 0) > 0.8]
    if tail:
        tail_annual = sum(float(p["spend"]) for p in tail) * factor
        add({
            "kind": "tail",
            "title": f"Rationalise {len(tail)} long-tail suppliers (last 20% of spend)",
            "category": None,
            "supplier": None,
            "item": None,
            "target_annual": round(tail_annual * TAIL_RATE, 2),
            "rationale": (
                f"{len(tail)} small suppliers together make up only the last 20% of spend "
                f"(~${tail_annual:,.0f}/yr) but most of the admin. Consolidating or dropping them "
                f"could save ~{int(TAIL_RATE * 100)}% (~${round(tail_annual * TAIL_RATE):,.0f}/yr) "
                "in price and processing. (Estimate \u2014 not tracked to one ledger slice.)"
            ),
            "source": "auto",
        })

    # 5) Many low-value purchases -> consolidate to cut processing cost.
    lv = run_select(
        "SELECT COUNT(*) AS txns FROM vw_spend WHERE amount < ?", [LOW_VALUE_THRESHOLD]
    )[0]
    txns_annual = float(lv["txns"]) * factor
    if txns_annual > 0:
        target = round(txns_annual * LOW_VALUE_REDUCTION * LOW_VALUE_PROCESS_COST, 2)
        add({
            "kind": "low_value",
            "title": f"Consolidate {int(txns_annual):,} low-value purchases (< ${int(LOW_VALUE_THRESHOLD)})",
            "category": None,
            "supplier": None,
            "item": None,
            "target_annual": target,
            "rationale": (
                f"~{int(txns_annual):,}/yr purchases are under ${int(LOW_VALUE_THRESHOLD)} each. "
                f"At ~${int(LOW_VALUE_PROCESS_COST)} to process each PO, removing "
                f"{int(LOW_VALUE_REDUCTION * 100)}% via catalogues/blanket orders could save "
                f"~${target:,.0f}/yr in processing cost. (Estimate \u2014 process savings.)"
            ),
            "source": "auto",
        })

    # 6) Contract overpayment -> recover leakage (exact, measured from unit prices).
    over = run_select(
        "SELECT supplier_name AS supplier, "
        "SUM((unit_price - contracted_unit_price) * qty) AS overpayment "
        "FROM vw_spend WHERE contract_id IS NOT NULL AND contracted_unit_price IS NOT NULL "
        "AND unit_price > contracted_unit_price GROUP BY 1 "
        "HAVING SUM((unit_price - contracted_unit_price) * qty) > 0 ORDER BY overpayment DESC"
    )
    for o in over[:MAX_PER_KIND]:
        target = round(float(o["overpayment"]) * factor, 2)
        add({
            "kind": "overpayment",
            "title": f"Recover contract overpayment: {o['supplier']}",
            "category": None,
            "supplier": o["supplier"],
            "item": None,
            "target_annual": target,
            "rationale": (
                f"Invoices from {o['supplier']} were billed above agreed contract prices "
                f"(~${target:,.0f}/yr over contract). Enforcing contracted rates recovers this."
            ),
            "source": "auto",
        })

    out.sort(key=lambda s: s["target_annual"], reverse=True)
    return out[:MAX_SUGGESTIONS]


# ---------------------------------------------------------------------------- writes
def _next_id(con) -> int:
    return int(con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM savings_opportunity").fetchone()[0])


def create_opportunity(data: dict) -> dict:
    _ensure()
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("A title is required.")
    status = data.get("status") or "identified"
    if status not in STATUSES:
        raise ValueError(f"Invalid status '{status}'.")

    category = data.get("category") or None
    supplier = data.get("supplier") or None
    item = data.get("item") or None
    target = data.get("target_annual")
    target = float(target) if target not in (None, "") else None

    # If the opportunity is created straight into the realisation phase, snapshot the
    # baseline run-rate now so realised savings can be measured against it.
    baseline_date = baseline_annual = None
    if status in _REALISING and (category or supplier or item):
        baseline_date = dt.date.today()
        baseline_annual = _slice_annual(category, supplier, item)

    with DB_LOCK:
        con = get_rw_conn()
        try:
            new_id = _next_id(con)
            con.execute(
                "INSERT INTO savings_opportunity "
                "(id, title, kind, category, supplier, item, status, target_annual, "
                "baseline_annual, baseline_date, owner, rationale, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [new_id, title[:200], data.get("kind") or "custom", category, supplier, item, status,
                 target, baseline_annual, baseline_date, data.get("owner") or None,
                 data.get("rationale") or None, data.get("source") or "manual"],
            )
        finally:
            con.close()
    return get_opportunity(new_id)


def update_opportunity(opp_id: int, patch: dict) -> dict | None:
    _ensure()
    current = run_select("SELECT * FROM savings_opportunity WHERE id = ?", [int(opp_id)])
    if not current:
        return None
    cur = current[0]

    fields: list[str] = []
    params: list = []

    if "status" in patch and patch["status"]:
        st = patch["status"]
        if st not in STATUSES:
            raise ValueError(f"Invalid status '{st}'.")
        fields.append("status = ?")
        params.append(st)
        # First time entering the realisation phase: capture the baseline run-rate.
        has_slice = cur["category"] or cur["supplier"] or cur["item"]
        entering = (st in _REALISING and has_slice
                    and not cur["baseline_date"] and not patch.get("baseline_date"))
        if entering:
            fields.append("baseline_date = ?")
            params.append(dt.date.today())
            fields.append("baseline_annual = ?")
            params.append(_slice_annual(cur["category"], cur["supplier"], cur["item"]))

    for col in ("title", "owner", "rationale", "category", "supplier", "item"):
        if col in patch:
            fields.append(f"{col} = ?")
            params.append(patch[col] or None)

    if "target_annual" in patch:
        v = patch["target_annual"]
        fields.append("target_annual = ?")
        params.append(float(v) if v not in (None, "") else None)

    if patch.get("baseline_date"):
        fields.append("baseline_date = ?")
        bd = patch["baseline_date"]
        params.append(dt.date.fromisoformat(bd) if isinstance(bd, str) else bd)

    if not fields:
        return get_opportunity(opp_id)

    fields.append("updated_at = current_timestamp")
    with DB_LOCK:
        con = get_rw_conn()
        try:
            con.execute(
                f"UPDATE savings_opportunity SET {', '.join(fields)} WHERE id = ?",
                params + [int(opp_id)],
            )
        finally:
            con.close()
    return get_opportunity(opp_id)


def delete_opportunity(opp_id: int) -> bool:
    _ensure()
    with DB_LOCK:
        con = get_rw_conn()
        try:
            existed = con.execute(
                "SELECT COUNT(*) FROM savings_opportunity WHERE id = ?", [int(opp_id)]
            ).fetchone()[0]
            con.execute("DELETE FROM savings_opportunity WHERE id = ?", [int(opp_id)])
        finally:
            con.close()
    return bool(existed)
