"""Parse DDL / Alembic / Prisma / Django migrations into structured operations."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp


@dataclass
class SchemaOperation:
    op_type: str
    table: str | None = None
    column: str | None = None
    data_type: str | None = None
    nullable: bool | None = None
    default: str | None = None
    old_type: str | None = None
    new_type: str | None = None
    index_name: str | None = None
    constraint_name: str | None = None
    referenced_table: str | None = None
    raw_sql: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# SQL / DDL via SQLGlot
# ---------------------------------------------------------------------------

def _col_name(col: exp.Expression | None) -> str | None:
    if col is None:
        return None
    if isinstance(col, exp.Column):
        return col.name
    if isinstance(col, exp.Identifier):
        return col.name
    return str(col).strip('"')


def _table_name(node: exp.Expression) -> str | None:
    table = node.find(exp.Table)
    if table is not None:
        return table.name
    if hasattr(node, "this") and isinstance(node.this, exp.Table):
        return node.this.name
    return None


def parse_sql_ddl(sql: str) -> list[SchemaOperation]:
    ops: list[SchemaOperation] = []
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except Exception:
        # Fall back to statement-splitting + per-statement parse
        statements = []
        for chunk in re.split(r";\s*\n", sql):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                statements.extend(sqlglot.parse(chunk, read="postgres"))
            except Exception:
                ops.append(
                    SchemaOperation(
                        op_type="unknown",
                        raw_sql=chunk,
                        metadata={"parse_error": True},
                    )
                )

    for stmt in statements:
        if stmt is None:
            continue
        raw = stmt.sql(dialect="postgres")
        if isinstance(stmt, exp.Create):
            kind = (stmt.args.get("kind") or "").upper()
            if kind == "TABLE" or stmt.find(exp.Schema) is not None:
                table = _table_name(stmt) or "unknown"
                cols = []
                schema = stmt.find(exp.Schema)
                if schema:
                    for col_def in schema.find_all(exp.ColumnDef):
                        cols.append(_col_name(col_def.this))
                ops.append(
                    SchemaOperation(
                        op_type="create_table",
                        table=table,
                        raw_sql=raw,
                        metadata={"columns": cols},
                    )
                )
            elif kind == "INDEX":
                ops.append(
                    SchemaOperation(
                        op_type="create_index",
                        table=_table_name(stmt),
                        index_name=stmt.this.name if hasattr(stmt.this, "name") else None,
                        raw_sql=raw,
                        metadata={"concurrent": "concurrently" in raw.lower()},
                    )
                )
            continue

        if isinstance(stmt, exp.Drop):
            kind = (stmt.args.get("kind") or "").upper()
            if kind == "TABLE":
                ops.append(
                    SchemaOperation(
                        op_type="drop_table",
                        table=_table_name(stmt) or (stmt.this.name if stmt.this else None),
                        raw_sql=raw,
                    )
                )
            elif kind == "INDEX":
                ops.append(
                    SchemaOperation(
                        op_type="drop_index",
                        index_name=stmt.this.name if stmt.this else None,
                        raw_sql=raw,
                    )
                )
            elif kind == "COLUMN":
                # uncommon as top-level DROP COLUMN
                ops.append(SchemaOperation(op_type="drop_column", raw_sql=raw))
            continue

        # SQLGlot 26+: ALTER TABLE is exp.Alter (not AlterTable)
        if isinstance(stmt, exp.Alter) or type(stmt).__name__ == "Alter":
            table = _table_name(stmt)
            actions = stmt.args.get("actions") or []
            for action in actions:
                ops.extend(_parse_alter_action(action, table, raw))
            if not actions:
                ops.extend(_heuristic_alter(raw))
            continue

        if type(stmt).__name__ == "RenameTable" or isinstance(stmt, getattr(exp, "RenameTable", ())):
            to = stmt.args.get("to")
            new_name = getattr(to, "name", None) or str(to) if to is not None else None
            ops.append(
                SchemaOperation(
                    op_type="rename_table",
                    table=_table_name(stmt),
                    raw_sql=raw,
                    metadata={"new_name": new_name},
                )
            )
            continue

        lower = raw.lower()
        if "alter table" in lower:
            ops.extend(_heuristic_alter(raw))
        elif lower.strip():
            ops.append(SchemaOperation(op_type="other", raw_sql=raw))

    if not ops and sql.strip():
        ops.extend(_heuristic_full(sql))
    return ops


def _parse_alter_action(action: exp.Expression, table: str | None, raw: str) -> list[SchemaOperation]:
    results: list[SchemaOperation] = []
    action_name = type(action).__name__

    # ADD COLUMN → ColumnDef
    if isinstance(action, exp.ColumnDef) or action_name in {"ColumnDef", "AddColumnProperty"}:
        col = action.find(exp.ColumnDef) or action
        col_name = _col_name(getattr(col, "this", None))
        dtype = None
        kind = getattr(col, "kind", None) or (col.args.get("kind") if hasattr(col, "args") else None)
        if kind is not None:
            dtype = kind.sql(dialect="postgres") if hasattr(kind, "sql") else str(kind)
        col_sql = action.sql(dialect="postgres").lower()
        nullable = "not null" not in col_sql
        default = None
        if "default" in col_sql:
            m = re.search(r"default\s+(.+?)(?:\s|$)", col_sql)
            default = m.group(1) if m else None
            # NOT NULL with DEFAULT is still nullable=False for constraint purposes
            if "not null" in col_sql:
                nullable = False
        elif "not null" in col_sql:
            nullable = False
        results.append(
            SchemaOperation(
                op_type="add_column",
                table=table,
                column=col_name,
                data_type=dtype,
                nullable=nullable,
                default=default,
                raw_sql=raw,
            )
        )
        return results

    # DROP COLUMN
    if isinstance(action, exp.Drop) or action_name == "Drop":
        col = None
        if hasattr(action, "this") and action.this is not None:
            col = _col_name(action.this) or getattr(action.this, "name", None)
        results.append(
            SchemaOperation(op_type="drop_column", table=table, column=col, raw_sql=raw)
        )
        return results

    # ALTER COLUMN (type / nullability)
    if action_name == "AlterColumn" or isinstance(action, getattr(exp, "AlterColumn", ())):
        col = _col_name(action.this) if hasattr(action, "this") else None
        dtype = action.args.get("dtype") if hasattr(action, "args") else None
        if dtype is not None:
            new_type = dtype.sql(dialect="postgres") if hasattr(dtype, "sql") else str(dtype)
            results.append(
                SchemaOperation(
                    op_type="alter_column_type",
                    table=table,
                    column=col,
                    new_type=new_type,
                    raw_sql=raw,
                )
            )
            return results
        allow_null = action.args.get("allow_null") if hasattr(action, "args") else None
        if allow_null is False:
            results.append(
                SchemaOperation(
                    op_type="set_not_null",
                    table=table,
                    column=col,
                    nullable=False,
                    raw_sql=raw,
                )
            )
            return results
        if allow_null is True:
            results.append(
                SchemaOperation(
                    op_type="drop_not_null",
                    table=table,
                    column=col,
                    nullable=True,
                    raw_sql=raw,
                )
            )
            return results

    # RENAME COLUMN
    if action_name == "RenameColumn":
        old = _col_name(action.this) if hasattr(action, "this") else None
        to = action.args.get("to") if hasattr(action, "args") else None
        new_name = _col_name(to) if to is not None else None
        results.append(
            SchemaOperation(
                op_type="rename_column",
                table=table,
                column=old,
                raw_sql=raw,
                metadata={"new_name": new_name},
            )
        )
        return results

    action_sql = action.sql(dialect="postgres")
    lower = action_sql.lower()

    if "add constraint" in lower or "foreign key" in lower:
        ref = re.search(r"references\s+[\"']?(\w+)", lower)
        results.append(
            SchemaOperation(
                op_type="add_foreign_key",
                table=table,
                referenced_table=ref.group(1) if ref else None,
                raw_sql=raw,
            )
        )
        return results

    # Fallback heuristics on the action SQL
    results.extend(_heuristic_alter(f"ALTER TABLE {table or 'unknown'} {action_sql}"))
    if results:
        return results

    results.append(SchemaOperation(op_type="alter_table", table=table, raw_sql=raw))
    return results


def _heuristic_alter(raw: str) -> list[SchemaOperation]:
    lower = raw.lower()
    table_m = re.search(r"alter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?[\"']?(\w+)", lower)
    table = table_m.group(1) if table_m else None
    ops: list[SchemaOperation] = []

    patterns = [
        (
            r"add\s+column\s+(?:if\s+not\s+exists\s+)?[\"']?(\w+)[\"']?\s+(\w+(?:\([^)]+\))?)"
            r"((?:\s+not\s+null)?)((?:\s+default\s+[^,;]+)?)?",
            "add_column",
        ),
        (r"drop\s+column\s+(?:if\s+exists\s+)?[\"']?(\w+)", "drop_column"),
        (
            r"alter\s+column\s+[\"']?(\w+)[\"']?\s+(?:set\s+data\s+)?type\s+(\w+(?:\([^)]+\))?)",
            "alter_column_type",
        ),
        (r"alter\s+column\s+[\"']?(\w+)[\"']?\s+set\s+not\s+null", "set_not_null"),
        (r"alter\s+column\s+[\"']?(\w+)[\"']?\s+drop\s+not\s+null", "drop_not_null"),
        (r"rename\s+column\s+[\"']?(\w+)[\"']?\s+to\s+[\"']?(\w+)", "rename_column"),
        (r"rename\s+to\s+[\"']?(\w+)", "rename_table"),
        (r"add\s+constraint.+foreign\s+key.+references\s+[\"']?(\w+)", "add_foreign_key"),
    ]

    matched = False
    for pattern, op_type in patterns:
        for m in re.finditer(pattern, lower, re.IGNORECASE | re.DOTALL):
            matched = True
            if op_type == "add_column":
                not_null = "not null" in (m.group(3) or "")
                default = (m.group(4) or "").strip() or None
                ops.append(
                    SchemaOperation(
                        op_type=op_type,
                        table=table,
                        column=m.group(1),
                        data_type=m.group(2),
                        nullable=not not_null,
                        default=default.replace("default", "").strip() if default else None,
                        raw_sql=raw,
                    )
                )
            elif op_type == "alter_column_type":
                ops.append(
                    SchemaOperation(
                        op_type=op_type,
                        table=table,
                        column=m.group(1),
                        new_type=m.group(2),
                        raw_sql=raw,
                    )
                )
            elif op_type == "rename_column":
                ops.append(
                    SchemaOperation(
                        op_type=op_type,
                        table=table,
                        column=m.group(1),
                        raw_sql=raw,
                        metadata={"new_name": m.group(2)},
                    )
                )
            elif op_type == "rename_table":
                ops.append(
                    SchemaOperation(
                        op_type=op_type,
                        table=table,
                        raw_sql=raw,
                        metadata={"new_name": m.group(1)},
                    )
                )
            elif op_type == "add_foreign_key":
                ops.append(
                    SchemaOperation(
                        op_type=op_type,
                        table=table,
                        referenced_table=m.group(1),
                        raw_sql=raw,
                    )
                )
            else:
                ops.append(
                    SchemaOperation(
                        op_type=op_type,
                        table=table,
                        column=m.group(1) if m.lastindex else None,
                        raw_sql=raw,
                    )
                )
    if not matched:
        ops.append(SchemaOperation(op_type="alter_table", table=table, raw_sql=raw))
    return ops


def _heuristic_full(sql: str) -> list[SchemaOperation]:
    ops: list[SchemaOperation] = []
    for chunk in re.split(r";\s*", sql):
        chunk = chunk.strip()
        if not chunk:
            continue
        lower = chunk.lower()
        if lower.startswith("create table"):
            m = re.search(r"create\s+table\s+(?:if\s+not\s+exists\s+)?[\"']?(\w+)", lower)
            ops.append(
                SchemaOperation(
                    op_type="create_table",
                    table=m.group(1) if m else None,
                    raw_sql=chunk,
                )
            )
        elif lower.startswith("drop table"):
            m = re.search(r"drop\s+table\s+(?:if\s+exists\s+)?[\"']?(\w+)", lower)
            ops.append(
                SchemaOperation(
                    op_type="drop_table",
                    table=m.group(1) if m else None,
                    raw_sql=chunk,
                )
            )
        elif lower.startswith("create (unique )?index") or lower.startswith("create index") or "create unique index" in lower[:40]:
            concurrent = "concurrently" in lower
            m = re.search(r"on\s+[\"']?(\w+)", lower)
            ops.append(
                SchemaOperation(
                    op_type="create_index",
                    table=m.group(1) if m else None,
                    raw_sql=chunk,
                    metadata={"concurrent": concurrent},
                )
            )
        elif lower.startswith("alter table"):
            ops.extend(_heuristic_alter(chunk))
        else:
            ops.append(SchemaOperation(op_type="other", raw_sql=chunk))
    return ops


# ---------------------------------------------------------------------------
# Alembic / Prisma / Django extractors
# ---------------------------------------------------------------------------

_ALEMBIC_OP_PATTERNS = [
    (r"op\.add_column\(\s*['\"](\w+)['\"]\s*,\s*sa\.Column\(\s*['\"](\w+)['\"]", "add_column"),
    (r"op\.drop_column\(\s*['\"](\w+)['\"]\s*,\s*['\"](\w+)['\"]", "drop_column"),
    (r"op\.alter_column\(\s*['\"](\w+)['\"]\s*,\s*['\"](\w+)['\"][^)]*nullable\s*=\s*False", "set_not_null"),
    (r"op\.alter_column\(\s*['\"](\w+)['\"]\s*,\s*['\"](\w+)['\"][^)]*type_", "alter_column_type"),
    (r"op\.rename_table\(\s*['\"](\w+)['\"]\s*,\s*['\"](\w+)['\"]", "rename_table"),
    (r"op\.drop_table\(\s*['\"](\w+)['\"]", "drop_table"),
    (r"op\.create_table\(\s*['\"](\w+)['\"]", "create_table"),
    (r"op\.create_index\(", "create_index"),
    (r"op\.execute\(\s*['\"](.+?)['\"]\s*\)", "raw_execute"),
]


def parse_alembic(content: str) -> list[SchemaOperation]:
    ops: list[SchemaOperation] = []
    # Prefer embedded SQL in op.execute
    for m in re.finditer(r"op\.execute\(\s*(?:['\"]{1,3})(.+?)(?:['\"]{1,3})\s*\)", content, re.DOTALL):
        ops.extend(parse_sql_ddl(m.group(1)))

    for pattern, op_type in _ALEMBIC_OP_PATTERNS:
        for m in re.finditer(pattern, content, re.DOTALL):
            if op_type == "raw_execute":
                continue
            if op_type in {"add_column", "drop_column", "set_not_null", "alter_column_type"}:
                ops.append(
                    SchemaOperation(
                        op_type=op_type,
                        table=m.group(1),
                        column=m.group(2) if m.lastindex and m.lastindex >= 2 else None,
                        raw_sql=m.group(0),
                    )
                )
            elif op_type == "rename_table":
                ops.append(
                    SchemaOperation(
                        op_type=op_type,
                        table=m.group(1),
                        raw_sql=m.group(0),
                        metadata={"new_name": m.group(2)},
                    )
                )
            elif op_type in {"drop_table", "create_table"}:
                ops.append(SchemaOperation(op_type=op_type, table=m.group(1), raw_sql=m.group(0)))
            else:
                ops.append(SchemaOperation(op_type=op_type, raw_sql=m.group(0)))

    # Also scan upgrade() docstring / comments for SQL blocks
    sql_blocks = re.findall(r"```sql\s*(.+?)```", content, re.DOTALL | re.IGNORECASE)
    for block in sql_blocks:
        ops.extend(parse_sql_ddl(block))

    return ops or [SchemaOperation(op_type="unknown", raw_sql=content[:500])]


def parse_prisma(content: str) -> list[SchemaOperation]:
    """Parse Prisma migrate SQL or schema diffs."""
    if "model " in content and "@@" in content or content.strip().startswith("model "):
        ops: list[SchemaOperation] = []
        for m in re.finditer(r"model\s+(\w+)\s*\{([^}]+)\}", content):
            table = m.group(1)
            fields = []
            for line in m.group(2).splitlines():
                line = line.strip()
                if not line or line.startswith("//") or line.startswith("@@"):
                    continue
                parts = line.split()
                if parts:
                    fields.append(parts[0])
            ops.append(
                SchemaOperation(
                    op_type="create_table",
                    table=table,
                    raw_sql=m.group(0),
                    metadata={"columns": fields, "orm": "prisma"},
                )
            )
        return ops
    return parse_sql_ddl(content)


def parse_django(content: str) -> list[SchemaOperation]:
    ops: list[SchemaOperation] = []
    patterns = [
        (r"migrations\.AddField\(\s*model_name=['\"](\w+)['\"]\s*,\s*name=['\"](\w+)['\"]", "add_column"),
        (r"migrations\.RemoveField\(\s*model_name=['\"](\w+)['\"]\s*,\s*name=['\"](\w+)['\"]", "drop_column"),
        (r"migrations\.AlterField\(\s*model_name=['\"](\w+)['\"]\s*,\s*name=['\"](\w+)['\"]", "alter_column_type"),
        (r"migrations\.RenameField\(\s*model_name=['\"](\w+)['\"]\s*,\s*old_name=['\"](\w+)['\"]", "rename_column"),
        (r"migrations\.DeleteModel\(\s*name=['\"](\w+)['\"]", "drop_table"),
        (r"migrations\.CreateModel\(\s*name=['\"](\w+)['\"]", "create_table"),
        (r"migrations\.RunSQL\(\s*['\"](.+?)['\"]", "raw_execute"),
    ]
    for pattern, op_type in patterns:
        for m in re.finditer(pattern, content, re.DOTALL):
            if op_type == "raw_execute":
                ops.extend(parse_sql_ddl(m.group(1)))
            elif op_type in {"add_column", "drop_column", "alter_column_type", "rename_column"}:
                ops.append(
                    SchemaOperation(
                        op_type=op_type,
                        table=m.group(1),
                        column=m.group(2) if m.lastindex >= 2 else None,
                        raw_sql=m.group(0),
                        metadata={"orm": "django"},
                    )
                )
            else:
                ops.append(
                    SchemaOperation(
                        op_type=op_type,
                        table=m.group(1),
                        raw_sql=m.group(0),
                        metadata={"orm": "django"},
                    )
                )
    return ops or parse_sql_ddl(content)


def detect_source_type(content: str, filename: str | None = None, hint: str | None = None) -> str:
    if hint and hint != "auto":
        return hint
    name = (filename or "").lower()
    if name.endswith(".prisma") or "prisma" in name:
        return "prisma"
    if "alembic" in name or "op.add_column" in content or "op.drop_column" in content:
        return "alembic"
    if "migrations.AddField" in content or "migrations.CreateModel" in content:
        return "django"
    return "sql"


def parse_migration(
    content: str,
    source_type: str = "sql",
    filename: str | None = None,
) -> list[dict[str, Any]]:
    resolved = detect_source_type(content, filename, source_type)
    if resolved == "alembic":
        ops = parse_alembic(content)
    elif resolved == "prisma":
        ops = parse_prisma(content)
    elif resolved == "django":
        ops = parse_django(content)
    else:
        ops = parse_sql_ddl(content)

    # Deduplicate by (op_type, table, column, raw_sql)
    seen: set[tuple] = set()
    unique: list[SchemaOperation] = []
    for op in ops:
        key = (op.op_type, op.table, op.column, op.raw_sql[:200])
        if key in seen:
            continue
        seen.add(key)
        unique.append(op)
    return [op.to_dict() for op in unique]
