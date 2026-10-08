from pathlib import Path

from app.services.parser import parse_migration
from app.services.risk_engine import score_operations
from app.services.scenarios import default_table_stats, load_scenario_sql

STATS = default_table_stats()


def test_not_null_without_default_is_critical():
    sql, _ = load_scenario_sql("drop-not-null-users")
    ops = parse_migration(sql, source_type="sql")
    result = score_operations(ops, STATS)
    assert result["overall_risk"] in {"critical", "high"}
    ids = {f["rule_id"] for f in result["findings"]}
    assert "R04_ADD_NOT_NULL_NO_DEFAULT" in ids


def test_drop_column_is_high():
    sql, _ = load_scenario_sql("drop-column-orders")
    ops = parse_migration(sql, source_type="sql")
    result = score_operations(ops, STATS)
    assert result["overall_score"] >= 0.7
    assert any(f["rule_id"] == "R02_DROP_COLUMN" for f in result["findings"])


def test_nonconcurrent_index_lock_risk():
    sql, _ = load_scenario_sql("nonconcurrent-index")
    ops = parse_migration(sql, source_type="sql")
    result = score_operations(ops, STATS)
    assert any(f["rule_id"] == "R08_NONCONCURRENT_INDEX" for f in result["findings"])
    assert result["overall_score"] >= 0.5


def test_safe_nullable_add_is_low():
    sql, _ = load_scenario_sql("safe-add-nullable")
    ops = parse_migration(sql, source_type="sql")
    result = score_operations(ops, STATS)
    assert result["overall_risk"] in {"low", "medium"}
    assert result["overall_score"] < 0.7


def test_type_narrowing_critical():
    sql, _ = load_scenario_sql("type-narrowing")
    ops = parse_migration(sql, source_type="sql")
    result = score_operations(ops, STATS)
    assert result["overall_risk"] in {"critical", "high"}


def test_alembic_rename_parsed():
    sql, scenario = load_scenario_sql("rename-column-alembic")
    ops = parse_migration(sql, source_type=scenario["source_type"], filename=scenario["filename"])
    assert any(o["op_type"] == "rename_column" for o in ops)
    result = score_operations(ops, STATS)
    assert any(f["rule_id"] == "R06_RENAME_COLUMN" for f in result["findings"])


def test_samples_dir_exists():
    root = Path(__file__).resolve().parents[1] / "samples" / "migrations"
    assert (root / "001_add_email_not_null.sql").exists()
