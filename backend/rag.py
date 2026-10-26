"""Context retrieval for Text-to-SQL.

Minimal slice: returns a static, curated schema description plus a few
(question -> SQL) examples. A later phase replaces this with Qdrant similarity
retrieval over more examples and contract/policy chunks.
"""

# The agent is only ever allowed to query these curated views.
ALLOWED_VIEWS = {"vw_spend", "vw_supplier", "vw_category", "vw_contract"}

SCHEMA_DOC = """You may query ONLY these read-only PostgreSQL views:

vw_spend (one row per spend line):
  spend_id (int), doc_type ('AP'|'PO'), invoice_date (date),
  supplier_name (text), is_preferred_supplier (bool),
  category_level1, category_level2, category_level3, category_level4 (text),
  bu_name (text), region (text),
  qty (numeric), unit_price (numeric), amount (numeric),   -- amount is in USD
  item (text, NULL => not itemised),  -- specific product / line-item within a category
  is_maverick (bool),            -- true = off-contract / non-preferred supplier
  contract_id (text, NULL => off-contract), contracted_unit_price (numeric, NULL)

vw_supplier: supplier_name, country, is_preferred
vw_category: code, level1, level2, level3, level4
vw_contract: contract_id, supplier_name, category_level2, start_date, end_date,
             contracted_unit_price, committed_volume

Guidance:
- Total spend => SUM(amount).
- "off-contract" / "maverick" => is_maverick = true.
- Group common categories by category_level2 (e.g. 'IT Hardware', 'IT Software').
- "items" / "products" => the item column; GROUP BY item and filter category_level2.
- Match category / supplier / item names case-insensitively with ILIKE, using the FULL
  label the user gives (e.g. category_level2 ILIKE 'Category 1', never just '1').
- A named thing the user buys may be a broad CATEGORY (category_level2, e.g. 'IT Software')
  OR a specific ITEM (item, e.g. 'SaaS subscription', 'Laptop'). When it is not clearly a
  category, match it against BOTH columns so it is found either way:
  (category_level2 ILIKE '<name>' OR item ILIKE '<name>').
- Dates: Note that invoice dates in dataset are historical (2025). Do not filter by hardcoded current_date if it excludes historical dataset rows.
"""

FEWSHOT = [
    {
        "q": "Top 5 categories by spend this year",
        "sql": (
            "SELECT category_level2 AS category, SUM(amount) AS total_spend "
            "FROM vw_spend "
            "GROUP BY category_level2 ORDER BY total_spend DESC LIMIT 5;"
        ),
    },
    {
        "q": "How much did we spend off-contract on IT hardware last quarter, by BU?",
        "sql": (
            "SELECT bu_name, SUM(amount) AS off_contract_spend FROM vw_spend "
            "WHERE category_level2 ILIKE '%IT Hardware%' AND is_maverick = true "
            "GROUP BY bu_name ORDER BY off_contract_spend DESC;"
        ),
    },
    {
        "q": "Which suppliers did we overpay versus their contract price?",
        "sql": (
            "SELECT supplier_name, SUM((unit_price - contracted_unit_price) * qty) AS overpayment "
            "FROM vw_spend WHERE contract_id IS NOT NULL AND unit_price > contracted_unit_price "
            "GROUP BY supplier_name ORDER BY overpayment DESC;"
        ),
    },
    {
        "q": "Top 5 items I spent on in IT Hardware",
        "sql": (
            "SELECT item, SUM(amount) AS total_spend FROM vw_spend "
            "WHERE category_level2 ILIKE 'IT Hardware' AND item IS NOT NULL "
            "GROUP BY item ORDER BY total_spend DESC LIMIT 5;"
        ),
    },
    {
        "q": "The 5 items in category 1",
        "sql": (
            "SELECT item, SUM(amount) AS total_spend FROM vw_spend "
            "WHERE category_level2 ILIKE 'Category 1' AND item IS NOT NULL "
            "GROUP BY item ORDER BY total_spend DESC LIMIT 5;"
        ),
    },
    {
        "q": "what is the spend on SaaS subscription that is purchased from DHL",
        "sql": (
            "SELECT SUM(amount) AS total_spend FROM vw_spend "
            "WHERE (category_level2 ILIKE 'SaaS subscription' OR item ILIKE 'SaaS subscription') "
            "AND supplier_name ILIKE 'DHL';"
        ),
    },
]


def retrieve_context(question: str) -> str:
    """Return schema + few-shot examples to ground SQL generation."""
    examples = "\n\n".join(f"Q: {e['q']}\nSQL: {e['sql']}" for e in FEWSHOT)
    return f"{SCHEMA_DOC}\nExamples:\n{examples}"
