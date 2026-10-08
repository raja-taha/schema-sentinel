import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AnalysisStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class RiskLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, default="sql")
    scenario_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=AnalysisStatus.pending.value)
    overall_risk: Mapped[str | None] = mapped_column(String(32), nullable=True)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    migration_sql: Mapped[str] = mapped_column(Text, nullable=False)
    migration_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    repo_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    operations: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    risk_findings: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    dependency_graph: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    code_references: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    rollout_plan: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    rollback_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    markdown_report: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_trace: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    github_meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TableStat(Base):
    """Synthetic or ingested table-size metadata for lock/rewrite risk estimates."""

    __tablename__ = "table_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schema_name: Mapped[str] = mapped_column(String(128), nullable=False, default="public")
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    row_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    has_indexes: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
