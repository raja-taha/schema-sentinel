from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AnalysisCreate(BaseModel):
    title: str | None = None
    migration_sql: str | None = Field(
        default=None, description="Raw SQL / Alembic / Prisma / Django migration content"
    )
    migration_filename: str | None = None
    source_type: str = Field(
        default="auto", description="auto | sql | alembic | prisma | django"
    )
    scenario_id: str | None = Field(default=None, description="Legacy curated scenario id")
    sample_filename: str | None = Field(
        default=None, description="Load a file from samples/migrations by filename"
    )
    repo_path: str | None = Field(default=None, description="Optional path for code-reference search")
    auto_analyze: bool = True


class AnalysisSummary(BaseModel):
    id: UUID
    title: str
    source_type: str
    scenario_id: str | None = None
    status: str
    overall_risk: str | None = None
    overall_score: float | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class AnalysisDetail(AnalysisSummary):
    migration_sql: str
    migration_filename: str | None = None
    repo_path: str | None = None
    operations: list[dict[str, Any]] | dict[str, Any] | None = None
    risk_findings: list[dict[str, Any]] | dict[str, Any] | None = None
    dependency_graph: dict[str, Any] | None = None
    code_references: list[dict[str, Any]] | dict[str, Any] | None = None
    rollout_plan: list[dict[str, Any]] | dict[str, Any] | None = None
    rollback_sql: str | None = None
    llm_explanation: str | None = None
    markdown_report: str | None = None
    agent_trace: list[dict[str, Any]] | dict[str, Any] | None = None
    github_meta: dict[str, Any] | None = None
    error_message: str | None = None
    updated_at: datetime | None = None


class ScenarioOut(BaseModel):
    id: str
    title: str
    description: str
    source_type: str
    filename: str
    expected_risk: str
    tags: list[str] = []


class WebhookPayload(BaseModel):
    action: str | None = None
    pull_request: dict[str, Any] | None = None
    repository: dict[str, Any] | None = None
    installation: dict[str, Any] | None = None


class HealthOut(BaseModel):
    status: str
    app: str
    agent_mode: str
    use_openai: bool
