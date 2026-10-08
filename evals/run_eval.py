#!/usr/bin/env python3
"""Evaluate deterministic risk rules against sample scenarios."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services.analysis_service import analyze_sync
from app.services.scenarios import default_repo_path, load_scenario_sql


def main() -> int:
    scenarios_path = Path(__file__).parent / "scenarios.json"
    cases = json.loads(scenarios_path.read_text(encoding="utf-8"))
    results = []
    passed = 0
    t0 = time.perf_counter()

    for case in cases:
        sql, scenario = load_scenario_sql(case["id"])
        start = time.perf_counter()
        out = analyze_sync(
            sql,
            source_type=scenario["source_type"],
            filename=scenario["filename"],
            repo_path=str(default_repo_path()),
            title=scenario["title"],
        )
        latency_ms = (time.perf_counter() - start) * 1000
        rule_ids = {f["rule_id"] for f in out["findings"]}
        expected = set(case.get("must_include_rules") or [])
        # For type narrowing, either rule id is OK
        if case["id"] == "type-narrowing":
            rules_ok = bool(rule_ids & expected) if expected else True
        else:
            rules_ok = expected.issubset(rule_ids)

        risk_ok = out["overall_risk"] in case["expected_risk"]
        refs_ok = True
        if "min_code_refs" in case:
            refs_ok = len(out["code_references"]) >= case["min_code_refs"]
        score_ok = True
        if "max_score" in case:
            score_ok = out["overall_score"] <= case["max_score"]

        ok = rules_ok and risk_ok and refs_ok and score_ok
        if ok:
            passed += 1

        results.append(
            {
                "id": case["id"],
                "ok": ok,
                "overall_risk": out["overall_risk"],
                "overall_score": out["overall_score"],
                "rules_fired": sorted(rule_ids),
                "code_refs": len(out["code_references"]),
                "latency_ms": round(latency_ms, 2),
                "checks": {
                    "risk_ok": risk_ok,
                    "rules_ok": rules_ok,
                    "refs_ok": refs_ok,
                    "score_ok": score_ok,
                },
            }
        )
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {case['id']} risk={out['overall_risk']} score={out['overall_score']:.2f}")

    total_ms = (time.perf_counter() - t0) * 1000
    summary = {
        "passed": passed,
        "total": len(cases),
        "accuracy": round(passed / len(cases), 3) if cases else 0,
        "total_latency_ms": round(total_ms, 2),
        "avg_latency_ms": round(total_ms / len(cases), 2) if cases else 0,
        "results": results,
    }
    out_path = Path(__file__).parent / "latest_results.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n{passed}/{len(cases)} passed · avg {summary['avg_latency_ms']}ms")
    print(f"Wrote {out_path}")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
