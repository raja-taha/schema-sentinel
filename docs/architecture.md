# SchemaSentinel architecture

## Proof

> This system analyzes database migrations as software changes — scoring lock, compatibility, and data-loss risk with deterministic rules, then explaining blast radius with an LLM.

## Request flow

```text
PR webhook / Console / API
        │
        ▼
FastAPI (auth via X-API-Key)
        │
        ▼
Migration parser (SQLGlot + Alembic/Prisma/Django extractors)
        │
        ├──► Deterministic risk engine (10 rules)
        ├──► Code reference search (samples/app or repo_path)
        ├──► NetworkX dependency / blast-radius graph
        ├──► Expand → backfill → switch → contract planner
        ├──► Rollback SQL sketch (honest about irreversibility)
        └──► LangGraph reasoner (OpenAI or mock)
                │
                ▼
        Markdown report + optional GitHub PR comment
```

## Components

| Piece | Role |
|---|---|
| `apps/api` | FastAPI orchestration, persistence, analysis pipeline |
| `apps/web` | Next.js reviewer console |
| `services/worker` | Redis queue consumer for async re-analysis |
| `samples/` | Risky migrations + miniature app for blast-radius demos |
| `evals/` | Scenario graders for CI |

## Design choices

1. **Rules before LLM** — severities come only from deterministic rules; the model explains, it does not re-score.
2. **Honest rollbacks** — drops and narrowing type changes are marked irreversible; we never pretend every DDL is undoable.
3. **Synthetic table stats** — lock risk uses seeded row estimates (`users`, `orders`, `payments`, …) so demos work without a prod DB. Optional `TARGET_DATABASE_URL` is reserved for live stats.
4. **Offline-friendly** — `AGENT_MODE=mock` (or empty `OPENAI_API_KEY`) keeps CI and local demos green.

## Data model

- `analyses` — migration input, operations JSON, findings, graph, report, traces
- `table_stats` — row/size metadata for lock scoring
- `audit_logs` — create / complete / fail events
