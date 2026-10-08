"""LangGraph LLM reasoner over deterministic risk findings (OpenAI when configured)."""

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
    stats = state.get("stats_meta") or {}
    stats_note = (
        f"Table stats source: **{stats.get('source', 'unknown')}**"
        + (f" (`{stats.get('url_host')}`)" if stats.get("url_host") else "")
        + "."
    )
    return (
        f"### Reviewer briefing\n\n"
        f"Overall risk is **{state.get('overall_risk')}** "
        f"(score `{state.get('overall_score')}`).\n\n"
        f"{stats_note}\n\n"
        f"{ref_note}\n\n"
        f"#### Top findings\n{bullets or '- None'}\n\n"
        f"#### Guidance\n"
        f"Prefer an **expand → backfill → switch → contract** rollout. "
        f"Do not treat generated rollback SQL as a guarantee — "
        f"irreversible drops and type narrowings need backups or shadow columns.\n"
    )


def _openai_explanation(state: ReasonerState) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0.2,
        timeout=60,
        max_retries=2,
    )

    ops_summary = ", ".join(
        f"{o.get('op_type')}({o.get('table')}.{o.get('column')})"
        for o in (state.get("operations") or [])[:12]
    )
    findings_summary = "\n".join(
        f"- [{f.get('severity')}] {f.get('rule_id')}: {f.get('message')}"
        for f in (state.get("findings") or [])[:8]
    )
    refs = state.get("code_references") or []
    ref_summary = "\n".join(
        f"- `{r.get('path')}:{r.get('line')}` ({r.get('symbol')})" for r in refs[:8]
    )
    stats = state.get("stats_meta") or {}

    prompt = (
        f"Migration: {state.get('title')}\n"
        f"Overall risk: {state.get('overall_risk')} ({state.get('overall_score')})\n"
        f"Table stats: source={stats.get('source')} host={stats.get('url_host')}\n"
        f"Operations: {ops_summary}\n"
        f"Findings:\n{findings_summary}\n"
        f"Code refs ({len(refs)}):\n{ref_summary or '- none'}\n\n"
        "Write a concise PR review comment (markdown) covering: blast radius, "
        "why rules fired, expand/backfill/switch/contract advice, and what is NOT safely reversible. "
        "Do not invent tables that were not provided. Be skeptical of perfect rollbacks. "
        "Never change or contradict the deterministic overall risk score."
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
    stats_meta: dict[str, Any] | None = None,
    force_mock: bool = False,
) -> dict[str, Any]:
    """Run OpenAI reasoner when configured; otherwise deterministic mock briefing."""
    settings = get_settings()
    state: ReasonerState = {
        "title": title,
        "operations": operations,
        "findings": findings,
        "code_references": code_references,
        "overall_risk": overall_risk,
        "overall_score": overall_score,
        "stats_meta": stats_meta or {},
        "trace": [],
    }

    use_openai = (not force_mock) and settings.use_openai
    trace: list[dict[str, Any]] = [
        {"step": "ingest", "detail": f"{len(operations)} ops, {len(findings)} findings"},
        {
            "step": "mode",
            "detail": "openai" if use_openai else "mock",
            "agent_mode": settings.agent_mode,
            "has_api_key": bool(settings.openai_api_key),
        },
        {
            "step": "stats",
            "detail": (stats_meta or {}).get("source"),
            "host": (stats_meta or {}).get("url_host"),
        },
    ]

    try:
        if use_openai:
            explanation = _openai_explanation(state)
            trace.append({"step": "llm_reasoner", "detail": "openai_completed"})
        else:
            explanation = _mock_explanation(state)
            trace.append({"step": "llm_reasoner", "detail": "mock_completed"})
    except Exception as exc:
        logger.warning("reasoner_fallback", error=str(exc))
        explanation = _mock_explanation(state)
        trace.append({"step": "llm_reasoner", "detail": f"fallback_mock:{exc}"})

    try:
        from langgraph.graph import END, StateGraph

        def node_summarize(s: ReasonerState) -> ReasonerState:
            out = dict(s)
            out["explanation"] = explanation
            return out  # type: ignore[return-value]

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
