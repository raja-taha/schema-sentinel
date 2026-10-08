from typing import Any, TypedDict


class ReasonerState(TypedDict, total=False):
    title: str
    operations: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    code_references: list[dict[str, Any]]
    overall_risk: str
    overall_score: float
    stats_meta: dict[str, Any]
    explanation: str
    trace: list[dict[str, Any]]
