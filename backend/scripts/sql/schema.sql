-- Spend Analytics Agent - demo schema for embedded DuckDB (dims + fact + views).
-- Keys are assigned explicitly by seed_demo.py. No SERIAL, FKs, or roles needed.

CREATE TABLE IF NOT EXISTS dim_supplier (
    supplier_key   BIGINT PRIMARY KEY,
    supplier_id    TEXT,
    supplier_name  TEXT NOT NULL,
    parent_key     BIGINT,
    country        TEXT,
    is_preferred   BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS dim_category (
    category_key   BIGINT PRIMARY KEY,
    code           TEXT,
    level1         TEXT,
    level2         TEXT,
    level3         TEXT,
    level4         TEXT
);

CREATE TABLE IF NOT EXISTS dim_business_unit (
    bu_key   BIGINT PRIMARY KEY,
    bu_code  TEXT,
    bu_name  TEXT,
    region   TEXT
);

CREATE TABLE IF NOT EXISTS dim_contract (
    contract_key   BIGINT PRIMARY KEY,
    contract_id    TEXT,
    supplier_key   BIGINT,
    category_key   BIGINT,
    start_date     DATE,
    end_date       DATE,
    contracted_unit_price NUMERIC,
    committed_volume      NUMERIC,
    currency       TEXT DEFAULT 'USD'
);

CREATE TABLE IF NOT EXISTS fact_spend (
    spend_id       BIGINT PRIMARY KEY,
    doc_type       TEXT,
    doc_number     TEXT,
    line_no        INT,
    item_name      TEXT,
    supplier_key   BIGINT,
    category_key   BIGINT,
    bu_key         BIGINT,
    contract_key   BIGINT,
    invoice_date   DATE,
    qty            NUMERIC,
    unit_price     NUMERIC,
    amount         NUMERIC NOT NULL,
    currency       TEXT DEFAULT 'USD',
    classification_confidence NUMERIC,
    is_maverick    BOOLEAN,
    source_system  TEXT
);

-- Savings realisation tracker: each row is one savings opportunity followed through
-- its lifecycle (identified -> negotiating -> contracted -> realised). The realised
-- amount itself is MEASURED from the ledger, not stored, so ROI stays provable.
CREATE TABLE IF NOT EXISTS savings_opportunity (
    id              BIGINT PRIMARY KEY,
    title           TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'custom',   -- consolidation | price_variance | maverick | tail | low_value | overpayment | custom
    category        TEXT,                             -- measurement slice (category_level2)
    supplier        TEXT,                             -- measurement slice (supplier_name)
    item            TEXT,                             -- measurement slice (item / line item)
    status          TEXT NOT NULL DEFAULT 'identified',
    target_annual   DOUBLE,                           -- estimated annual saving target
    baseline_annual DOUBLE,                           -- run-rate captured when work began
    baseline_date   DATE,                             -- when the change took effect
    owner           TEXT,
    rationale       TEXT,
    source          TEXT NOT NULL DEFAULT 'manual',   -- auto (agent-detected) | manual
    created_at      TIMESTAMP DEFAULT current_timestamp,
    updated_at      TIMESTAMP DEFAULT current_timestamp
);

-- ---------- Curated semantic views (the only surface the agent may query) ----------

CREATE OR REPLACE VIEW vw_supplier AS
SELECT supplier_name, country, is_preferred
FROM dim_supplier;

CREATE OR REPLACE VIEW vw_category AS
SELECT code, level1, level2, level3, level4
FROM dim_category;

CREATE OR REPLACE VIEW vw_contract AS
SELECT ct.contract_id,
       s.supplier_name,
       c.level2 AS category_level2,
       ct.start_date,
       ct.end_date,
       ct.contracted_unit_price,
       ct.committed_volume
FROM dim_contract ct
LEFT JOIN dim_supplier s ON s.supplier_key = ct.supplier_key
LEFT JOIN dim_category c ON c.category_key = ct.category_key;

CREATE OR REPLACE VIEW vw_spend AS
SELECT f.spend_id,
       f.doc_type,
       f.invoice_date,
       s.supplier_name,
       s.is_preferred AS is_preferred_supplier,
       c.level1 AS category_level1,
       c.level2 AS category_level2,
       c.level3 AS category_level3,
       c.level4 AS category_level4,
       b.bu_name,
       b.region,
       f.qty,
       f.unit_price,
       f.amount,
       f.item_name AS item,
       f.is_maverick,
       ct.contract_id,
       ct.contracted_unit_price
FROM fact_spend f
LEFT JOIN dim_supplier s      ON s.supplier_key = f.supplier_key
LEFT JOIN dim_category c      ON c.category_key = f.category_key
LEFT JOIN dim_business_unit b ON b.bu_key = f.bu_key
LEFT JOIN dim_contract ct     ON ct.contract_key = f.contract_key;
