"""Search application code for table/column references (regex-based, tree-sitter-ready)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_CODE_GLOBS = (
    "*.py",
    "*.ts",
    "*.tsx",
    "*.js",
    "*.jsx",
    "*.go",
    "*.rb",
    "*.java",
    "*.sql",
    "*.prisma",
)

_SKIP_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    ".next",
    "dist",
    "build",
    ".pytest_cache",
}


def _iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    if not root.exists():
        return files
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lstrip(".") in {
            "py", "ts", "tsx", "js", "jsx", "go", "rb", "java", "sql", "prisma"
        } or path.name in _CODE_GLOBS:
            files.append(path)
    return files


def search_references(
    operations: list[dict[str, Any]],
    repo_path: str | Path | None,
    max_hits: int = 80,
) -> list[dict[str, Any]]:
    if not repo_path:
        return []
    root = Path(repo_path)
    if not root.exists():
        return []

    targets: list[tuple[str | None, str | None]] = []
    for op in operations:
        table = op.get("table")
        column = op.get("column")
        if table:
            targets.append((table, column))
            new_name = (op.get("metadata") or {}).get("new_name")
            if new_name and op.get("op_type") in {"rename_column", "rename_table"}:
                targets.append((new_name if op.get("op_type") == "rename_table" else table, new_name if op.get("op_type") == "rename_column" else None))

    # Deduplicate
    seen_t: set[tuple] = set()
    uniq_targets = []
    for t in targets:
        if t not in seen_t:
            seen_t.add(t)
            uniq_targets.append(t)

    hits: list[dict[str, Any]] = []
    files = _iter_files(root)

    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lines = text.splitlines()
        for table, column in uniq_targets:
            if not table:
                continue
            patterns = [
                re.compile(rf"\b{re.escape(table)}\b", re.IGNORECASE),
                re.compile(rf"['\"]table['\"]\s*:\s*['\"]{re.escape(table)}['\"]", re.IGNORECASE),
                re.compile(rf"FROM\s+{re.escape(table)}\b", re.IGNORECASE),
                re.compile(rf"INTO\s+{re.escape(table)}\b", re.IGNORECASE),
                re.compile(rf"UPDATE\s+{re.escape(table)}\b", re.IGNORECASE),
                re.compile(rf"__tablename__\s*=\s*['\"]{re.escape(table)}['\"]"),
                re.compile(rf"model\s+{re.escape(table)}\b", re.IGNORECASE),
            ]
            if column:
                patterns.extend(
                    [
                        re.compile(rf"\b{re.escape(table)}\.{re.escape(column)}\b", re.IGNORECASE),
                        re.compile(rf"['\"]{re.escape(column)}['\"]"),
                        re.compile(rf"\b{re.escape(column)}\b"),
                    ]
                )

            for i, line in enumerate(lines, start=1):
                for pat in patterns:
                    if pat.search(line):
                        # Prefer stronger matches; skip very generic column-only on short names
                        if column and pat.pattern == rf"\b{re.escape(column)}\b" and len(column) < 3:
                            continue
                        hits.append(
                            {
                                "path": str(path.relative_to(root)).replace("\\", "/"),
                                "line": i,
                                "snippet": line.strip()[:240],
                                "table": table,
                                "column": column,
                                "symbol": f"{table}.{column}" if column else table,
                                "endpoint_hint": _guess_endpoint(path, lines),
                            }
                        )
                        break
                if len(hits) >= max_hits:
                    return _dedupe_hits(hits)
    return _dedupe_hits(hits)


def _guess_endpoint(path: Path, lines: list[str]) -> str | None:
    text = "\n".join(lines[:80])
    m = re.search(r"@(?:app|router)\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)", text)
    if m:
        return f"{m.group(1).upper()} {m.group(2)}"
    m = re.search(r"(?:export\s+async\s+function|export\s+function)\s+(GET|POST|PUT|PATCH|DELETE)", text)
    if m:
        return f"{m.group(1)} /{path.parent.name}"
    return None


def _dedupe_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple] = set()
    out = []
    for h in hits:
        key = (h["path"], h["line"], h.get("table"), h.get("column"))
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out
