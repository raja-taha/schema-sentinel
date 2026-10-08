from urllib.parse import urlparse

from app.services.db_stats import fetch_live_table_stats, rewrite_target_url_for_runtime
from app.services.scenarios import default_table_stats


def test_synthetic_fallback_when_no_target(monkeypatch):
    monkeypatch.setenv("TARGET_DATABASE_URL", "")
    from app.core.config import get_settings

    get_settings.cache_clear()
    result = fetch_live_table_stats("")
    assert result["source"] == "synthetic"
    assert "users" in result["rows"]
    assert result["rows"]["users"] == default_table_stats()["users"]
    get_settings.cache_clear()


def test_rewrite_localhost_in_docker(monkeypatch):
    monkeypatch.setattr("app.services.db_stats._running_in_docker", lambda: True)
    rewritten = rewrite_target_url_for_runtime(
        "postgresql://sentinel:sentinel@localhost:5434/schemasentinel"
    )
    parsed = urlparse(rewritten)
    assert parsed.hostname == "db"
    assert parsed.port == 5432
