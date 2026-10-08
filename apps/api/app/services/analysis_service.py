"""Orchestrate parse → live stats → graph → rules → code search → reasoner → report."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.workflow import run_reasoner
from app.core.logging import get_logger
from app.models.analysis import Analysis, AnalysisStatus, AuditLog
from app.services.code_search import search_references
from app.services.db_stats import resolve_table_stats
from app.services.dependency_graph import build_dependency_graph
from app.services.parser import parse_migration
from app.services.redis_state import set_analysis_progress
from app.services.report import render_markdown_report
from app.services.risk_engine import score_operations
from app.services.rollout import build_rollout_plan, generate_rollback_sql
from app.services.parser import detect_source_type
from app.services.samples import load_sample_migration
from app.services.scenarios import (
    default_repo_path,
    default_table_stats,
    get_scenario,
    load_scenario_sql,
)

logger = get_logger("analysis_service")


async def audit(
    session: AsyncSession,
    action: str,
    analysis_id: UUID | None = None,
    detail: dict | None = None,
) -> None:
    session.add(AuditLog(analysis_id=analysis_id, action=action, detail=detail or {}))


async def create_analysis(
    session: AsyncSession,
    *,
    title: str | None = None,
    migration_sql: str | None = None,
    migration_filename: str | None = None,
    source_type: str = "auto",
    scenario_id: str | None = None,
    sample_filename: str | None = None,
    repo_path: str | None = None,
    auto_analyze: bool = True,
    github_meta: dict[str, Any] | None = None,
) -> Analysis:
    if scenario_id:
        content, scenario = load_scenario_sql(scenario_id)
        migration_sql = content
        migration_filename = scenario["filename"]
        source_type = scenario["source_type"]
        title = title or scenario["title"]
        if not repo_path:
            repo_path = str(default_repo_path())
    elif sample_filename:
        sample = load_sample_migration(sample_filename)
        migration_sql = sample["migration_sql"]
        migration_filename = sample["filename"]
        source_type = sample["source_type"]
        title = title or sample["filename"]
        if not repo_path:
            repo_path = str(default_repo_path())
    elif not migration_sql:
        raise ValueError("Provide migration_sql, sample_filename, or scenario_id")

    if source_type in {"auto", ""}:
        source_type = detect_source_type(
            migration_sql or "", filename=migration_filename, hint=None
        )

    if not repo_path:
        repo_path = str(default_repo_path())

    analysis = Analysis(
        title=title or migration_filename or "Untitled migration analysis",
        source_type=source_type,
        scenario_id=scenario_id,
        status=AnalysisStatus.pending.value,
        migration_sql=migration_sql or "",
        migration_filename=migration_filename,
        repo_path=repo_path,
        github_meta=github_meta,
    )
    session.add(analysis)
    await session.flush()
    await audit(session, "analysis.created", analysis.id, {"scenario_id": scenario_id})
    await session.commit()
    await session.refresh(analysis)

    if auto_analyze:
        analysis = await run_analysis(session, analysis.id)

    return analysis


async def get_analysis(session: AsyncSession, analysis_id: UUID) -> Analysis | None:
    return await session.get(Analysis, analysis_id)


async def list_analyses(session: AsyncSession, limit: int = 50) -> list[Analysis]:
    result = await session.execute(
        select(Analysis).order_by(Analysis.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def run_analysis(session: AsyncSession, analysis_id: UUID) -> Analysis:
    analysis = await session.get(Analysis, analysis_id)
    if not analysis:
        raise KeyError(f"Analysis {analysis_id} not found")

    analysis.status = AnalysisStatus.running.value
    analysis.error_message = None
    await session.commit()
    await set_analysis_progress(str(analysis_id), {"stage": "parse", "pct": 10})

    try:
        operations = parse_migration(
            analysis.migration_sql,
            source_type=analysis.source_type,
            filename=analysis.migration_filename,
        )
        await set_analysis_progress(str(analysis_id), {"stage": "db_stats", "pct": 25})

        stats_payload = resolve_table_stats()
        table_rows = stats_payload.get("rows") or default_table_stats()

        await set_analysis_progress(str(analysis_id), {"stage": "risk_rules", "pct": 40})
        scored = score_operations(operations, table_rows)
        findings = scored["findings"]
        overall_risk = scored["overall_risk"]
        overall_score = scored["overall_score"]

        await set_analysis_progress(str(analysis_id), {"stage": "code_search", "pct": 55})
        repo = analysis.repo_path or str(default_repo_path())
        code_refs = search_references(operations, repo)

        await set_analysis_progress(str(analysis_id), {"stage": "graph", "pct": 70})
        graph = build_dependency_graph(operations, code_refs)
        rollout = build_rollout_plan(operations, findings)
        rollback = generate_rollback_sql(operations)

        await set_analysis_progress(str(analysis_id), {"stage": "reasoner", "pct": 85})
        reasoner = run_reasoner(
            title=analysis.title,
            operations=operations,
            findings=findings,
            code_references=code_refs,
            overall_risk=overall_risk,
            overall_score=overall_score,
            stats_meta={
                "source": stats_payload.get("source"),
                "url_host": stats_payload.get("url_host"),
                "table_count": len(stats_payload.get("details") or []),
                "error": stats_payload.get("error"),
            },
        )

        report = render_markdown_report(
            title=analysis.title,
            overall_risk=overall_risk,
            overall_score=overall_score,
            operations=operations,
            findings=findings,
            dependency_graph=graph,
            code_references=code_refs,
            rollout_plan=rollout,
            rollback_sql=rollback,
            llm_explanation=reasoner["explanation"],
            stats_meta={
                "source": stats_payload.get("source"),
                "url_host": stats_payload.get("url_host"),
            },
        )

        # Attach stats provenance onto dependency graph for the UI
        graph = {**graph, "stats_source": stats_payload.get("source"), "stats_host": stats_payload.get("url_host")}

        analysis.operations = operations
        analysis.risk_findings = findings
        analysis.dependency_graph = graph
        analysis.code_references = code_refs
        analysis.rollout_plan = rollout
        analysis.rollback_sql = rollback
        analysis.llm_explanation = reasoner["explanation"]
        analysis.markdown_report = report
        analysis.agent_trace = reasoner["trace"]
        analysis.overall_risk = overall_risk
        analysis.overall_score = overall_score
        analysis.status = AnalysisStatus.completed.value
        analysis.completed_at = datetime.now(timezone.utc)

        await audit(
            session,
            "analysis.completed",
            analysis.id,
            {
                "overall_risk": overall_risk,
                "findings": len(findings),
                "stats_source": stats_payload.get("source"),
            },
        )
        await session.commit()
        await session.refresh(analysis)
        await set_analysis_progress(str(analysis_id), {"stage": "done", "pct": 100})
        logger.info(
            "analysis_completed",
            id=str(analysis_id),
            risk=overall_risk,
            stats_source=stats_payload.get("source"),
            llm=reasoner["trace"],
        )
        return analysis

    except Exception as exc:
        logger.exception("analysis_failed", id=str(analysis_id))
        analysis.status = AnalysisStatus.failed.value
        analysis.error_message = str(exc)
        await audit(session, "analysis.failed", analysis.id, {"error": str(exc)})
        await session.commit()
        await session.refresh(analysis)
        await set_analysis_progress(
            str(analysis_id), {"stage": "failed", "pct": 100, "error": str(exc)}
        )
        return analysis


def analyze_sync(
    migration_sql: str,
    *,
    source_type: str = "sql",
    filename: str | None = None,
    repo_path: str | None = None,
    title: str = "sync-analysis",
    use_live_stats: bool = False,
) -> dict[str, Any]:
    """Pure sync pipeline for tests/evals (no app DB writes)."""
    operations = parse_migration(migration_sql, source_type=source_type, filename=filename)
    if use_live_stats:
        stats_payload = resolve_table_stats()
        table_rows = stats_payload.get("rows") or default_table_stats()
    else:
        # Deterministic evals/CI — avoid network dependency
        stats_payload = {"source": "synthetic", "url_host": None, "error": None}
        table_rows = default_table_stats()

    scored = score_operations(operations, table_rows)
    code_refs = search_references(operations, repo_path or default_repo_path())
    graph = build_dependency_graph(operations, code_refs)
    rollout = build_rollout_plan(operations, scored["findings"])
    rollback = generate_rollback_sql(operations)
    reasoner = run_reasoner(
        title=title,
        operations=operations,
        findings=scored["findings"],
        code_references=code_refs,
        overall_risk=scored["overall_risk"],
        overall_score=scored["overall_score"],
        stats_meta={
            "source": stats_payload.get("source"),
            "url_host": stats_payload.get("url_host"),
        },
        force_mock=not use_live_stats,
    )
    report = render_markdown_report(
        title=title,
        overall_risk=scored["overall_risk"],
        overall_score=scored["overall_score"],
        operations=operations,
        findings=scored["findings"],
        dependency_graph=graph,
        code_references=code_refs,
        rollout_plan=rollout,
        rollback_sql=rollback,
        llm_explanation=reasoner["explanation"],
        stats_meta={
            "source": stats_payload.get("source"),
            "url_host": stats_payload.get("url_host"),
        },
    )
    return {
        "operations": operations,
        "findings": scored["findings"],
        "overall_risk": scored["overall_risk"],
        "overall_score": scored["overall_score"],
        "dependency_graph": graph,
        "code_references": code_refs,
        "rollout_plan": rollout,
        "rollback_sql": rollback,
        "llm_explanation": reasoner["explanation"],
        "agent_trace": reasoner["trace"],
        "markdown_report": report,
        "stats": stats_payload,
        "scenario": get_scenario(title) if False else None,
    }
