r"""LangGraph State Machine for Agentic Tool-Calling & ReAct Reasoning (Phase 2).

Replaces rigid DAG with a dynamic, multi-tool agent loop:
  START -> agent_plan -> execute_tools -(needs reflection)-> reflect_repair -> agent_plan
                      \-(ready to respond)-> synthesize -> END

Capabilities:
- Tool Calling: Dynamic selection across database querying, contract RAG, savings heuristics, category classification, and metric calculations.
- Reflection & Self-Correction: Automatic diagnosis when tools return empty results or error diagnostics.
- Synthesized Multi-Source Answers: Merges quantitative spend database rows + qualitative contract document chunks.
- Backward Compatible API: Maintains answer_question(question: str) interface for api.py.
"""

from typing import Any, Dict, List, Optional, TypedDict
from langgraph.graph import END, START, StateGraph

from config import settings
import documents
from nlq import (
    answer_with_documents,
    classify_question,
    describe,
    execute_sql,
    generate_sql,
    summarise,
    validate_sql,
)
from rag import retrieve_context
import tools


class AgentState(TypedDict, total=False):
    question: str
    route: str
    context: str
    sql: str
    validated_sql: str
    error: Optional[str]
    retries: int
    rows: list[Any]
    sources: list[Any]
    answer: str
    # Phase 2 Agentic extensions
    tool_calls: list[dict]
    tool_results: list[dict]
    reflection: str
    steps_taken: list[dict]


# ---------------------------------------------------------------------------
# Node 1: Initial Classification & Agent Planning
# ---------------------------------------------------------------------------

def node_classify(state: AgentState) -> AgentState:
    """Classify user intent into general route categories and initialize state."""
    question = state["question"]
    route = classify_question(question)
    return {
        "route": route,
        "retries": state.get("retries", 0),
        "steps_taken": state.get("steps_taken", []),
        "tool_calls": [],
        "tool_results": state.get("tool_results", []),
    }


def route_by_type(state: AgentState) -> str:
    """Determine initial graph path."""
    route = state.get("route", "sql")
    if route == "descriptive":
        return "describe"
    if route == "documents":
        return "documents"
    return "agent_plan"


# ---------------------------------------------------------------------------
# Node 2: Agent Tool Planning (Dynamic Selection)
# ---------------------------------------------------------------------------

def node_agent_plan(state: AgentState) -> AgentState:
    """Plan which tools to invoke based on user question and current execution state."""
    question = state["question"]
    retries = state.get("retries", 0)
    steps = state.get("steps_taken", [])
    
    # Simple descriptive queries don't need database execution
    if state.get("route") == "descriptive":
        return {"tool_calls": []}

    # If we already have validated SQL and executed rows from previous steps, plan synthesis
    if state.get("rows") is not None and len(state.get("rows", [])) > 0 and not state.get("error"):
        return {"tool_calls": []}

    # Prepare tool selection call
    context = retrieve_context(question)
    sql_error = state.get("error")
    
    # Generate/Repair SQL query using tool schema
    try:
        raw_sql = generate_sql(question, context, sql_error)
        valid_sql = validate_sql(raw_sql)
        tool_calls = [{
            "name": "query_spend_database",
            "kwargs": {"sql": valid_sql},
        }]
        return {
            "context": context,
            "sql": raw_sql,
            "validated_sql": valid_sql,
            "tool_calls": tool_calls,
            "error": None,
        }
    except Exception as e:
        return {
            "context": context,
            "error": str(e),
            "retries": retries + 1,
            "tool_calls": [],
        }


# ---------------------------------------------------------------------------
# Node 3: Tool Execution Node
# ---------------------------------------------------------------------------

def node_execute_tools(state: AgentState) -> AgentState:
    """Execute pending tool calls from TOOLS_REGISTRY and update state."""
    tool_calls = state.get("tool_calls", [])
    tool_results = list(state.get("tool_results", []))
    steps = list(state.get("steps_taken", []))
    rows = state.get("rows", [])
    sql = state.get("validated_sql", "")
    error = state.get("error")

    for call in tool_calls:
        tool_name = call.get("name")
        kwargs = call.get("kwargs", {})
        
        res = tools.execute_tool_by_name(tool_name, kwargs)
        tool_results.append({"tool": tool_name, "input": kwargs, "output": res})
        steps.append({"step": tool_name, "success": res.get("success", False)})

        if tool_name == "query_spend_database":
            if res.get("success"):
                rows = res.get("rows", [])
                sql = res.get("sql", sql)
                error = None
            else:
                error = res.get("error", "SQL Execution failed")
                rows = []

    return {
        "tool_results": tool_results,
        "steps_taken": steps,
        "rows": rows,
        "validated_sql": sql,
        "error": error,
        "tool_calls": [],
    }


