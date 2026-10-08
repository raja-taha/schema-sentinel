#!/usr/bin/env python3
"""Run a demo analysis against the live API (or sync fallback)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def main() -> int:
    parser = argparse.ArgumentParser(description="SchemaSentinel demo seeder")
    parser.add_argument(
        "scenario_id",
        nargs="?",
        default="drop-not-null-users",
        help="Scenario id from /api/v1/scenarios",
    )
    parser.add_argument("--base-url", default=os.getenv("NEXT_PUBLIC_API_URL", "http://localhost:8000"))
    parser.add_argument("--api-key", default=os.getenv("API_KEY", "change-me-to-a-strong-secret"))
    parser.add_argument("--sync", action="store_true", help="Run offline sync pipeline (no API)")
    args = parser.parse_args()

    if args.sync:
        from app.services.analysis_service import analyze_sync
        from app.services.scenarios import default_repo_path, load_scenario_sql

        sql, scenario = load_scenario_sql(args.scenario_id)
        result = analyze_sync(
            sql,
            source_type=scenario["source_type"],
            filename=scenario["filename"],
            repo_path=str(default_repo_path()),
            title=scenario["title"],
        )
        print(json.dumps({
            "title": scenario["title"],
            "overall_risk": result["overall_risk"],
            "overall_score": result["overall_score"],
            "findings": len(result["findings"]),
            "code_refs": len(result["code_references"]),
        }, indent=2))
        print("\n--- Report preview ---\n")
        print(result["markdown_report"][:2000])
        return 0

    headers = {"X-API-Key": args.api_key}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=60) as client:
        resp = client.post(
            "/api/v1/analyses",
            json={"scenario_id": args.scenario_id, "auto_analyze": True},
        )
        resp.raise_for_status()
        data = resp.json()
        print(json.dumps({
            "id": data["id"],
            "title": data["title"],
            "status": data["status"],
            "overall_risk": data["overall_risk"],
            "overall_score": data["overall_score"],
            "findings": len(data.get("risk_findings") or []),
        }, indent=2))
        print(f"\nOpen console: http://localhost:3000/analyses/{data['id']}")
        print(f"API detail:   {args.base_url}/api/v1/analyses/{data['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
