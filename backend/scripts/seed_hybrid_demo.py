"""One-off demo setup for the hybrid documents feature.

Appends a clean batch of "Office Chair" purchases at unit price 6,000 so the
agent can compare them against a contract PDF/doc that says 5,000. The contract
price is NOT stored in the DB on purpose - it only lives in the uploaded
document, which is exactly what this feature demonstrates.
"""
import duckdb

con = duckdb.connect("spend.duckdb")

# Reuse the keys of an existing furniture-ish row so the new lines join cleanly
# to a real supplier / category / business unit in the views.
ref = con.execute(
    "select supplier_key, category_key, bu_key from fact_spend "
    "where item_name ilike '%chair%' limit 1"
).fetchone()
if ref is None:
    ref = con.execute(
        "select supplier_key, category_key, bu_key from fact_spend limit 1"
    ).fetchone()
supplier_key, category_key, bu_key = ref

# Remove any prior run of this demo batch so it is idempotent.
con.execute("delete from fact_spend where doc_number = 'DEMO-CHAIRS-001'")

start_id = con.execute("select coalesce(max(spend_id), 0) from fact_spend").fetchone()[0]

rows = []
for i in range(10):
    rows.append((
        start_id + 1 + i,      # spend_id
        "INVOICE",             # doc_type
        "DEMO-CHAIRS-001",     # doc_number
        i + 1,                 # line_no
        "Office Chair",        # item_name
        supplier_key,
        category_key,
        bu_key,
        None,                  # contract_key -> price comes from the document only
        "2024-11-15",          # invoice_date
        1,                     # qty
        6000,                  # unit_price
        6000,                  # amount
        "USD",                 # currency (label only; magnitudes are the point)
        None,                  # classification_confidence
        False,                 # is_maverick
        "demo",                # source_system
    ))

con.executemany(
    """
    insert into fact_spend
        (spend_id, doc_type, doc_number, line_no, item_name, supplier_key,
         category_key, bu_key, contract_key, invoice_date, qty, unit_price,
         amount, currency, classification_confidence, is_maverick, source_system)
    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    rows,
)
con.close()

check = duckdb.connect("spend.duckdb", read_only=True)
print("Office Chair rows now:")
print(check.execute(
    "select item, count(1) n, avg(unit_price) unit, sum(amount) tot "
    "from vw_spend where item = 'Office Chair' group by 1"
).fetchall())
check.close()
