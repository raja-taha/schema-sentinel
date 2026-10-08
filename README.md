# SchemaSentinel

**Database Migration Risk Analyzer** — treats schema changes like software changes: parse SQL/ORM migrations, score lock / compatibility / data-loss risk, map blast radius across application code, and produce expand→backfill→switch→contract rollout guidance with honest rollback sketches.

> **Proof:** This system analyzes database migrations as software changes — scoring lock, compatibility, and data-loss risk with **deterministic rules**, then explaining blast radius with an LLM (which never overrides severity).

---

## Demo

![SchemaSentinel console](docs/screenshots/console.svg)

| Screen | What it proves |
|---|---|
| Analyze workspace | Scenario or pasted SQL → full risk pipeline in one click |
| Findings panel | Rule IDs, severity, reversibility, lock/data-loss categories |
| Graph view | Table/column/code dependency blast radius |
| Rollout + rollback | Phased migration plan + SQL sketch that admits irreversibility |

> Add real PNG/GIF captures under `docs/screenshots/` after your first local run (`console.png`, `findings.gif`, `graph.png`).

---

## Architecture

```text
PR webhook / Next.js console
        │
        ▼
FastAPI orchestration API
        │
        ▼
parse → risk rules → code search → NetworkX graph
        → rollout/rollback → LangGraph reasoner → Markdown report
        │
        ├── PostgreSQL (analyses, table_stats, audit)
        ├── Redis (progress + worker queue)
        └── Optional GitHub PR comment
```

![Architecture](docs/architecture.png.svg)

Full write-up: [`docs/architecture.md`](docs/architecture.md)

---

## Hard engineering problems

1. **Reliable multi-format parsing** — SQLGlot for PostgreSQL DDL plus extractors for Alembic / Prisma / Django so the same risk engine sees structured operations.
2. **Backward-compatible vs contract-breaking** — ten deterministic rules separate additive expands from NOT NULL, drops, renames, type narrowing, and blocking indexes.
3. **Lock risk with table-size metadata** — synthetic (or live) row estimates scale index/FK/NOT NULL scores instead of treating every table equally.
4. **Honest rollback advice** — generated SQL marks DROP / narrowing type changes as non-auto-reversible; we do not pretend every migration is undoable.

---

## Evaluation

| Metric | Dataset | Current result |
|---|---|---|
| Risk-rule scenario accuracy | 6 migrations (`evals/scenarios.json`) | **100% (6/6)**, ~152ms avg latency |

```bash
python evals/run_eval.py
# writes evals/latest_results.json
```

Offline sync demo (no Docker required for the core pipeline):

```bash
python scripts/seed_demo.py drop-column-orders --sync
```

---

## Safety & reliability

- API key auth on workspace routes (`X-API-Key`)
- GitHub webhook HMAC verification when `GITHUB_WEBHOOK_SECRET` is set
- Deterministic severities — LLM explanation cannot raise/lower rule scores
- Audit trail (`audit_logs`) for create / complete / fail
- Agent traces persisted on each analysis
- OpenAI optional — mock reasoner keeps demos and CI green
- Known limitation: live `TARGET_DATABASE_URL` stats and full PR file fetch are stubs; synthetic stats + sample app code are the supported happy path

---

## Run locally

### Prerequisites

- Docker + Docker Compose (Postgres + Redis + API + worker + web)
- Python 3.12+ with a `venv` inside `apps/api` for local API / tests
- Node 20+ for the Next.js console
- (Optional) `OPENAI_API_KEY` for live LLM explanations

### 1. Configure environment

```bash
cp .env.example .env
# fill in secrets — at minimum set API_KEY (and matching NEXT_PUBLIC_API_KEY)
```

