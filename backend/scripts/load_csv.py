"""Load a real spend export (CSV) into the DuckDB star schema.

Usage:
    python scripts/load_csv.py <path-to-csv> [--append] [--db spend.duckdb]

By default this REPLACES existing data (swap the demo seed for your data).
Use --append to add to what's already there (dimensions are de-duplicated by name).
The running API server picks up new data automatically on the next query
(no restart needed unless you changed .env).

Columns are matched case-insensitively and common aliases are accepted.
  Required : supplier_name, and one of (amount | unit_price)
  Strongly recommended : category, invoice_date
  Optional : business_unit, region, qty, currency, doc_type, doc_number,
             country, is_preferred, contract_id, contracted_unit_price,
             is_maverick, category_level1, category_code
"""
import argparse
import csv
import datetime as dt
import os
import re

import duckdb
from dotenv import load_dotenv

load_dotenv()

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(HERE, "sql", "schema.sql")

# canonical field -> accepted CSV header names (lower-cased)
FIELD_ALIASES = {
    "supplier_name": ["supplier_name", "supplier", "vendor", "vendor_name", "supplier name"],
    "category": ["category", "category_level2", "commodity", "spend_category", "category name"],
    "category_level1": ["category_level1", "category_l1", "parent_category"],
    "category_code": ["category_code", "unspsc", "code"],
    "business_unit": ["business_unit", "bu", "bu_name", "department", "cost_center", "business unit"],
    "region": ["region", "geo"],
    "invoice_date": ["invoice_date", "date", "posting_date", "document_date", "invoice date"],
    "qty": ["qty", "quantity", "units"],
    "unit_price": ["unit_price", "price", "unit price"],
    "amount": ["amount", "spend", "total", "net_amount", "value", "amount_usd"],
    "currency": ["currency", "curr"],
    "doc_type": ["doc_type", "document_type", "type"],
    "doc_number": ["doc_number", "document_number", "invoice_number", "po_number", "doc no"],
    "country": ["country", "supplier_country"],
    "is_preferred": ["is_preferred", "preferred", "preferred_supplier"],
    "contract_id": ["contract_id", "contract", "contract_no"],
    "contracted_unit_price": ["contracted_unit_price", "contract_price"],
    "is_maverick": ["is_maverick", "maverick", "off_contract"],
}

DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%b-%Y", "%m-%d-%Y", "%d.%m.%Y"]


def ensure_schema(con) -> None:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        sql = re.sub(r"--[^\n]*", "", f.read())
    for stmt in (s.strip() for s in sql.split(";") if s.strip()):
        con.execute(stmt)


def build_header_map(fieldnames: list[str]) -> dict[str, str]:
    lower = {fn.strip().lower(): fn for fn in fieldnames}
    resolved = {}
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in lower:
                resolved[field] = lower[alias]
                break
    return resolved


