"""Build table/column dependency graphs with NetworkX."""

from __future__ import annotations

from typing import Any

import networkx as nx


def build_dependency_graph(
    operations: list[dict[str, Any]],
    code_references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    g = nx.DiGraph()

    for op in operations:
        table = op.get("table")
        if not table:
            continue
        node = f"table:{table}"
        g.add_node(node, kind="table", name=table)
        col = op.get("column")
        if col:
            col_node = f"column:{table}.{col}"
            g.add_node(col_node, kind="column", name=col, table=table)
            g.add_edge(node, col_node, relation="has_column")

        op_node = f"op:{op.get('op_type')}:{table}:{col or ''}"
        g.add_node(
            op_node,
            kind="operation",
            op_type=op.get("op_type"),
            table=table,
            column=col,
        )
        g.add_edge(op_node, node, relation="affects")
        if col:
            g.add_edge(op_node, f"column:{table}.{col}", relation="affects")

        ref = op.get("referenced_table")
        if ref:
            ref_node = f"table:{ref}"
            g.add_node(ref_node, kind="table", name=ref)
            g.add_edge(node, ref_node, relation="references")

    for ref in code_references or []:
        path = ref.get("path") or ref.get("file")
        symbol = ref.get("symbol") or ref.get("match")
        table = ref.get("table")
        if not path:
            continue
        code_node = f"code:{path}"
        g.add_node(code_node, kind="code", path=path, symbol=symbol)
        if table:
            table_node = f"table:{table}"
            if table_node not in g:
                g.add_node(table_node, kind="table", name=table)
            g.add_edge(code_node, table_node, relation="references")
            col = ref.get("column")
            if col:
                col_node = f"column:{table}.{col}"
                if col_node not in g:
                    g.add_node(col_node, kind="column", name=col, table=table)
                g.add_edge(code_node, col_node, relation="references")

    # Blast radius: dependents of each affected table
    blast: dict[str, Any] = {}
    for node, data in g.nodes(data=True):
        if data.get("kind") != "table":
            continue
        downstream = []
        for _, tgt, edata in g.out_edges(node, data=True):
            downstream.append({"node": tgt, "relation": edata.get("relation")})
        upstream_code = [
            src for src, _, edata in g.in_edges(node, data=True) if str(src).startswith("code:")
        ]
        blast[data["name"]] = {
            "downstream": downstream,
            "code_refs": upstream_code,
            "degree": g.degree(node),
        }

    return {
        "nodes": [
            {"id": n, **{k: v for k, v in attrs.items()}} for n, attrs in g.nodes(data=True)
        ],
        "edges": [
            {"source": u, "target": v, **attrs} for u, v, attrs in g.edges(data=True)
        ],
        "blast_radius": blast,
        "stats": {
            "node_count": g.number_of_nodes(),
            "edge_count": g.number_of_edges(),
            "tables": len([n for n, d in g.nodes(data=True) if d.get("kind") == "table"]),
            "code_files": len([n for n, d in g.nodes(data=True) if d.get("kind") == "code"]),
        },
    }
