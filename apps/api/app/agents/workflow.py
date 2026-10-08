"""LangGraph LLM reasoner over deterministic risk findings (with mock fallback)."""

from __future__ import annotations

from typing import Any

from app.agents.state import ReasonerState
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("agents.workflow")


def _mock_explanation(state: ReasonerState) -> str:
    findings = state.get("findings") or []
    top = findings[:3]
    bullets = "\n".join(
        f"- **{f.get('title')}** ({f.get('severity')}): {f.get('message')}" for f in top
    )
    refs = state.get("code_references") or []
    ref_note = (
        f"Found **{len(refs)}** application reference(s) that may break if this ships as-is."
        if refs
        else "No application references were indexed for this run."
    )
    return (
        f"### Reviewer briefing\n\n"
        f"Overall risk is **{state.get('overall_risk')}** "
        f"(score `{state.get('overall_score')}`).\n\n"
        f"{ref_note}\n\n"
        f"#### Top findings\n{bullets or '- None'}\n\n"
        f"#### Guidance\n"
        f"Prefer an **expand → backfill → switch → contract** rollout. "
        f"Do not treat generated rollback SQL as a guarantee — "
        f"irreversible drops and type narrowings need backups or shadow columns.\n"
    )


def _openai_explanation(state: ReasonerState) -> str:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage

    settings = get_settings()
    llm = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key, temperature=0.2)

    ops_summary = ", ".join(
        f"{o.get('op_type')}({o.get('table')}.{o.get('column')})" for o in (state.get("operations") or [])[:12]
    )
    findings_summary = "\n".join(
        f"- [{f.get('severity')}] {f.get('rule_id')}: {f.get('message')}"
        for f in (state.get("findings") or [])[:8]
    )
    prompt = (
        f"Migration: {state.get('title')}\n"
        f"Overall risk: {state.get('overall_risk')} ({state.get('overall_score')})\n"
        f"Operations: {ops_summary}\n"
        f"Findings:\n{findings_summary}\n"
        f"Code refs: {len(state.get('code_references') or [])}\n\n"
        "Write a concise PR review comment (markdown) covering: blast radius, "
        "why rules fired, expand/backfill/switch/contract advice, and what is NOT safely reversible. "
        "Do not invent tables that were not provided. Be skeptical of perfect rollbacks."
    )
    messages = [
        SystemMessage(
            content=(
                "You are SchemaSentinel, a database migration risk analyst. "
                "You explain deterministic rule output; you never override rule severities."
            )
        ),
        HumanMessage(content=prompt),
    ]
    result = llm.invoke(messages)
    return str(result.content)


def run_reasoner(
    *,
    title: str,
    operations: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    code_references: list[dict[str, Any]],
    overall_risk: str,
    overall_score: float,
) -> dict[str, Any]:
    """Run LLM or mock reasoner. Returns explanation + trace."""
    settings = get_settings()
    state: ReasonerState = {
        "title": title,
        "operations": operations,
        "findings": findings,
        "code_references": code_references,
        "overall_risk": overall_risk,
        "overall_score": overall_score,
        "trace": [],
    }

    trace: list[dict[str, Any]] = [
        {"step": "ingest", "detail": f"{len(operations)} ops, {len(findings)} findings"},
        {"step": "mode", "detail": "openai" if settings.use_openai else "mock"},
    ]

    try:
        if settings.use_openai:
            explanation = _openai_explanation(state)
            trace.append({"step": "llm_reasoner", "detail": "openai_completed"})
        else:
            explanation = _mock_explanation(state)
            trace.append({"step": "llm_reasoner", "detail": "mock_completed"})
    except Exception as exc:
        logger.warning("reasoner_fallback", error=str(exc))
        explanation = _mock_explanation(state)
        trace.append({"step": "llm_reasoner", "detail": f"fallback_mock:{exc}"})

    # Lightweight LangGraph-shaped pipeline for portfolio signal
    try:
        from langgraph.graph import END, StateGraph

        def node_summarize(s: ReasonerState) -> ReasonerState:
            s = dict(s)
            s["explanation"] = explanation
            return s  # type: ignore[return-value]

        graph = StateGraph(ReasonerState)
        graph.add_node("summarize", node_summarize)
        graph.set_entry_point("summarize")
        graph.add_edge("summarize", END)
        app = graph.compile()
        final = app.invoke({**state, "explanation": explanation})
        explanation = final.get("explanation") or explanation
        trace.append({"step": "langgraph", "detail": "summarize→end"})
    except Exception as exc:
        trace.append({"step": "langgraph", "detail": f"skipped:{exc}"})

    return {"explanation": explanation, "trace": trace}
