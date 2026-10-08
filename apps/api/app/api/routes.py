from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import ApiKey, DbSession
from app.core.config import get_settings
from app.core.security import verify_github_signature
from app.schemas.analysis import (
    AnalysisCreate,
    AnalysisDetail,
    AnalysisSummary,
    HealthOut,
    ScenarioOut,
)
from app.services import analysis_service
from app.services.github_service import conclusion_from_risk, post_pr_comment
from app.services.redis_state import get_analysis_progress
from app.services.scenarios import list_scenarios

router = APIRouter()


@router.get("/health", response_model=HealthOut)
async def health():
    settings = get_settings()
    return HealthOut(
        status="ok",
        app=settings.app_name,
        agent_mode=settings.agent_mode,
        use_openai=settings.use_openai,
    )


@router.get("/scenarios", response_model=list[ScenarioOut])
async def scenarios(_: ApiKey):
    return list_scenarios()


@router.get("/analyses", response_model=list[AnalysisSummary])
async def list_analyses(session: DbSession, _: ApiKey):
    rows = await analysis_service.list_analyses(session)
    return rows


@router.post("/analyses", response_model=AnalysisDetail, status_code=status.HTTP_201_CREATED)
async def create_analysis(payload: AnalysisCreate, session: DbSession, _: ApiKey):
    try:
        analysis = await analysis_service.create_analysis(
            session,
            title=payload.title,
            migration_sql=payload.migration_sql,
            migration_filename=payload.migration_filename,
            source_type=payload.source_type,
            scenario_id=payload.scenario_id,
            repo_path=payload.repo_path,
            auto_analyze=payload.auto_analyze,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return analysis


@router.get("/analyses/{analysis_id}", response_model=AnalysisDetail)
async def get_analysis(analysis_id: UUID, session: DbSession, _: ApiKey):
    analysis = await analysis_service.get_analysis(session, analysis_id)
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    return analysis


@router.post("/analyses/{analysis_id}/rerun", response_model=AnalysisDetail)
async def rerun_analysis(analysis_id: UUID, session: DbSession, _: ApiKey):
    analysis = await analysis_service.get_analysis(session, analysis_id)
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    return await analysis_service.run_analysis(session, analysis_id)


@router.get("/analyses/{analysis_id}/report")
async def get_report(analysis_id: UUID, session: DbSession, _: ApiKey):
    analysis = await analysis_service.get_analysis(session, analysis_id)
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    return {
        "id": str(analysis.id),
        "markdown": analysis.markdown_report,
        "overall_risk": analysis.overall_risk,
        "overall_score": analysis.overall_score,
    }


@router.get("/analyses/{analysis_id}/progress")
async def progress(analysis_id: UUID, _: ApiKey):
    data = await get_analysis_progress(str(analysis_id))
    return data or {"stage": "unknown", "pct": 0}


@router.post("/webhooks/github")
async def github_webhook(request: Request, session: DbSession):
    """PR webhook → analyze migration files → optional PR comment."""
    body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256")
    if not verify_github_signature(body, sig):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    payload = await request.json()
    action = payload.get("action")
    pr = payload.get("pull_request") or {}
    repo = payload.get("repository") or {}

    if action not in {"opened", "synchronize", "reopened"} or not pr:
        return {"ok": True, "skipped": True, "reason": "irrelevant_event"}

    # Without fetching PR files via GitHub API, accept optional inline migration in payload (demo)
    migration_sql = (payload.get("migration_sql") or "").strip()
    title = f"PR #{pr.get('number')}: {pr.get('title') or 'migration check'}"

    if not migration_sql:
        return {
            "ok": True,
            "skipped": True,
            "reason": "no_migration_sql_in_payload",
            "hint": "For local demos, include migration_sql in the webhook JSON body.",
        }

    analysis = await analysis_service.create_analysis(
        session,
        title=title,
        migration_sql=migration_sql,
        source_type=payload.get("source_type") or "sql",
        migration_filename=payload.get("migration_filename"),
        auto_analyze=True,
    )

    settings = get_settings()
    github_meta = {
        "repo": repo.get("full_name"),
        "pr_number": pr.get("number"),
        "conclusion": conclusion_from_risk(analysis.overall_risk or "low"),
        "check_name": settings.github_check_name,
    }

    comment = None
    if settings.github_token and repo.get("full_name") and pr.get("number"):
        body_md = analysis.markdown_report or analysis.llm_explanation or "SchemaSentinel analysis complete."
        # Keep comment reasonably sized
        if len(body_md) > 60000:
            body_md = body_md[:60000] + "\n\n_(truncated)_"
        comment = await post_pr_comment(
            repo_full_name=repo["full_name"],
            pr_number=int(pr["number"]),
            body=body_md,
        )
        github_meta["comment"] = comment

    analysis.github_meta = github_meta
    await session.commit()
    await session.refresh(analysis)

    return {
        "ok": True,
        "analysis_id": str(analysis.id),
        "overall_risk": analysis.overall_risk,
        "conclusion": github_meta["conclusion"],
        "github": github_meta,
    }
