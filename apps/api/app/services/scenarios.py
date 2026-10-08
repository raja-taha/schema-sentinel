"""Built-in risky migration scenarios for demos and evals."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import get_settings

SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "drop-not-null-users",
        "title": "Add NOT NULL email without default",
        "description": (
            "Adds a NOT NULL column to a hot users table with no DEFAULT — "
            "classic production outage pattern."
        ),
        "source_type": "sql",
        "filename": "001_add_email_not_null.sql",
        "expected_risk": "critical",
        "tags": ["compatibility", "not-null"],
    },
    {
        "id": "drop-column-orders",
        "title": "Drop column still referenced in API",
        "description": "Drops orders.status while FastAPI handlers still filter on it.",
        "source_type": "sql",
        "filename": "002_drop_orders_status.sql",
        "expected_risk": "high",
        "tags": ["data_loss", "blast-radius"],
    },
    {
        "id": "nonconcurrent-index",
        "title": "Blocking index on large table",
        "description": "CREATE INDEX without CONCURRENTLY on a multi-million row payments table.",
        "source_type": "sql",
        "filename": "003_index_payments.sql",
        "expected_risk": "high",
        "tags": ["lock", "index"],
    },
    {
        "id": "rename-column-alembic",
        "title": "Alembic rename without expand/contract",
        "description": "Alembic op that renames users.name → users.full_name in one step.",
        "source_type": "alembic",
        "filename": "004_rename_user_name.py",
        "expected_risk": "high",
        "tags": ["compatibility", "alembic"],
    },
    {
        "id": "type-narrowing",
        "title": "Narrow varchar to int",
        "description": "Alters products.sku from text to integer — data loss / cast failures.",
        "source_type": "sql",
        "filename": "005_narrow_sku_type.sql",
        "expected_risk": "critical",
        "tags": ["data_loss", "type"],
    },
    {
        "id": "safe-add-nullable",
        "title": "Safe nullable column add",
        "description": "Additive nullable column with no volatile default — should score low.",
        "source_type": "sql",
        "filename": "006_add_nullable_note.sql",
        "expected_risk": "low",
        "tags": ["safe", "expand"],
    },
]


def list_scenarios() -> list[dict[str, Any]]:
    return SCENARIOS


def get_scenario(scenario_id: str) -> dict[str, Any] | None:
    for s in SCENARIOS:
        if s["id"] == scenario_id:
            return s
    return None


def load_scenario_sql(scenario_id: str) -> tuple[str, dict[str, Any]]:
    scenario = get_scenario(scenario_id)
    if not scenario:
        raise KeyError(f"Unknown scenario: {scenario_id}")
    settings = get_settings()
    path = settings.samples_dir / "migrations" / scenario["filename"]
    if not path.exists():
        # Fallback: try relative to repo when running in Docker with /samples mount
        alt = Path("/samples/migrations") / scenario["filename"]
        path = alt if alt.exists() else path
    content = path.read_text(encoding="utf-8")
    return content, scenario


def default_repo_path() -> Path:
    settings = get_settings()
    sample_app = settings.samples_dir / "app_code"
    if sample_app.exists():
        return sample_app
    alt = Path("/samples/app_code")
    return alt if alt.exists() else sample_app


def default_table_stats() -> dict[str, int]:
    return {
        "users": 2_500_000,
        "orders": 18_000_000,
        "payments": 45_000_000,
        "products": 500_000,
        "accounts": 800_000,
    }
