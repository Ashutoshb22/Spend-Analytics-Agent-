"""Phase 3: Multi-Agent Orchestration & Proactive Intelligence Sub-Agents.

Defines specialized autonomous sub-agents coordinated by a Supervisor Agent,
along with an autonomous proactive background spend auditing engine.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

import db
import documents
import metrics
import nlq
import savings
import tools


# ---------------------------------------------------------------------------
# Data Models for Multi-Agent Task Delegation
# ---------------------------------------------------------------------------

class AgentTask(BaseModel):
    task_id: str
    target_agent: str
    description: str
    context: Dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    task_id: str
    agent_name: str
    status: str
    summary: str
    data: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Sub-Agent 1: Ingestion & Data Quality Agent
# ---------------------------------------------------------------------------

class IngestionDataQualityAgent:
    """Specialized agent for spend data quality, schema audit, and line-item categorization."""

    name: str = "IngestionDataQualityAgent"

    def run_data_quality_audit(self) -> Dict[str, Any]:
        """Audit the spend database for unmapped categories, missing suppliers, or null line items."""
        sql = """
            SELECT 
                COUNT(*) AS total_rows,
                COUNT(CASE WHEN category_level2 IS NULL OR category_level2 = '' THEN 1 END) AS unmapped_categories,
                COUNT(CASE WHEN item IS NULL OR item = '' THEN 1 END) AS unitemised_rows,
                COUNT(CASE WHEN supplier_name IS NULL OR supplier_name = '' THEN 1 END) AS missing_suppliers
            FROM vw_spend;
        """
        res = tools.execute_sql_query(sql)
        audit_data = res.get("rows", [{}])[0] if res.get("success") and res.get("rows") else {}
        
        score = 100.0
        total = audit_data.get("total_rows", 1) or 1
        unmapped = audit_data.get("unmapped_categories", 0) or 0
        unitemised = audit_data.get("unitemised_rows", 0) or 0
        
        score -= (unmapped / total) * 40.0
        score -= (unitemised / total) * 20.0
        data_quality_score = max(0.0, round(score, 1))

        return {
            "agent": self.name,
            "data_quality_score": data_quality_score,
            "total_records": total,
            "unmapped_categories": unmapped,
            "unitemised_records": unitemised,
            "missing_suppliers": audit_data.get("missing_suppliers", 0),
            "recommendation": (
                "Run auto-classification on unmapped line items."
                if unmapped > 0 else "Data quality is optimal."
            ),
        }


# ---------------------------------------------------------------------------
# Sub-Agent 2: Procurement & Compliance RAG Agent
# ---------------------------------------------------------------------------

class ProcurementComplianceAgent:
    """Specialized agent for cross-referencing actual spend against PDF contract terms and policies."""

    name: str = "ProcurementComplianceAgent"

    def verify_vendor_compliance(self, vendor_name: str) -> Dict[str, Any]:
        """Cross-reference actual vendor spend against PDF contract terms and detect overpayments."""
        # 1. Search contract documents
        doc_res = tools.search_contract_documents(f"{vendor_name} contract pricing terms SLA", top_k=3)
        contract_chunks = doc_res.get("results", [])

        # 2. Query DuckDB for off-contract / maverick transactions for this vendor
        sql = f"""
            SELECT 
                supplier_name,
                SUM(amount) AS total_spend,
                SUM(CASE WHEN is_maverick = true THEN amount ELSE 0 END) AS maverick_spend,
                COUNT(DISTINCT contract_id) AS active_contracts
            FROM vw_spend
            WHERE supplier_name ILIKE '%{vendor_name}%'
            GROUP BY supplier_name;
        """
        db_res = tools.execute_sql_query(sql)
        vendor_data = db_res.get("rows", [{}])[0] if db_res.get("success") and db_res.get("rows") else {}

        maverick_spend = float(vendor_data.get("maverick_spend", 0) or 0)
        total_spend = float(vendor_data.get("total_spend", 0) or 0)
        maverick_pct = round((maverick_spend / total_spend * 100), 1) if total_spend > 0 else 0.0

        return {
            "agent": self.name,
            "vendor_name": vendor_name,
            "total_spend": total_spend,
            "maverick_spend": maverick_spend,
            "maverick_percentage": maverick_pct,
            "contract_references": contract_chunks,
            "compliance_status": "NON_COMPLIANT" if maverick_pct > 15.0 else "COMPLIANT",
        }


# ---------------------------------------------------------------------------
# Sub-Agent 3: Savings & Negotiation Agent
# ---------------------------------------------------------------------------

class SavingsNegotiationAgent:
    """Specialized agent for tail-spend consolidation and supplier negotiation strategy."""

    name: str = "SavingsNegotiationAgent"

    def generate_negotiation_playbook(self, category: Optional[str] = None) -> Dict[str, Any]:
        """Generate structured supplier negotiation strategies and target savings."""
        opps_res = tools.detect_savings_opportunities(kind="consolidation")
        opps = opps_res.get("opportunities", [])
        
        if category:
            opps = [o for o in opps if o.get("category", "").lower() == category.lower()]

        total_target_savings = sum(float(o.get("target_annual", 0) or 0) for o in opps)
        
        strategies = []
        for o in opps[:5]:
            strategies.append({
                "opportunity_title": o.get("title"),
                "category": o.get("category"),
                "supplier": o.get("supplier"),
                "target_annual_savings": o.get("target_annual"),
                "recommended_action": (
                    f"Consolidate spend with primary supplier in {o.get('category')} "
                    f"to capture estimated ${o.get('target_annual', 0):,.2f} annual savings."
                ),
            })

        return {
            "agent": self.name,
            "category_filter": category or "All Categories",
            "total_target_savings": total_target_savings,
            "opportunity_count": len(opps),
            "negotiation_strategies": strategies,
        }


# ---------------------------------------------------------------------------
# Supervisor Agent (Orchestrator)
# ---------------------------------------------------------------------------

class SupervisorAgent:
    """Orchestrates specialized sub-agents and synthesizes unified multi-agent insights."""

    def __init__(self):
        self.data_agent = IngestionDataQualityAgent()
        self.compliance_agent = ProcurementComplianceAgent()
        self.savings_agent = SavingsNegotiationAgent()

    def process_multi_agent_request(self, question: str, vendor: Optional[str] = None) -> Dict[str, Any]:
        """Orchestrate sub-agents based on multi-domain question scope."""
        results: List[AgentResult] = []

        # 1. Run Data Quality Audit
        dq_data = self.data_agent.run_data_quality_audit()
        results.append(AgentResult(
            task_id="task_data_audit",
            agent_name=self.data_agent.name,
            status="SUCCESS",
            summary=f"Data Quality Score: {dq_data['data_quality_score']}/100",
            data=dq_data,
        ))

        # 2. Run Vendor Compliance Analysis if vendor specified or detected
        target_vendor = vendor or ("DHL" if "dhl" in question.lower() else None)
        compliance_data = {}
        if target_vendor:
            compliance_data = self.compliance_agent.verify_vendor_compliance(target_vendor)
            results.append(AgentResult(
                task_id="task_compliance",
                agent_name=self.compliance_agent.name,
                status="SUCCESS",
                summary=f"Compliance for {target_vendor}: {compliance_data['compliance_status']}",
                data=compliance_data,
            ))

        # 3. Run Savings Strategy
        savings_data = self.savings_agent.generate_negotiation_playbook()
        results.append(AgentResult(
            task_id="task_savings",
            agent_name=self.savings_agent.name,
            status="SUCCESS",
            summary=f"Target Savings Opportunities: ${savings_data['total_target_savings']:,.2f}",
            data=savings_data,
        ))

        # 4. Synthesize Executive Report
        executive_summary = (
            f"Multi-Agent Audit Completed: Data Quality Score is {dq_data['data_quality_score']}/100. "
            f"Identified ${savings_data['total_target_savings']:,.2f} in potential savings across "
            f"{savings_data['opportunity_count']} consolidation targets."
        )
        if compliance_data:
            executive_summary += f" Vendor '{target_vendor}' status is {compliance_data.get('compliance_status')}."

        return {
            "question": question,
            "executive_summary": executive_summary,
            "sub_agent_results": [r.model_dump() for r in results],
        }


# ---------------------------------------------------------------------------
# Autonomous Proactive Spend Audit Engine
# ---------------------------------------------------------------------------

def run_proactive_spend_audit() -> Dict[str, Any]:
    """Autonomous background spend audit engine.
    
    Scans DuckDB ledger for price variances, off-contract spend spikes, and tail fragmentation.
    """
    findings = []

    # Finding 1: Off-contract maverick spend by category
    sql_maverick = """
        SELECT 
            category_level2 AS category,
            SUM(amount) AS maverick_amount,
            COUNT(*) AS transaction_count
        FROM vw_spend
        WHERE is_maverick = true
        GROUP BY category_level2
        ORDER BY maverick_amount DESC
        LIMIT 3;
    """
    res_mav = tools.execute_sql_query(sql_maverick)
    if res_mav.get("success") and res_mav.get("rows"):
        for row in res_mav["rows"]:
            cat = row.get("category") or "Unknown"
            amt = float(row.get("maverick_amount") or 0)
            if amt > 5000:
                findings.append({
                    "severity": "HIGH",
                    "type": "MAVERICK_SPEND_SPIKE",
                    "title": f"High Off-Contract Spend in {cat}",
                    "description": f"${amt:,.2f} spent off-contract across {row.get('transaction_count')} transactions.",
                    "recommended_action": f"Establish mandatory purchasing policy and preferred suppliers for {cat}.",
                })

    # Finding 2: Supplier fragmentation in category
    sql_frag = """
        SELECT 
            category_level2 AS category,
            COUNT(DISTINCT supplier_name) AS supplier_count,
            SUM(amount) AS total_spend
        FROM vw_spend
        GROUP BY category_level2
        HAVING COUNT(DISTINCT supplier_name) >= 3
        ORDER BY supplier_count DESC
        LIMIT 3;
    """
    res_frag = tools.execute_sql_query(sql_frag)
    if res_frag.get("success") and res_frag.get("rows"):
        for row in res_frag["rows"]:
            cat = row.get("category") or "Unknown"
            supp_cnt = row.get("supplier_count")
            amt = float(row.get("total_spend") or 0)
            findings.append({
                "severity": "MEDIUM",
                "type": "SUPPLIER_FRAGMENTATION",
                "title": f"Supplier Fragmentation in {cat}",
                "description": f"Category {cat} is fragmented across {supp_cnt} suppliers totaling ${amt:,.2f}.",
                "recommended_action": f"Issue RFP to consolidate {cat} spend to 1-2 primary vendors.",
            })

    return {
        "audit_status": "COMPLETED",
        "total_findings": len(findings),
        "findings": findings,
    }
