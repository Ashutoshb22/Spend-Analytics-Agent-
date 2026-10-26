"""Tests for the upload cleaning + loading pipeline (no SLM, isolated temp DB).

Run:  python -m pytest -q tests/test_ingest.py
"""
import duckdb

from ingest import ingest_bytes

# A deliberately messy export:
#  - a title/preamble row before the real header,
#  - alias column names (Vendor, Business Unit, ...),
#  - currency symbols + thousands separators in amounts,
#  - mixed date formats,
#  - a duplicate supplier row (dimension must be de-duplicated),
#  - a row with no amount (must be skipped),
#  - a fully blank row (must be ignored).
MESSY_CSV = (
    "Acme Corp Spend Export,,,,,,\n"
    "Vendor,Invoice Date,Amount,Qty,Unit Price,Category,Business Unit\n"
    'Dell Technologies,2025-01-15,"$1,200.00",2,$600.00,IT Hardware,BU-West\n'
    'HP Inc.,01/20/2025,"$2,500.00",5,$500.00,IT Hardware,BU-East\n'
    "Staples,2025/02/01,300,10,30,Office Supplies,BU-West\n"
    'Microsoft,2025-02-10,"$4,000.00",4,$1000.00,IT Software,BU-North\n'
    'Dell Technologies,2025-01-15,"$1,200.00",2,$600.00,IT Hardware,BU-West\n'
    "Lenovo,2025-03-01,,,,IT Hardware,BU-West\n"
    ",,,,,,\n"
)


def test_ingest_cleans_and_loads(tmp_path):
    db = str(tmp_path / "spend.duckdb")
    summary = ingest_bytes(
        MESSY_CSV.encode("utf-8"), "spend.csv", db_path=db, mode="replace", use_slm=False
    )

    # Header auto-detected past the preamble row.
    assert summary["header_row_index"] == 1
    assert summary["mapping_method"].startswith("column aliases")

    # Lenovo (no amount) skipped; the duplicate Dell row still loads as a fact line.
    assert summary["rows_loaded"] == 5
    assert summary["rows_skipped"] == 1

    # Dell appears twice but the supplier dimension is de-duplicated.
    assert summary["new_suppliers"] == 4

    mapped = summary["columns_mapped"]
    assert mapped.get("supplier_name") == "Vendor"
    assert mapped.get("amount") == "Amount"

    con = duckdb.connect(db, read_only=True)
    try:
        total = con.execute("SELECT SUM(amount) FROM vw_spend").fetchone()[0]
        suppliers = con.execute("SELECT COUNT(*) FROM dim_supplier").fetchone()[0]
        lines = con.execute("SELECT COUNT(*) FROM vw_spend").fetchone()[0]
    finally:
        con.close()

    # 1200 + 2500 + 300 + 4000 + 1200(dup) = 9200, with symbols/commas stripped.
    assert abs(float(total) - 9200.0) < 0.01
    assert suppliers == 4
    assert lines == 5


def test_ingest_rejects_file_without_required_columns(tmp_path):
    db = str(tmp_path / "spend.duckdb")
    bad = b"colour,shape\nred,circle\nblue,square\n"
    try:
        ingest_bytes(bad, "junk.csv", db_path=db, mode="replace", use_slm=False)
        raised = False
    except ValueError:
        raised = True
    assert raised, "Expected a ValueError when no supplier/amount columns are present"


def test_ingest_handles_tab_delimited(tmp_path):
    db = str(tmp_path / "spend.duckdb")
    tsv = (
        "Vendor\tInvoice Date\tAmount\tCategory\n"
        "Dell\t2025-01-01\t100\tIT Hardware\n"
        "HP\t2025-01-02\t200\tIT Hardware\n"
    )
    summary = ingest_bytes(tsv.encode("utf-8"), "spend.tsv", db_path=db, mode="replace", use_slm=False)
    assert summary["rows_loaded"] == 2
    assert summary["columns_mapped"].get("supplier_name") == "Vendor"
    assert summary["columns_mapped"].get("amount") == "Amount"