| Variable | Purpose |
|---|---|
| `API_KEY` / `NEXT_PUBLIC_API_KEY` | Shared API auth |
| `DATABASE_URL` | App DB (host port **5434** by default) |
| `REDIS_URL` | Progress + worker queue (host port **6380**) |
| `OPENAI_API_KEY` | Optional live reasoner |
| `AGENT_MODE` | `auto` \| `openai` \| `mock` |
| `GITHUB_TOKEN` / `GITHUB_WEBHOOK_SECRET` | Optional PR comments |

### 2. Start the stack

```bash
docker compose up --build
```

| Service | URL |
|---|---|
| Web console | http://localhost:3000 |
| API + OpenAPI docs | http://localhost:8000/docs |
| Postgres | `localhost:5434` |
| Redis | `localhost:6380` |

### 3. Run a demo analysis

1. Open the console → pick **Add NOT NULL email without default**
2. Click **Run risk analysis**
3. Review findings, graph, code refs, rollout phases, rollback SQL
4. Compare rule output with the LLM explanation panel

CLI alternative (API must be up):

```bash
python scripts/seed_demo.py drop-not-null-users
```

### Local API without Docker app containers

```bash
# terminals: docker compose up db redis
cd apps/api
python -m venv venv
# Windows: .\venv\Scripts\activate
pip install -r requirements.txt
python -m app.db.seed
uvicorn app.main:app --reload --port 8000

# another terminal
cd apps/web && npm install && npm run dev
```

---

## API examples

```bash
# Health
curl http://localhost:8000/api/v1/health

# Analyze a built-in risky scenario
curl -X POST http://localhost:8000/api/v1/analyses \
  -H "X-API-Key: change-me-to-a-strong-secret" \
  -H "Content-Type: application/json" \
  -d "{\"scenario_id\":\"drop-column-orders\",\"auto_analyze\":true}"
```

Postman: import [`postman/SchemaSentinel.postman_collection.json`](postman/SchemaSentinel.postman_collection.json) and [`postman/SchemaSentinel.postman_environment.json`](postman/SchemaSentinel.postman_environment.json).

---

## Repository layout

```text
schema-sentinel/
├── apps/api/                 # FastAPI + analysis engine
├── apps/web/                 # Next.js reviewer console
├── services/worker/          # Redis queue consumer
├── samples/migrations/       # Risky + safe migration fixtures
├── samples/app_code/         # Miniature app for blast-radius search
├── evals/                    # Scenario graders
├── tests/                    # Unit + pipeline tests
├── postman/                  # API collection + local env
├── docs/                     # Architecture + screenshots
├── docker-compose.yml
└── .env.example
```

---

## Deterministic risk rules (10)

| ID | Signal |
|---|---|
| R01 | Drop table |
| R02 | Drop column |
| R03 | SET NOT NULL |
| R04 | ADD NOT NULL without DEFAULT |
| R05 | Type change / narrowing |
| R06 | Rename column |
| R07 | Rename table |
| R08 | Index without `CONCURRENTLY` |
| R09 | Add foreign key (lock / NOT VALID) |
| R10 | Volatile DEFAULT on add column |

---

## Tradeoffs

- **No Neo4j** — NetworkX in-process is enough for MVP blast radius and keeps Docker light.
- **Regex + SQLGlot, not full tree-sitter** — covers the portfolio signal for ORM/SQL parsing without native grammar packaging pain on Windows.
- **GitHub PR file fetch** — webhook demo accepts inline `migration_sql`; production would list PR files via the GitHub API.
- **Frontend is a reviewer console**, not a design-system playground — time went into the parser/rules/graph path.

---

## Roadmap

- Live `pg_stat` / table size ingestion via `TARGET_DATABASE_URL`
- Query-log impact hints (which endpoints hit affected tables most)
- Shadow migration dry-run against a clone database
- Schema-version compatibility simulation across N app releases

---

## Makefile shortcuts

```bash
make up       # docker compose up --build
make test     # pytest tests -q
make eval     # python evals/run_eval.py
make seed     # demo via API
```

## License

MIT — use freely in portfolio and production experiments.
