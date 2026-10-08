"""Deterministic migration risk rules (lock / compatibility / data-loss)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.config import get_settings

# Risky type widen/narrow pairs (simplified PostgreSQL)
_NARROWING = {
    ("text", "varchar"),
    ("varchar", "char"),
    ("bigint", "integer"),
    ("integer", "smallint"),
    ("numeric", "integer"),
    ("timestamptz", "timestamp"),
    ("jsonb", "json"),
    ("uuid", "text"),
    ("text", "integer"),
    ("varchar", "integer"),
    ("text", "int"),
}

_TYPE_ALIASES = {
    "int": "integer",
    "int4": "integer",
    "int8": "bigint",
    "int2": "smallint",
    "bool": "boolean",
    "character varying": "varchar",
    "double precision": "float",
}


def _norm_type(value: str | None) -> str:
    if not value:
        return ""
    base = value.lower().split("(")[0].strip()
    return _TYPE_ALIASES.get(base, base)


@dataclass
class RiskFinding:
    rule_id: str
    title: str
    severity: str  # low | medium | high | critical
    category: str  # lock | compatibility | data_loss | operational
    score: float  # 0.0 – 1.0
    table: str | None = None
    column: str | None = None
    message: str = ""
    reversible: bool = True
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _row_estimate(table: str | None, table_stats: dict[str, int]) -> int:
    settings = get_settings()
    if not table:
        return settings.default_table_row_estimate
    return table_stats.get(table.lower(), settings.default_table_row_estimate)


def _lock_score(rows: int) -> float:
    if rows >= 10_000_000:
        return 0.95
    if rows >= 1_000_000:
        return 0.8
    if rows >= 100_000:
        return 0.55
    if rows >= 10_000:
        return 0.35
    return 0.15


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------

def rule_drop_table(op: dict, stats: dict[str, int]) -> RiskFinding | None:
    if op.get("op_type") != "drop_table":
        return None
    rows = _row_estimate(op.get("table"), stats)
    return RiskFinding(
        rule_id="R01_DROP_TABLE",
        title="Drop table",
        severity="critical",
        category="data_loss",
        score=min(1.0, 0.85 + _lock_score(rows) * 0.15),
        table=op.get("table"),
        message=f"Dropping table `{op.get('table')}` destroys data and breaks all dependents.",
        reversible=False,
        evidence={"row_estimate": rows},
    )


def rule_drop_column(op: dict, stats: dict[str, int]) -> RiskFinding | None:
    if op.get("op_type") != "drop_column":
        return None
    rows = _row_estimate(op.get("table"), stats)
    return RiskFinding(
        rule_id="R02_DROP_COLUMN",
        title="Drop column",
        severity="high",
        category="data_loss",
        score=0.75 + min(0.2, _lock_score(rows) * 0.2),
        table=op.get("table"),
        column=op.get("column"),
        message=(
            f"Dropping `{op.get('table')}.{op.get('column')}` is irreversible without backups "
            "and will break any code still reading that column."
        ),
        reversible=False,
        evidence={"row_estimate": rows},
    )


def rule_set_not_null(op: dict, stats: dict[str, int]) -> RiskFinding | None:
    if op.get("op_type") != "set_not_null":
        return None
    rows = _row_estimate(op.get("table"), stats)
    return RiskFinding(
        rule_id="R03_SET_NOT_NULL",
        title="Set NOT NULL without proven backfill",
        severity="high",
        category="compatibility",
        score=0.7 + min(0.25, _lock_score(rows) * 0.25),
        table=op.get("table"),
        column=op.get("column"),
        message=(
            f"Setting `{op.get('table')}.{op.get('column')}` NOT NULL fails if existing NULLs "
            "remain and may take an ACCESS EXCLUSIVE lock on large tables."
        ),
        reversible=True,
        evidence={"row_estimate": rows, "lock_risk": _lock_score(rows)},
    )


def rule_add_not_null_no_default(op: dict, stats: dict[str, int]) -> RiskFinding | None:
    if op.get("op_type") != "add_column":
        return None
    if op.get("nullable") is False and not op.get("default"):
        rows = _row_estimate(op.get("table"), stats)
        return RiskFinding(
            rule_id="R04_ADD_NOT_NULL_NO_DEFAULT",
            title="Add NOT NULL column without default",
            severity="critical",
            category="compatibility",
            score=0.92,
            table=op.get("table"),
            column=op.get("column"),
            message=(
                f"Adding NOT NULL column `{op.get('column')}` without DEFAULT fails on "
                f"non-empty table `{op.get('table')}` (~{rows:,} rows)."
            ),
            reversible=True,
            evidence={"row_estimate": rows},
        )
    return None


def rule_type_narrowing(op: dict, stats: dict[str, int]) -> RiskFinding | None:
    if op.get("op_type") != "alter_column_type":
        return None
    new_type = _norm_type(op.get("new_type"))
    old_type = _norm_type(op.get("old_type"))
    risky_targets = {"integer", "smallint", "boolean", "uuid", "date", "int"}
    narrowing = False
    if old_type and (old_type, new_type) in _NARROWING:
        narrowing = True
    elif not old_type and new_type in risky_targets:
        # Unknown source type → cast into a strict target is treated as narrowing risk
        narrowing = True

    rows = _row_estimate(op.get("table"), stats)
    if narrowing:
        return RiskFinding(
            rule_id="R05_TYPE_NARROWING",
            title="Narrowing type change",
            severity="critical",
            category="data_loss",
            score=0.9,
            table=op.get("table"),
            column=op.get("column"),
            message=(
                f"Narrowing `{op.get('table')}.{op.get('column')}` "
                f"({old_type or '?'} → {new_type}) can truncate or reject rows."
            ),
            reversible=False,
            evidence={"old_type": old_type, "new_type": new_type, "row_estimate": rows},
        )

    if new_type:
        return RiskFinding(
            rule_id="R05_TYPE_CHANGE",
            title="Column type change",
            severity="high",
            category="compatibility",
            score=0.65 + min(0.25, _lock_score(rows) * 0.2),
            table=op.get("table"),
            column=op.get("column"),
            message=(
                f"Altering `{op.get('table')}.{op.get('column')}` type to `{new_type}` "
                "may rewrite the table and reject non-castable values."
            ),
            reversible=False,
            evidence={"new_type": new_type, "row_estimate": rows},
        )
    return None


def rule_rename_column(op: dict, stats: dict[str, int]) -> RiskFinding | None:
    if op.get("op_type") != "rename_column":
        return None
    return RiskFinding(
        rule_id="R06_RENAME_COLUMN",
        title="Rename column",
        severity="high",
        category="compatibility",
        score=0.72,
        table=op.get("table"),
        column=op.get("column"),
        message=(
            f"Renaming `{op.get('table')}.{op.get('column')}` to "
            f"`{op.get('metadata', {}).get('new_name')}` breaks ORM models and raw SQL "
            "that still use the old name. Prefer expand/contract."
        ),
        reversible=True,
        evidence={"new_name": (op.get("metadata") or {}).get("new_name")},
    )


def rule_rename_table(op: dict, stats: dict[str, int]) -> RiskFinding | None:
    if op.get("op_type") != "rename_table":
        return None
    return RiskFinding(
        rule_id="R07_RENAME_TABLE",
        title="Rename table",
        severity="high",
        category="compatibility",
        score=0.78,
        table=op.get("table"),
        message=(
            f"Renaming table `{op.get('table')}` invalidates FKs, views, and application "
            "queries. Use dual-write / synonym period when possible."
        ),
        reversible=True,
        evidence={"new_name": (op.get("metadata") or {}).get("new_name")},
    )


def rule_nonconcurrent_index(op: dict, stats: dict[str, int]) -> RiskFinding | None:
    if op.get("op_type") != "create_index":
        return None
    meta = op.get("metadata") or {}
    if meta.get("concurrent"):
        return RiskFinding(
            rule_id="R08_CONCURRENT_INDEX",
            title="Concurrent index create",
            severity="low",
            category="operational",
            score=0.2,
            table=op.get("table"),
            message="CREATE INDEX CONCURRENTLY avoids long exclusive locks; still monitor I/O.",
            reversible=True,
            evidence={"concurrent": True},
        )
    rows = _row_estimate(op.get("table"), stats)
    severity = "high" if rows >= 100_000 else "medium"
    return RiskFinding(
        rule_id="R08_NONCONCURRENT_INDEX",
        title="Index without CONCURRENTLY",
        severity=severity,
        category="lock",
        score=0.4 + _lock_score(rows) * 0.5,
        table=op.get("table"),
        message=(
            f"CREATE INDEX on `{op.get('table')}` (~{rows:,} rows) without CONCURRENTLY "
            "blocks writes for the duration of the build."
        ),
        reversible=True,
        evidence={"row_estimate": rows, "concurrent": False},
    )


def rule_add_foreign_key(op: dict, stats: dict[str, int]) -> RiskFinding | None:
    if op.get("op_type") != "add_foreign_key":
        return None
    rows = _row_estimate(op.get("table"), stats)
    raw = (op.get("raw_sql") or "").lower()
    not_valid = "not valid" in raw
    if not_valid:
        return RiskFinding(
            rule_id="R09_FK_NOT_VALID",
            title="Foreign key NOT VALID",
            severity="low",
            category="lock",
            score=0.25,
            table=op.get("table"),
            message="FK added as NOT VALID — validate in a later phase to reduce lock time.",
            reversible=True,
            evidence={"not_valid": True, "referenced_table": op.get("referenced_table")},
        )
    return RiskFinding(
        rule_id="R09_ADD_FOREIGN_KEY",
        title="Add foreign key",
        severity="medium" if rows < 1_000_000 else "high",
        category="lock",
        score=0.45 + _lock_score(rows) * 0.4,
        table=op.get("table"),
        message=(
            f"Adding FK on `{op.get('table')}` → `{op.get('referenced_table')}` scans "
            f"~{rows:,} rows and locks both tables unless added NOT VALID then validated."
        ),
        reversible=True,
        evidence={
            "row_estimate": rows,
            "referenced_table": op.get("referenced_table"),
        },
    )


def rule_volatile_default(op: dict, stats: dict[str, int]) -> RiskFinding | None:
    if op.get("op_type") != "add_column":
        return None
    default = (op.get("default") or "").lower()
    volatile = any(tok in default for tok in ("now()", "clock_timestamp", "random(", "gen_random"))
    if not volatile:
        # Also check raw SQL for ADD COLUMN ... DEFAULT now()
        raw = (op.get("raw_sql") or "").lower()
        if "default" in raw and any(
            tok in raw for tok in ("now()", "clock_timestamp", "random(", "gen_random_uuid")
        ):
            volatile = True
            if "gen_random_uuid" in raw and op.get("nullable") is not False:
                # uuid default on add is often OK on PG11+
                rows = _row_estimate(op.get("table"), stats)
                if rows < 100_000:
                    return None
        else:
            return None
    rows = _row_estimate(op.get("table"), stats)
    return RiskFinding(
        rule_id="R10_VOLATILE_DEFAULT",
        title="Volatile DEFAULT on add column",
        severity="medium" if rows < 1_000_000 else "high",
        category="lock",
        score=0.5 + _lock_score(rows) * 0.35,
        table=op.get("table"),
        column=op.get("column"),
        message=(
            f"Adding column with volatile DEFAULT on `{op.get('table')}` (~{rows:,} rows) "
            "may rewrite every row. Prefer add nullable → backfill → set default/constraints."
        ),
        reversible=True,
        evidence={"row_estimate": rows, "default": op.get("default")},
    )


RULES = [
    rule_drop_table,
    rule_drop_column,
    rule_set_not_null,
    rule_add_not_null_no_default,
    rule_type_narrowing,
    rule_rename_column,
    rule_rename_table,
    rule_nonconcurrent_index,
    rule_add_foreign_key,
    rule_volatile_default,
]


_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def score_operations(
    operations: list[dict[str, Any]],
    table_stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    stats = {k.lower(): v for k, v in (table_stats or {}).items()}
    findings: list[RiskFinding] = []

    for op in operations:
        for rule in RULES:
            try:
                finding = rule(op, stats)
            except TypeError:
                # Defensive: rule_add_foreign_key had a bad kw temporarily
                finding = None
            if finding:
                findings.append(finding)

    if not findings and operations:
        findings.append(
            RiskFinding(
                rule_id="R00_NO_MATCH",
                title="No high-risk pattern matched",
                severity="low",
                category="operational",
                score=0.15,
                message="Operations parsed but no deterministic high-risk rule fired. Still review manually.",
            )
        )

    findings.sort(key=lambda f: (-f.score, -_SEVERITY_RANK.get(f.severity, 0)))
    max_score = max((f.score for f in findings), default=0.0)
    settings = get_settings()

    if max_score >= 0.85 or any(f.severity == "critical" for f in findings):
        level = "critical"
    elif max_score >= settings.risk_threshold_high:
        level = "high"
    elif max_score >= settings.risk_threshold_medium:
        level = "medium"
    else:
        level = "low"

    return {
        "findings": [f.to_dict() for f in findings],
        "overall_score": round(max_score, 3),
        "overall_risk": level,
        "rule_count_fired": len([f for f in findings if f.rule_id != "R00_NO_MATCH"]),
    }