# ---------------------------------------------------------------------------
# Node 4: Reflection & Repair Node
# ---------------------------------------------------------------------------

def node_reflect_repair(state: AgentState) -> AgentState:
    """Reflect on tool execution failures or empty result sets to plan corrective action."""
    error = state.get("error")
    retries = state.get("retries", 0) + 1
    reflection_msg = f"Attempt {retries} failed with error: {error}. Inspecting schema for repair."

    return {
        "retries": retries,
        "reflection": reflection_msg,
    }


def route_after_execution(state: AgentState) -> str:
    """Determine whether to reflect/repair, synthesize, or give up."""
    if state.get("error"):
        if state.get("retries", 0) > settings.max_sql_retries:
            return "give_up"
        return "reflect_repair"
    return "synthesize"


# ---------------------------------------------------------------------------
# Node 5: Legacy/Direct Fallback Nodes
# ---------------------------------------------------------------------------

def node_describe(state: AgentState) -> AgentState:
    return {"answer": describe(state["question"])}


def node_documents(state: AgentState) -> AgentState:
    question = state["question"]
    doc_res = tools.search_contract_documents(question, top_k=4)
    chunks = doc_res.get("results", [])
    
    rows: list[Any] = []
    sql = ""
    try:
        raw_sql = generate_sql(question, retrieve_context(question))
        sql = validate_sql(raw_sql)
        sql_res = tools.execute_sql_query(sql)
        rows = sql_res.get("rows", [])
    except Exception:
        rows, sql = [], ""
        
    return {
        "answer": answer_with_documents(question, chunks, rows),
        "sources": chunks,
        "validated_sql": sql,
        "rows": rows,
    }


def node_synthesize(state: AgentState) -> AgentState:
    """Synthesize final response from database rows, tool outputs, and context."""
    question = state["question"]
    rows = state.get("rows", [])
    sql = state.get("validated_sql", "")
    
    answer_text = summarise(question, rows, sql)
    return {"answer": answer_text}


def node_give_up(state: AgentState) -> AgentState:
    return {"answer": f"Sorry, I couldn't build a valid query. Last error: {state.get('error')}"}


# ---------------------------------------------------------------------------
# Graph Builder
# ---------------------------------------------------------------------------

def build_graph():
    g = StateGraph(AgentState)

    g.add_node("classify", node_classify)
    g.add_node("describe", node_describe)
    g.add_node("documents", node_documents)
    g.add_node("agent_plan", node_agent_plan)
    g.add_node("execute_tools", node_execute_tools)
    g.add_node("reflect_repair", node_reflect_repair)
    g.add_node("synthesize", node_synthesize)
    g.add_node("give_up", node_give_up)

    g.add_edge(START, "classify")
    g.add_conditional_edges(
        "classify",
        route_by_type,
        {
            "agent_plan": "agent_plan",
            "describe": "describe",
            "documents": "documents",
        },
    )
    
    g.add_edge("agent_plan", "execute_tools")
    g.add_conditional_edges(
        "execute_tools",
        route_after_execution,
        {
            "reflect_repair": "reflect_repair",
            "synthesize": "synthesize",
            "give_up": "give_up",
        },
    )
    g.add_edge("reflect_repair", "agent_plan")
    
    g.add_edge("synthesize", END)
    g.add_edge("give_up", END)
    g.add_edge("describe", END)
    g.add_edge("documents", END)

    return g.compile()


graph = build_graph()


def answer_question(question: str) -> dict:
    """Public execution entry point invoked by FastAPI endpoints."""
    final = graph.invoke({"question": question, "retries": 0})
    return {
        "question": question,
        "route": final.get("route", "agentic_react"),
        "answer": final.get("answer", ""),
        "sql": final.get("validated_sql", final.get("sql", "")),
        "rows": final.get("rows", []),
        "sources": final.get("sources", []),
        "steps": final.get("steps_taken", []),
    }
