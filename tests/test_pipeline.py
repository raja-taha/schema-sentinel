from app.services.analysis_service import analyze_sync
from app.services.code_search import search_references
from app.services.dependency_graph import build_dependency_graph
from app.services.parser import parse_migration
from app.services.rollout import build_rollout_plan, generate_rollback_sql
from app.services.scenarios import default_repo_path, load_scenario_sql


def test_end_to_end_sync_pipeline():
    sql, scenario = load_scenario_sql("drop-column-orders")
    result = analyze_sync(
        sql,
        source_type=scenario["source_type"],
        filename=scenario["filename"],
        repo_path=str(default_repo_path()),
        title=scenario["title"],
    )
    assert result["operations"]
    assert result["findings"]
    assert result["markdown_report"]
    assert "expand" in {s["phase"] for s in result["rollout_plan"]}
    assert "CANNOT auto-rollback" in result["rollback_sql"] or "DROP COLUMN" in result["rollback_sql"]
    assert any("orders" in (r.get("path") or "") or r.get("table") == "orders" for r in result["code_references"])


def test_dependency_graph_links_code():
    sql, _ = load_scenario_sql("drop-column-orders")
    ops = parse_migration(sql)
    refs = search_references(ops, default_repo_path())
    graph = build_dependency_graph(ops, refs)
    assert graph["stats"]["tables"] >= 1
    assert graph["stats"]["node_count"] >= 2


def test_rollout_phases_present():
    ops = parse_migration("ALTER TABLE users ADD COLUMN bio text NULL;")
    plan = build_rollout_plan(ops, [])
    assert [p["phase"] for p in plan] == ["expand", "backfill", "switch", "contract"]
    rb = generate_rollback_sql(ops)
    assert "BEGIN" in rb and "COMMIT" in rb
