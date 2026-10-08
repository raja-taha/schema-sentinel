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
3. **Live table stats** — when `TARGET_DATABASE_URL` is set, lock risk uses `pg_class` row estimates + relation sizes; falls back to synthetic defaults on failure.
4. **Offline-friendly evals** — CI/evals force mock LLM + synthetic stats so they stay deterministic without network.
5. **GitHub PR fetch** — webhook lists PR files via the GitHub API, downloads migration contents, analyzes, then comments + creates a check run.

## Data model

- `analyses` — migration input, operations JSON, findings, graph, report, traces
- `table_stats` — row/size metadata for lock scoring
- `audit_logs` — create / complete / fail events
