"""Load a small, deterministic synthetic dataset into DuckDB.

Run after init_db.py:
    python scripts/seed_demo.py
"""
import datetime as dt
import os
import random

import duckdb
from dotenv import load_dotenv

load_dotenv()

DB = os.environ.get("DUCKDB_PATH", "spend.duckdb")
random.seed(42)

CATEGORIES = [
    ("43211500", "Information Technology", "IT Hardware"),
    ("43230000", "Information Technology", "IT Software"),
    ("44120000", "Office", "Office Supplies"),
    ("78100000", "Logistics", "Freight & Logistics"),
    ("80100000", "Professional Services", "Consulting"),
    ("15100000", "Facilities", "Utilities"),
]

BUSINESS_UNITS = [
    ("BUW", "BU-West", "Americas"),
    ("BUE", "BU-East", "Americas"),
    ("BUN", "BU-North", "EMEA"),
]

SUPPLIERS = [
    ("Dell Technologies", "US", True),
    ("HP Inc.", "US", True),
    ("Lenovo", "CN", False),
    ("Microsoft", "US", True),
    ("Adobe", "US", False),
    ("Staples", "US", False),
    ("Office Depot", "US", False),
    ("DHL", "DE", True),
    ("FedEx", "US", False),
    ("Accenture", "IE", True),
    ("Deloitte", "US", False),
    ("Acme Utilities", "US", False),
]

# Representative line items per category (level 2) so line-item analytics have data.
ITEMS = {
    "IT Hardware": ["Laptop", "Desktop workstation", "27\" monitor", "Docking station",
                    "Keyboard & mouse", "Server blade"],
    "IT Software": ["SaaS subscription", "Database license", "Security suite",
                    "Cloud storage", "Collaboration seats", "Analytics platform"],
    "Office Supplies": ["Printer paper", "Toner cartridge", "Notebooks", "Pens (box)",
                        "Desk organiser", "Whiteboard"],
    "Freight & Logistics": ["Air freight", "Ocean freight", "Courier delivery",
                            "Warehousing", "Last-mile delivery", "Customs handling"],
    "Consulting": ["Advisory engagement", "Implementation services", "Staff augmentation",
                   "Audit services", "Training workshop"],
    "Utilities": ["Electricity", "Water", "Natural gas", "Waste management",
                  "Facilities maintenance"],
}


