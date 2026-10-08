"""Optional GitHub check / PR comment helpers."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("github")


async def post_pr_comment(
    *,
    repo_full_name: str,
    pr_number: int,
    body: str,
) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.github_token:
        logger.info("github_skipped", reason="no_token")
        return None

    url = f"https://api.github.com/repos/{repo_full_name}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, json={"body": body})
        if resp.status_code >= 400:
            logger.warning("github_comment_failed", status=resp.status_code, body=resp.text[:300])
            return {"ok": False, "status": resp.status_code}
        return {"ok": True, "status": resp.status_code, "data": resp.json()}


def conclusion_from_risk(overall_risk: str) -> str:
    if overall_risk in {"critical", "high"}:
        return "failure"
    if overall_risk == "medium":
        return "neutral"
    return "success"


def extract_migration_files_from_pr(pr_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hints = ("migration", "migrations", "alembic", "prisma", ".sql")
    out = []
    for f in pr_files:
        name = (f.get("filename") or "").lower()
        if any(h in name for h in hints):
            out.append(f)
    return out
