"""Discover and load migration files from the samples library (and uploads)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.parser import detect_source_type


def _migrations_dirs() -> list[Path]:
    settings = get_settings()
    candidates = [
        settings.samples_dir / "migrations",
        Path("/samples/migrations"),
    ]
    return [p for p in candidates if p.is_dir()]


def list_sample_migrations() -> list[dict[str, Any]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for root in _migrations_dirs():
        for path in sorted(root.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".sql", ".py", ".prisma"}:
                continue
            if path.name in seen:
                continue
            seen.add(path.name)
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue
            source_type = detect_source_type(content, filename=path.name)
            preview = " ".join(
                line.strip()
                for line in content.splitlines()
                if line.strip() and not line.strip().startswith("#") and not line.strip().startswith('"""')
            )[:160]
            items.append(
                {
                    "id": path.stem,
                    "filename": path.name,
                    "title": path.stem.replace("_", " "),
                    "source_type": source_type,
                    "preview": preview,
                    "bytes": path.stat().st_size,
                }
            )
    return items


def load_sample_migration(filename: str) -> dict[str, Any]:
    safe = Path(filename).name
    for root in _migrations_dirs():
        path = root / safe
        if path.is_file():
            content = path.read_text(encoding="utf-8")
            return {
                "filename": safe,
                "migration_sql": content,
                "source_type": detect_source_type(content, filename=safe),
                "title": safe,
            }
    raise KeyError(f"Sample not found: {safe}")
