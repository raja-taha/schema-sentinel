"""Generate expand → backfill → switch → contract rollout steps and rollback SQL."""

from __future__ import annotations

from typing import Any


def build_rollout_plan(
    operations: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = [
        {
            "phase": "expand",
            "title": "Expand schema (backward compatible)",
            "description": (
                "Add new columns/tables/indexes as nullable or concurrent so old code keeps working."
            ),
            "actions": [],
        },
        {
            "phase": "backfill",
            "title": "Backfill data",
            "description": "Populate new columns in batches; verify null rates before constraining.",
            "actions": [],
        },
        {
            "phase": "switch",
            "title": "Switch application reads/writes",
            "description": "Deploy code that uses the new schema; keep dual-write if renaming.",
            "actions": [],
        },
        {
            "phase": "contract",
            "title": "Contract (remove old shape)",
            "description": "Only after traffic has moved: drop old columns/tables and tighten constraints.",
            "actions": [],
        },
    ]

    by_phase = {s["phase"]: s for s in steps}

    for op in operations:
        op_type = op.get("op_type")
        table = op.get("table")
        column = op.get("column")

        if op_type == "add_column":
            by_phase["expand"]["actions"].append(
                f"ADD COLUMN `{table}.{column}` as NULLABLE (ignore NOT NULL until backfill)."
            )
            by_phase["backfill"]["actions"].append(
                f"Batch UPDATE `{table}` SET `{column}` = <derived value> WHERE `{column}` IS NULL."
            )
            if op.get("nullable") is False:
                by_phase["contract"]["actions"].append(
                    f"ALTER `{table}.{column}` SET NOT NULL after verifying zero NULLs."
                )
        elif op_type == "create_index":
            by_phase["expand"]["actions"].append(
                f"CREATE INDEX CONCURRENTLY on `{table}` (avoid blocking writes)."
            )
        elif op_type == "create_table":
            by_phase["expand"]["actions"].append(f"CREATE TABLE `{table}` (empty, additive).")
            by_phase["switch"]["actions"].append(f"Point writers/readers at `{table}`.")
        elif op_type in {"rename_column", "rename_table"}:
            new_name = (op.get("metadata") or {}).get("new_name")
            by_phase["expand"]["actions"].append(
                f"Add new name `{new_name}` alongside `{column or table}` (do not rename in place)."
            )
            by_phase["backfill"]["actions"].append(
                f"Dual-write/sync `{column or table}` → `{new_name}`."
            )
            by_phase["switch"]["actions"].append(
                f"Deploy app to read `{new_name}`; keep dual-write until stable."
            )
            by_phase["contract"]["actions"].append(
                f"Drop old `{column or table}` after observability confirms zero reads."
            )
        elif op_type == "set_not_null":
            by_phase["backfill"]["actions"].append(
                f"Ensure `{table}.{column}` has no NULLs; backfill stragglers."
            )
            by_phase["contract"]["actions"].append(
                f"SET NOT NULL on `{table}.{column}` in a low-traffic window."
            )
        elif op_type == "alter_column_type":
            by_phase["expand"]["actions"].append(
                f"Add shadow column `{column}_new` with target type on `{table}`."
            )
            by_phase["backfill"]["actions"].append(
                f"Cast/backfill `{table}.{column}` → `{column}_new` in batches."
            )
            by_phase["switch"]["actions"].append(
                f"Flip app to `{column}_new`; keep old column until verified."
            )
            by_phase["contract"]["actions"].append(
                f"Drop old `{column}` and rename `{column}_new` → `{column}`."
            )
        elif op_type in {"drop_column", "drop_table"}:
            target = f"{table}.{column}" if column else str(table)
            by_phase["switch"]["actions"].append(
                f"Remove all code references to `{target}` before dropping."
            )
            by_phase["contract"]["actions"].append(
                f"DROP `{target}` only after deploy + bake time."
            )
        elif op_type == "add_foreign_key":
            by_phase["expand"]["actions"].append(
                f"ADD CONSTRAINT ... FOREIGN KEY on `{table}` AS NOT VALID."
            )
            by_phase["backfill"]["actions"].append(
                f"VALIDATE CONSTRAINT on `{table}` in a separate transaction."
            )
        else:
            by_phase["expand"]["actions"].append(
                f"Review `{op_type}` on `{table}` — apply with expand/contract if disruptive."
            )

    # Attach finding-driven notes
    irreversible = [f for f in findings if not f.get("reversible", True)]
    if irreversible:
        by_phase["contract"]["actions"].append(
            f"⚠ {len(irreversible)} irreversible finding(s) — snapshot/backup before contract phase."
        )

    # Drop empty phases' empty action noise but keep structure
    for step in steps:
        if not step["actions"]:
            step["actions"].append("No specific actions for this phase given current operations.")

    return steps


def generate_rollback_sql(operations: list[dict[str, Any]]) -> str:
    lines = [
        "-- SchemaSentinel generated rollback sketch",
        "-- WARNING: Not every migration is safely reversible. Review before executing.",
        "BEGIN;",
        "",
    ]
    reversible_count = 0
    irreversible_notes: list[str] = []

    # Reverse order
    for op in reversed(operations):
        op_type = op.get("op_type")
        table = op.get("table")
        column = op.get("column")
        meta = op.get("metadata") or {}

        if op_type == "add_column" and table and column:
            lines.append(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column};")
            reversible_count += 1
        elif op_type == "create_table" and table:
            lines.append(f"-- Irreversible if data was written: DROP TABLE IF EXISTS {table};")
            irreversible_notes.append(f"create_table:{table}")
        elif op_type == "create_index":
            idx = op.get("index_name") or f"idx_{table}_manual"
            lines.append(f"DROP INDEX IF EXISTS {idx};")
            reversible_count += 1
        elif op_type == "drop_column":
            lines.append(
                f"-- CANNOT auto-rollback DROP COLUMN {table}.{column} — restore from backup."
            )
            irreversible_notes.append(f"drop_column:{table}.{column}")
        elif op_type == "drop_table":
            lines.append(f"-- CANNOT auto-rollback DROP TABLE {table} — restore from backup.")
            irreversible_notes.append(f"drop_table:{table}")
        elif op_type == "set_not_null" and table and column:
            lines.append(f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL;")
            reversible_count += 1
        elif op_type == "drop_not_null" and table and column:
            lines.append(
                f"-- Re-apply NOT NULL only after verifying no NULLs:\n"
                f"-- ALTER TABLE {table} ALTER COLUMN {column} SET NOT NULL;"
            )
        elif op_type == "rename_column" and table and column:
            new_name = meta.get("new_name")
            if new_name:
                lines.append(f"ALTER TABLE {table} RENAME COLUMN {new_name} TO {column};")
                reversible_count += 1
        elif op_type == "rename_table" and table:
            new_name = meta.get("new_name")
            if new_name:
                lines.append(f"ALTER TABLE {new_name} RENAME TO {table};")
                reversible_count += 1
        elif op_type == "alter_column_type":
            lines.append(
                f"-- Type change on {table}.{column} may be irreversible without shadow column."
            )
            irreversible_notes.append(f"alter_column_type:{table}.{column}")
        elif op_type == "add_foreign_key" and table:
            lines.append(f"-- ALTER TABLE {table} DROP CONSTRAINT <fk_name>;")
            reversible_count += 1
        else:
            lines.append(f"-- No automatic rollback for {op_type} on {table}")

    lines.extend(["", "COMMIT;", ""])
    if irreversible_notes:
        lines.append(f"-- Irreversible operations ({len(irreversible_notes)}):")
        for note in irreversible_notes:
            lines.append(f"--   - {note}")
    lines.append(f"-- Sketched reversible statements: {reversible_count}")
    return "\n".join(lines)
