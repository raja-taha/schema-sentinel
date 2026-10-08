from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

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
from app.services.db_stats import resolve_table_stats
from app.services.github_service import (
    collect_pr_migrations,
    conclusion_from_risk,
    create_check_run,
    post_pr_comment,
)
from app.services.parser import detect_source_type
from app.services.redis_state import get_analysis_progress
from app.services.samples import list_sample_migrations, load_sample_migration
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


@router.get("/stats")
async def table_stats(_: ApiKey):
    """Live (or synthetic) table size metadata used for lock-risk scoring."""
    return resolve_table_stats()


@router.get("/scenarios", response_model=list[ScenarioOut])
async def scenarios(_: ApiKey):
    """Curated eval scenarios (kept for evals/CI). Prefer /samples for browsing."""
    return list_scenarios()


@router.get("/samples")
async def samples(_: ApiKey):
    """All migration files under samples/migrations (dynamically discovered)."""
    return list_sample_migrations()


@router.get("/samples/{filename}")
async def sample_detail(filename: str, _: ApiKey):
    try:
        return load_sample_migration(filename)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


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
            sample_filename=payload.sample_filename,
            repo_path=payload.repo_path,
            auto_analyze=payload.auto_analyze,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return analysis


@router.post("/analyses/upload", response_model=AnalysisDetail, status_code=status.HTTP_201_CREATED)
async def upload_migration(
    session: DbSession,
    _: ApiKey,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    auto_analyze: bool = Form(default=True),
):
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be UTF-8 text (SQL / Alembic / Django / Prisma)",
        ) from exc
    if not content.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")

    filename = file.filename or "upload.sql"
    source_type = detect_source_type(content, filename=filename)
    analysis = await analysis_service.create_analysis(
        session,
        title=title or filename,
        migration_sql=content,
        migration_filename=filename,
        source_type=source_type,
        auto_analyze=auto_analyze,
    )
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
    """PR webhook → fetch migration files from GitHub → analyze → comment/check."""
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

    repo_full_name = repo.get("full_name")
    pr_number = pr.get("number")
    head = pr.get("head") or {}
    head_sha = head.get("sha")
    title = f"PR #{pr_number}: {pr.get('title') or 'migration check'}"

    # Allow inline SQL for local demos; otherwise fetch real PR files
    migration_sql = (payload.get("migration_sql") or "").strip()
    source_type = payload.get("source_type") or "sql"
    migration_filename = payload.get("migration_filename")
    fetched: dict = {}

    if not migration_sql and repo_full_name and pr_number:
        fetched = await collect_pr_migrations(
            repo_full_name=repo_full_name,
            pr_number=int(pr_number),
            head_sha=head_sha,
        )
        migration_sql = fetched.get("migration_sql") or ""
        source_type = fetched.get("source_type") or source_type
        filenames = fetched.get("filenames") or []
        migration_filename = filenames[0] if filenames else migration_filename

    if not migration_sql:
        return {
            "ok": True,
            "skipped": True,
            "reason": "no_migration_files",
            "hint": (
                "Set GITHUB_TOKEN so SchemaSentinel can list PR files, "
                "or include migration_sql in the webhook body for local demos."
            ),
            "pr_file_count": fetched.get("pr_file_count", 0),
        }

    analysis = await analysis_service.create_analysis(
        session,
        title=title,
        migration_sql=migration_sql,
        source_type=source_type,
        migration_filename=migration_filename,
        auto_analyze=True,
        github_meta={
            "repo": repo_full_name,
            "pr_number": pr_number,
            "head_sha": head_sha,
            "files": fetched.get("files") or [],
        },
    )

    settings = get_settings()
    conclusion = conclusion_from_risk(analysis.overall_risk or "low")
    github_meta = {
        "repo": repo_full_name,
        "pr_number": pr_number,
        "head_sha": head_sha,
        "conclusion": conclusion,
        "check_name": settings.github_check_name,
        "files": fetched.get("files") or [],
    }

    body_md = (
        analysis.markdown_report
        or analysis.llm_explanation
        or "SchemaSentinel analysis complete."
    )
    if len(body_md) > 60000:
        body_md = body_md[:60000] + "\n\n_(truncated)_"

    if settings.github_token and repo_full_name and pr_number:
        github_meta["comment"] = await post_pr_comment(
            repo_full_name=repo_full_name,
            pr_number=int(pr_number),
            body=body_md,
        )
        if head_sha:
            github_meta["check_run"] = await create_check_run(
                repo_full_name=repo_full_name,
                head_sha=head_sha,
                conclusion=conclusion,
                title=f"Risk: {analysis.overall_risk} ({analysis.overall_score})",
                summary=body_md[:65000],
            )

    analysis.github_meta = github_meta
    await session.commit()
    await session.refresh(analysis)

    return {
        "ok": True,
        "analysis_id": str(analysis.id),
        "overall_risk": analysis.overall_risk,
        "conclusion": conclusion,
        "files_analyzed": fetched.get("filenames") or ([migration_filename] if migration_filename else []),
        "github": github_meta,
    }
