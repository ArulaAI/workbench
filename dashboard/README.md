# SPEED Dashboard

Local web app for visualizing `.speed/` data: task DAGs, token burn analytics, codebase topology, spec alignment, and context budgets.

## Architecture

```
SPEED repo (tool)              Target project (user's repo)
├── dashboard/                 ├── .speed/
│   ├── backend/    (Python)   │   ├── dashboard.db     ← SQLite, written by dashboard
│   └── frontend/   (Next.js)  │   ├── features/*/logs/ ← JSONL, read by dashboard
└── speed                      │   ├── context/          ← JSON, read by dashboard
                               │   └── ...
```

The backend reads from the target project's `.speed/` directory. Each project gets its own SQLite DB at `.speed/dashboard.db`.

## Quick Start

```bash
# From a SPEED-initialized project:
speed dashboard start

# API only (no frontend):
speed dashboard start --api-only

# Custom port:
speed dashboard start --port 5000

# Custom frontend port (useful when another project already uses 3000):
speed dashboard start --frontend-port 3001

# Stop everything:
speed dashboard stop
```

The API serves at `http://localhost:4440/graphql` (GraphiQL explorer included). The frontend serves at `http://localhost:3000` by default. The same defaults can be configured with `SPEED_DASHBOARD_PORT` and `SPEED_DASHBOARD_FRONTEND_PORT`.

Each launched frontend uses a build cache isolated by its API and frontend ports. If the requested frontend port is already occupied, startup leaves the API running and asks you to stop the existing frontend or choose `--frontend-port`; it does not attach the new project to an unrelated dev server.

## Manual Setup

### Backend

Requires Python 3.10+ with these packages (installed via `requirements.txt`):

```bash
cd /path/to/speed
pip install -r requirements.txt

# Start the API server:
PYTHONPATH=. python -m dashboard.backend --port 4440 --project-root /path/to/target-project
```

### Frontend

Requires Node.js 18+.

```bash
cd dashboard/frontend
npm install
npm run dev
```

Configure the API URL in `.env.local` (defaults to `http://127.0.0.1:4440/graphql`).

## Views

| View | Route | Data Source |
|---|---|---|
| Mission Control | `/mission-control` | `tasks/*.json`, `state.json` |
| Codebase Topology | `/topology` | `semantic-graph.json` |
| Spec Alignment | `/spec-alignment` | `spec-alignment.json` |
| Context Budget | `/budget` | `context/tasks/*/context/budget.json` |
| Token Burn Analytics | `/analytics` | JSONL agent logs (ingested into SQLite) |

## GraphQL API

Eight query fields, three subscription channels.

**Queries** (test in GraphiQL at `/graphql`):

```graphql
# List features
{ features { name status taskCount } }

# Token burn by agent type
{ tokenBurnAggregate(groupBy: AGENT_TYPE) { groupKey totalCostUsd runCount } }

# Topology stats
{ codebaseTopology { nodeCount edgeCount clusterCount } }

# Mission control for a feature
{ missionControl(feature: "speed-security") { taskCount statusCounts { done running failed pending } } }

# Spec alignment coverage
{ specAlignment { totalClaims overallCoveragePct } }

# Context budget utilization
{ contextBudget { summary { taskCount utilizationPct totalCuts } } }
```

**Subscriptions** (WebSocket):

| Channel | Fires when |
|---|---|
| `taskStatusChanged(feature)` | Task status changes |
| `agentRunCompleted(feature?)` | New JSONL result event ingested |
| `costAccumulation(feature?)` | Every 5s with cumulative cost |

## Tech Stack

| Layer | Choice |
|---|---|
| Database | SQLite (WAL mode, one per target project) |
| API | FastAPI + Strawberry GraphQL |
| Live updates | GraphQL subscriptions via WebSocket |
| Frontend | Next.js 15 (App Router) |
| Graph visualization | React Flow |
| Charts | Recharts |
| Styling | Tailwind CSS |

## Ingestion

On startup, the backend:

1. Creates/migrates the SQLite schema
2. Registers the project (name, git remote, HEAD)
3. Backfills all existing `.speed/features/*/logs/*.jsonl` files
4. Starts a file watcher for live incremental ingestion

Run backfill without starting the server:

```bash
speed dashboard ingest
```

## File Structure

```
dashboard/
├── backend/
│   ├── app.py              # FastAPI app, CORS, lifespan
│   ├── cli.py              # --port, --project-root
│   ├── db.py               # SQLite schema, connection, migrations
│   ├── ingest.py           # JSONL parsing, backfill, file watcher
│   ├── schema.py           # Strawberry types, Query, Subscription
│   ├── subscriptions.py    # Async event fan-out
│   └── resolvers/
│       ├── token_burn.py       # SQL aggregation queries
│       ├── mission_control.py  # Task JSON + state composition
│       ├── topology.py         # semantic-graph.json → clusters
│       ├── spec_alignment.py   # Claims + coverage computation
│       └── budget.py           # Per-task budget reading
├── frontend/
│   ├── app/                    # 5 view pages
│   ├── components/             # Layout + shared + per-view
│   ├── lib/graphql/            # urql client + queries
│   └── lib/utils/              # Formatters, colors, cn
└── README.md
```
