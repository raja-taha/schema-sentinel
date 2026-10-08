"""GitHub PR file fetch, checks, and review comments."""

from __future__ import annotations

import base64
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.parser import detect_source_type

logger = get_logger("github")

_MIGRATION_HINTS = (
    "migration",
    "migrations",
    "alembic",
    "prisma/migrations",
    ".sql",
)


def _headers() -> dict[str, str]:
    settings = get_settings()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


async def list_pr_files(repo_full_name: str, pr_number: int) -> list[dict[str, Any]]:
    settings = get_settings()
    if not settings.github_token:
        logger.info("github_list_files_skipped", reason="no_token")
        return []

    files: list[dict[str, Any]] = []
    page = 1
    async with httpx.AsyncClient(timeout=45) as client:
        while page <= 10:
            url = (
                f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}/files"
                f"?per_page=100&page={page}"
            )
            resp = await client.get(url, headers=_headers())
            if resp.status_code >= 400:
                logger.warning(
                    "github_list_files_failed",
                    status=resp.status_code,
                    body=resp.text[:300],
                )
                break
            batch = resp.json()
            if not batch:
                break
            files.extend(batch)
            if len(batch) < 100:
                break
            page += 1
    return files


async def get_file_content(repo_full_name: str, path: str, ref: str) -> str | None:
    settings = get_settings()
    if not settings.github_token:
        return None

    url = f"https://api.github.com/repos/{repo_full_name}/contents/{path}"
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.get(url, headers=_headers(), params={"ref": ref})
        if resp.status_code >= 400:
            logger.warning(
                "github_get_file_failed",
                path=path,
                status=resp.status_code,
                body=resp.text[:200],
            )
            return None
        data = resp.json()
        if data.get("encoding") == "base64" and data.get("content"):
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        if isinstance(data.get("content"), str):
            return data["content"]
        # Fallback: raw download URL
        download = data.get("download_url")
        if download:
            raw = await client.get(download, headers=_headers())
            if raw.status_code < 400:
                return raw.text
    return None


def extract_migration_files_from_pr(pr_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for f in pr_files:
        name = (f.get("filename") or "").lower()
        status = (f.get("status") or "").lower()
        if status == "removed":
            continue
        if any(h in name for h in _MIGRATION_HINTS) or name.endswith(".sql"):
            out.append(f)
    return out


async def collect_pr_migrations(
    *,
    repo_full_name: str,
    pr_number: int,
    head_sha: str | None = None,
) -> dict[str, Any]:
    """
    Fetch PR changed files, filter migrations, download contents.

    Returns migration_sql (joined), filenames, source_type, file metas.
    """
    files = await list_pr_files(repo_full_name, pr_number)
    migrations = extract_migration_files_from_pr(files)
    if not migrations:
        return {
            "migration_sql": "",
            "filenames": [],
            "source_type": "sql",
            "files": [],
            "pr_file_count": len(files),
        }

    ref = head_sha or "HEAD"
    chunks: list[str] = []
    metas: list[dict[str, Any]] = []
    source_type = "sql"

    for item in migrations:
        path = item.get("filename") or ""
        # Prefer patch for added/modified when content API fails; else full file
        content = await get_file_content(repo_full_name, path, ref)
        if not content and item.get("patch"):
            # Reconstruct rough SQL from patch added lines
            added = [
                line[1:]
                for line in (item["patch"] or "").splitlines()
                if line.startswith("+") and not line.startswith("+++")
            ]
            content = "\n".join(added)
        if not content:
            continue
        detected = detect_source_type(content, filename=path)
        if detected != "sql":
            source_type = detected
        chunks.append(f"-- file: {path}\n{content.strip()}\n")
        metas.append(
            {
                "filename": path,
                "status": item.get("status"),
                "sha": item.get("sha"),
                "additions": item.get("additions"),
                "deletions": item.get("deletions"),
            }
        )

    return {
        "migration_sql": "\n".join(chunks).strip(),
        "filenames": [m["filename"] for m in metas],
        "source_type": source_type,
        "files": metas,
        "pr_file_count": len(files),
    }


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
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=_headers(), json={"body": body})
        if resp.status_code >= 400:
            logger.warning("github_comment_failed", status=resp.status_code, body=resp.text[:300])
            return {"ok": False, "status": resp.status_code}
        return {"ok": True, "status": resp.status_code, "data": resp.json()}


async def create_check_run(
    *,
    repo_full_name: str,
    head_sha: str,
    conclusion: str,
    title: str,
    summary: str,
) -> dict[str, Any] | None:
    """Create a completed GitHub Check Run for the commit."""
    settings = get_settings()
    if not settings.github_token or not head_sha:
        return None

    url = f"https://api.github.com/repos/{repo_full_name}/check-runs"
    payload = {
        "name": settings.github_check_name,
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": conclusion if conclusion in {"success", "failure", "neutral", "cancelled", "timed_out", "action_required", "skipped"} else "neutral",
        "output": {
            "title": title,
            "summary": summary[:65000],
        },
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=_headers(), json=payload)
        if resp.status_code >= 400:
            logger.warning("github_check_failed", status=resp.status_code, body=resp.text[:300])
            return {"ok": False, "status": resp.status_code, "body": resp.text[:300]}
        return {"ok": True, "status": resp.status_code, "data": resp.json()}


def conclusion_from_risk(overall_risk: str) -> str:
    if overall_risk in {"critical", "high"}:
        return "failure"
    if overall_risk == "medium":
        return "neutral"
    return "success"