def main() -> None:
    con = duckdb.connect(DB)
    try:
        for table in ["fact_spend", "dim_contract", "dim_business_unit", "dim_category", "dim_supplier"]:
            con.execute(f"DELETE FROM {table}")

        supplier_rows = [
            (i, name[:3].upper(), name, None, country, pref)
            for i, (name, country, pref) in enumerate(SUPPLIERS, start=1)
        ]
        con.executemany(
            "INSERT INTO dim_supplier (supplier_key, supplier_id, supplier_name, "
            "parent_key, country, is_preferred) VALUES (?,?,?,?,?,?)",
            supplier_rows,
        )
        preferred_by_key = {row[0]: row[5] for row in supplier_rows}
        supplier_keys = [row[0] for row in supplier_rows]

        category_rows = [
            (i, code, l1, l2, l2, l2)
            for i, (code, l1, l2) in enumerate(CATEGORIES, start=1)
        ]
        con.executemany(
            "INSERT INTO dim_category (category_key, code, level1, level2, level3, level4) "
            "VALUES (?,?,?,?,?,?)",
            category_rows,
        )
        category_keys = [row[0] for row in category_rows]

        bu_rows = [
            (i, code, name, region)
            for i, (code, name, region) in enumerate(BUSINESS_UNITS, start=1)
        ]
        con.executemany(
            "INSERT INTO dim_business_unit (bu_key, bu_code, bu_name, region) VALUES (?,?,?,?)",
            bu_rows,
        )
        bu_keys = [row[0] for row in bu_rows]

        # One contract per preferred supplier, for a random category.
        contract_rows = []
        contracts: dict[tuple[int, int], tuple[int, float]] = {}
        contract_key = 1
        contract_id = 1000
        for skey in supplier_keys:
            if not preferred_by_key[skey]:
                continue
            cat_key = random.choice(category_keys)
            price = round(random.uniform(50, 500), 2)
            contract_rows.append(
                (contract_key, f"C-{contract_id}", skey, cat_key,
                 dt.date(2025, 1, 1), dt.date(2026, 12, 31), price, 1000, "USD")
            )
            contracts[(skey, cat_key)] = (contract_key, price)
            contract_key += 1
            contract_id += 1
        if contract_rows:
            con.executemany(
                "INSERT INTO dim_contract (contract_key, contract_id, supplier_key, category_key, "
                "start_date, end_date, contracted_unit_price, committed_volume, currency) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                contract_rows,
            )

        today = dt.date.today()
        cat_name_by_key = {row[0]: row[3] for row in category_rows}
        # Independent RNG for item names so they don't shift the other random draws
        # (amounts, dates, suppliers) — keeps the rest of the dataset identical.
        item_rng = random.Random(20260717)
        fact_rows = []
        for i in range(600):
            idx = random.randrange(len(supplier_keys))
            skey = supplier_keys[idx]
            preferred = preferred_by_key[skey]
            cat_key = random.choice(category_keys)
            bu_key = random.choice(bu_keys)
            inv_date = today - dt.timedelta(days=random.randint(0, 460))
            qty = random.randint(1, 50)

            contract = contracts.get((skey, cat_key))
            if contract and random.random() < 0.7:
                c_key, base_price = contract
                unit_price = round(base_price * random.choice([1.0, 1.0, 1.05, 1.15]), 2)
                is_maverick = not preferred
                contract_ref = c_key
            else:
                contract_ref = None
                unit_price = round(random.uniform(50, 500), 2)
                is_maverick = True

            amount = round(qty * unit_price, 2)
            item_name = item_rng.choice(ITEMS[cat_name_by_key[cat_key]])
            fact_rows.append(
                (i + 1, random.choice(["AP", "PO"]), f"D-{10000 + i}", 1, item_name, skey, cat_key, bu_key,
                 contract_ref, inv_date, qty, unit_price, amount, "USD",
                 round(random.uniform(0.6, 1.0), 2), is_maverick, "DEMO")
            )

        # A realistic tail of small, low-value purchases (qty 1, cheap) using an
        # independent RNG so the 600 rows above stay identical. These create the
        # "hundreds of tiny POs" process-cost problem the savings tracker flags.
        low_rng = random.Random(99001)
        n_main = len(fact_rows)
        for j in range(120):
            skey = low_rng.choice(supplier_keys)
            cat_key = low_rng.choice(category_keys)
            bu_key = low_rng.choice(bu_keys)
            inv_date = today - dt.timedelta(days=low_rng.randint(0, 460))
            unit_price = round(low_rng.uniform(12, 180), 2)  # small -> amount < $500
            item_name = low_rng.choice(ITEMS[cat_name_by_key[cat_key]])
            fact_rows.append(
                (n_main + j + 1, "PO", f"D-{20000 + j}", 1, item_name, skey, cat_key, bu_key,
                 None, inv_date, 1, unit_price, unit_price, "USD",
                 round(low_rng.uniform(0.6, 1.0), 2), True, "DEMO")
            )
        con.executemany(
            "INSERT INTO fact_spend (spend_id, doc_type, doc_number, line_no, item_name, supplier_key, "
            "category_key, bu_key, contract_key, invoice_date, qty, unit_price, amount, currency, "
            "classification_confidence, is_maverick, source_system) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            fact_rows,
        )

        count = con.execute("SELECT COUNT(*) FROM fact_spend").fetchone()[0]
    finally:
        con.close()

    print(
        f"seed_demo: inserted {count} spend lines, {len(SUPPLIERS)} suppliers, "
        f"{len(CATEGORIES)} categories, {len(BUSINESS_UNITS)} business units."
    )


if __name__ == "__main__":
    main()