def parse_date(s: str | None):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(s) -> float | None:
    if s is None:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(s))
    if cleaned in ("", "-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_bool(s) -> bool:
    return str(s).strip().lower() in {"1", "true", "yes", "y", "t"}


def main() -> None:
    ap = argparse.ArgumentParser(description="Load a spend CSV into the DuckDB star schema.")
    ap.add_argument("csv_path", help="Path to the spend export CSV")
    ap.add_argument("--append", action="store_true", help="Append instead of replacing")
    ap.add_argument("--db", default=os.environ.get("DUCKDB_PATH", "spend.duckdb"))
    args = ap.parse_args()

    if not os.path.exists(args.csv_path):
        raise SystemExit(f"CSV not found: {args.csv_path}")

    try:
        con = duckdb.connect(args.db)
    except duckdb.Error as e:
        raise SystemExit(
            f"Could not open {args.db}. The API server may be using it — "
            f"stop it and retry, or wait until it is idle. ({e})"
        )

    try:
        ensure_schema(con)

        if args.append:
            suppliers = {n.casefold(): k for k, n in con.execute(
                "SELECT supplier_key, supplier_name FROM dim_supplier").fetchall()}
            categories = {n.casefold(): k for k, n in con.execute(
                "SELECT category_key, level2 FROM dim_category").fetchall()}
            bus = {n.casefold(): k for k, n in con.execute(
                "SELECT bu_key, bu_name FROM dim_business_unit").fetchall()}
            contracts = {c: k for k, c in con.execute(
                "SELECT contract_key, contract_id FROM dim_contract").fetchall()}

            def next_key(table: str, col: str) -> int:
                return con.execute(f"SELECT COALESCE(MAX({col}), 0) FROM {table}").fetchone()[0] + 1

            sk = next_key("dim_supplier", "supplier_key")
            ck = next_key("dim_category", "category_key")
            bk = next_key("dim_business_unit", "bu_key")
            ctk = next_key("dim_contract", "contract_key")
            fk = next_key("fact_spend", "spend_id")
        else:
            for table in ["fact_spend", "dim_contract", "dim_business_unit", "dim_category", "dim_supplier"]:
                con.execute(f"DELETE FROM {table}")
            suppliers, categories, bus, contracts = {}, {}, {}, {}
            sk = ck = bk = ctk = fk = 1

        new_suppliers, new_categories, new_bus, new_contracts, facts = [], [], [], [], []
        skipped = 0

        with open(args.csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            hmap = build_header_map(reader.fieldnames or [])
            if "supplier_name" not in hmap:
                raise SystemExit(f"No supplier column found. Detected headers: {reader.fieldnames}")
            if "amount" not in hmap and "unit_price" not in hmap:
                raise SystemExit("Need an 'amount' (or 'unit_price') column. Detected headers: "
                                 f"{reader.fieldnames}")

            def get(row, field):
                col = hmap.get(field)
                return row.get(col) if col else None

            for row in reader:
                supplier = (get(row, "supplier_name") or "").strip()
                if not supplier:
                    skipped += 1
                    continue

                qty = parse_amount(get(row, "qty"))
                qty = qty if qty else 1
                unit_price = parse_amount(get(row, "unit_price"))
                amount = parse_amount(get(row, "amount"))
                if amount is None and unit_price is not None:
                    amount = round(qty * unit_price, 2)
                if amount is None:
                    skipped += 1
                    continue

                cat2 = (get(row, "category") or "Uncategorised").strip() or "Uncategorised"
                cat1 = (get(row, "category_level1") or cat2).strip() or cat2
                code = (get(row, "category_code") or "").strip() or None
                bu = (get(row, "business_unit") or "Unknown").strip() or "Unknown"
                region = (get(row, "region") or "").strip() or None
                currency = (get(row, "currency") or "USD").strip() or "USD"
                doc_type = (get(row, "doc_type") or "AP").strip() or "AP"
                doc_number = (get(row, "doc_number") or "").strip() or None
                country = (get(row, "country") or "").strip() or None
                is_pref = parse_bool(get(row, "is_preferred")) if hmap.get("is_preferred") else False
                inv_date = parse_date(get(row, "invoice_date"))
                contract_id = (get(row, "contract_id") or "").strip()
                contracted_price = parse_amount(get(row, "contracted_unit_price"))

                key = supplier.casefold()
                if key not in suppliers:
                    suppliers[key] = sk
                    new_suppliers.append((sk, supplier[:3].upper(), supplier, None, country, is_pref))
                    sk += 1
                supplier_key = suppliers[key]

                ckey = cat2.casefold()
                if ckey not in categories:
                    categories[ckey] = ck
                    new_categories.append((ck, code, cat1, cat2, cat2, cat2))
                    ck += 1
                category_key = categories[ckey]

                bkey = bu.casefold()
                if bkey not in bus:
                    bus[bkey] = bk
                    new_bus.append((bk, bu[:6].upper(), bu, region))
                    bk += 1
                bu_key = bus[bkey]

                contract_key = None
                if contract_id:
                    if contract_id not in contracts:
                        contracts[contract_id] = ctk
                        new_contracts.append(
                            (ctk, contract_id, supplier_key, category_key, None, None,
                             contracted_price, None, currency))
                        ctk += 1
                    contract_key = contracts[contract_id]

                if hmap.get("is_maverick"):
                    is_maverick = parse_bool(get(row, "is_maverick"))
                else:
                    is_maverick = contract_key is None

                facts.append(
                    (fk, doc_type, doc_number, 1, supplier_key, category_key, bu_key, contract_key,
                     inv_date, qty, unit_price, amount, currency, None, is_maverick, "CSV"))
                fk += 1

        if new_suppliers:
            con.executemany(
                "INSERT INTO dim_supplier (supplier_key, supplier_id, supplier_name, parent_key, "
                "country, is_preferred) VALUES (?,?,?,?,?,?)", new_suppliers)
        if new_categories:
            con.executemany(
                "INSERT INTO dim_category (category_key, code, level1, level2, level3, level4) "
                "VALUES (?,?,?,?,?,?)", new_categories)
        if new_bus:
            con.executemany(
                "INSERT INTO dim_business_unit (bu_key, bu_code, bu_name, region) VALUES (?,?,?,?)",
                new_bus)
        if new_contracts:
            con.executemany(
                "INSERT INTO dim_contract (contract_key, contract_id, supplier_key, category_key, "
                "start_date, end_date, contracted_unit_price, committed_volume, currency) "
                "VALUES (?,?,?,?,?,?,?,?,?)", new_contracts)
        if facts:
            con.executemany(
                "INSERT INTO fact_spend (spend_id, doc_type, doc_number, line_no, supplier_key, "
                "category_key, bu_key, contract_key, invoice_date, qty, unit_price, amount, currency, "
                "classification_confidence, is_maverick, source_system) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", facts)

        total = con.execute("SELECT COUNT(*) FROM fact_spend").fetchone()[0]
    finally:
        con.close()

    mode = "appended" if args.append else "loaded"
    print(
        f"load_csv: {mode} {len(facts)} rows from {os.path.basename(args.csv_path)} "
        f"({skipped} skipped). fact_spend now has {total} rows. "
        f"New: suppliers +{len(new_suppliers)}, categories +{len(new_categories)}, "
        f"BUs +{len(new_bus)}, contracts +{len(new_contracts)}."
    )


if __name__ == "__main__":
    main()
