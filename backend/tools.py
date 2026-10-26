"""Agent tool registry for Spend Analytics system (Phase 1).

Exposes core analytical, retrieval, classification, and savings detection capabilities
as structured, schema-validated tools for autonomous LLM agents (LangGraph / ReAct).
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

import documents
import metrics
import nlq
import rag
import savings
from classify import classify_upload


# ---------------------------------------------------------------------------
# Pydantic Schemas for Tool Inputs
# ---------------------------------------------------------------------------

class ExecuteQueryInput(BaseModel):
    sql: str = Field(
        ...,
        description=(
            "Valid DuckDB SQL SELECT query. Query ONLY allowed views: vw_spend, vw_supplier, "
            "vw_category, vw_contract. Do not attempt data modification (INSERT/UPDATE/DELETE)."
        ),
    )


class SearchDocumentsInput(BaseModel):
    query: str = Field(
        ...,
        description="Search query to retrieve clauses from contracts, SLAs, policy files, and PDF documents.",
    )
    top_k: int = Field(
        default=4,
        description="Maximum number of document chunks to return (1 to 10).",
    )


class DetectSavingsInput(BaseModel):
    kind: Optional[str] = Field(
        default=None,
        description=(
            "Filter savings opportunity detection by type: 'consolidation', 'price_variance', "
            "'maverick', 'tail_spend', 'low_value_po', or None to detect all opportunity kinds."
        ),
    )


class GetDatabaseSchemaInput(BaseModel):
    question: Optional[str] = Field(
        default="",
        description="Optional context question to fetch tailored schema documentation and relevant few-shot SQL examples.",
    )


class ClassifySpendItemInput(BaseModel):
    description: str = Field(
        ...,
        description="Line item description, product name, or invoice text to classify into procurement categories.",
    )


class ComputeSpendMetricsInput(BaseModel):
    timeframe: Optional[str] = Field(
        default="all",
        description="Timeframe for spend metric aggregation (e.g., 'all', 'ytd', 'q3').",
    )


# ---------------------------------------------------------------------------
# Standalone Tool Functions
# ---------------------------------------------------------------------------

def execute_sql_query(sql: str) -> Dict[str, Any]:
    """Validate and execute a SQL query against the spend database.
    
    Returns structured result rows or error diagnostics.
    """
    try:
        validated = nlq.validate_sql(sql)
        rows = nlq.execute_sql(validated)
        return {
            "success": True,
            "sql": validated,
            "row_count": len(rows),
            "rows": rows,
        }
    except Exception as e:
        return {
            "success": False,
            "sql": sql,
            "error": str(e),
            "row_count": 0,
            "rows": [],
        }


def search_contract_documents(query: str, top_k: int = 4) -> Dict[str, Any]:
    """Retrieve relevant contract and policy excerpts using semantic/hybrid search."""
    try:
        top_k = max(1, min(top_k, 10))
        chunks = documents.search(query, k=top_k)
        return {
            "success": True,
            "query": query,
            "count": len(chunks),
            "results": chunks,
        }
    except Exception as e:
        return {
            "success": False,
            "query": query,
            "error": str(e),
            "count": 0,
            "results": [],
        }


def detect_savings_opportunities(kind: Optional[str] = None) -> Dict[str, Any]:
    """Run procurement analytics heuristics to detect actionable cost savings opportunities."""
    try:
        opps = savings.detect_opportunities()
        if kind:
            opps = [o for o in opps if o.get("kind") == kind]
        return {
            "success": True,
            "opportunity_count": len(opps),
            "opportunities": opps,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "opportunity_count": 0,
            "opportunities": [],
        }


def get_database_schema(question: Optional[str] = "") -> Dict[str, Any]:
    """Fetch DuckDB spend table schemas, view definitions, column types, and sample queries."""
    try:
        context_str = rag.retrieve_context(question or "")
        return {
            "success": True,
            "allowed_views": list(rag.ALLOWED_VIEWS),
            "context": context_str,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "allowed_views": [],
            "context": "",
        }


def classify_spend_item(description: str) -> Dict[str, Any]:
    """Classify a spend line item or raw text into procurement taxonomy levels."""
    try:
        filename = "item_classification.csv"
        csv_bytes = f"item_description\n{description}\n".encode("utf-8")
        classification = classify_upload(filename, csv_bytes)
        return {
            "success": True,
            "description": description,
            "classification": classification,
        }
    except Exception as e:
        return {
            "success": False,
            "description": description,
            "error": str(e),
            "classification": {},
        }


def compute_spend_metrics(timeframe: Optional[str] = "all") -> Dict[str, Any]:
    """Compute top-level KPI metrics (total spend, supplier counts, top categories, monthly trends)."""
    try:
        data = metrics.compute_metrics()
        return {
            "success": True,
            "timeframe": timeframe,
            "metrics": data,
        }
    except Exception as e:
        return {
            "success": False,
            "timeframe": timeframe,
            "error": str(e),
            "metrics": {},
        }


# ---------------------------------------------------------------------------
# Tool Registry & OpenAI Specification Helpers
# ---------------------------------------------------------------------------

TOOLS_REGISTRY = {
    "query_spend_database": {
        "name": "query_spend_database",
        "description": "Execute a SQL SELECT query against DuckDB read-only spend views (vw_spend, vw_supplier, vw_category, vw_contract).",
        "schema": ExecuteQueryInput,
        "func": execute_sql_query,
    },
    "search_contract_documents": {
        "name": "search_contract_documents",
        "description": "Search uploaded vendor contracts, policies, SLAs, and PDF attachments for legal or pricing terms.",
        "schema": SearchDocumentsInput,
        "func": search_contract_documents,
    },
    "detect_savings_opportunities": {
        "name": "detect_savings_opportunities",
        "description": "Run analytical heuristics to find cost reduction opportunities (supplier consolidation, tail spend, price variance).",
        "schema": DetectSavingsInput,
        "func": detect_savings_opportunities,
    },
    "get_database_schema": {
        "name": "get_database_schema",
        "description": "Retrieve DuckDB spend schema, available views, allowed columns, and SQL syntax guidance.",
        "schema": GetDatabaseSchemaInput,
        "func": get_database_schema,
    },
    "classify_spend_item": {
        "name": "classify_spend_item",
        "description": "Classify a line item description into standardized category levels.",
        "schema": ClassifySpendItemInput,
        "func": classify_spend_item,
    },
    "compute_spend_metrics": {
        "name": "compute_spend_metrics",
        "description": "Compute high-level executive spend metrics, supplier counts, and category breakdowns.",
        "schema": ComputeSpendMetricsInput,
        "func": compute_spend_metrics,
    },
}


def get_openai_tools_specs() -> List[Dict[str, Any]]:
    """Generate OpenAI function definitions for function calling."""
    specs = []
    for tool_name, tool_info in TOOLS_REGISTRY.items():
        schema_cls: type[BaseModel] = tool_info["schema"]
        json_schema = schema_cls.model_json_schema()
        specs.append({
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool_info["description"],
                "parameters": json_schema,
            },
        })
    return specs


def execute_tool_by_name(name: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a registered tool safely by name with argument dictionary."""
    if name not in TOOLS_REGISTRY:
        return {
            "success": False,
            "error": f"Tool '{name}' is not registered in TOOLS_REGISTRY.",
        }
    tool_info = TOOLS_REGISTRY[name]
    try:
        func = tool_info["func"]
        # Allow monkeypatching module-level functions in unit tests
        func_name = getattr(func, "__name__", None)
        if func_name and func_name in globals():
            func = globals()[func_name]
            
        validated_args = tool_info["schema"](**kwargs)
        return func(**validated_args.model_dump())
    except Exception as e:
        return {
            "success": False,
            "error": f"Tool argument validation or execution error for '{name}': {str(e)}",
        }


# Optional LangChain tool wrapper objects if langchain_core is installed
try:
    from langchain_core.tools import tool as lc_tool

    lc_query_spend_database = lc_tool(args_schema=ExecuteQueryInput)(execute_sql_query)
    lc_search_contract_documents = lc_tool(args_schema=SearchDocumentsInput)(search_contract_documents)
    lc_detect_savings_opportunities = lc_tool(args_schema=DetectSavingsInput)(detect_savings_opportunities)
    lc_get_database_schema = lc_tool(args_schema=GetDatabaseSchemaInput)(get_database_schema)
    lc_classify_spend_item = lc_tool(args_schema=ClassifySpendItemInput)(classify_spend_item)
    lc_compute_spend_metrics = lc_tool(args_schema=ComputeSpendMetricsInput)(compute_spend_metrics)

    LANGCHAIN_TOOLS = [
        lc_query_spend_database,
        lc_search_contract_documents,
        lc_detect_savings_opportunities,
        lc_get_database_schema,
        lc_classify_spend_item,
        lc_compute_spend_metrics,
    ]
except Exception:
    LANGCHAIN_TOOLS = []
