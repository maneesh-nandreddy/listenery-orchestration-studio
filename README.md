# Listenery Event Trigger Engine

The engine between an incoming product event and an outgoing interview send.
Given `{event_name, user_id, ...}`, it matches the event against a client's
rules, schedules a delayed send, deterministically samples which users get
included, deduplicates repeat sends, and fires a (stubbed) interview send
when the dispatch comes due.

Out of scope, by design: interview question generation, the AI interview
conversation itself, transcripts, and any real email/SMS provider. See
`NOTES.md` for the reasoning behind the bigger design choices.

## Key Architectural Highlights

*   **Resilient Scheduling**: Dispatch state is kept in Postgres (`due_at` timestamp) rather than in Celery ETAs, avoiding data loss if the Celery/Redis container restarts.
*   **Deterministic Sampling**: Built using SHA-256 hash modular mapping rather than Python's built-in `hash()`, guaranteeing identical sampling decisions across process restarts.
*   **Horizontal Scalability**: Employs `FOR UPDATE SKIP LOCKED` database queries on due dispatches, enabling multiple worker instances to query the queue simultaneously without double-sending.
*   **Tenant Isolation**: Standardized client-scoping on all rules, events, and deduplication logic, preventing cross-tenant suppression or leakage.
*   **Interactive Orchestration Studio**: Frontend dashboard with real-time stream sync, visual status chips, toast alerts, and a **Decision Trail** walkthrough panel.

## Stack

- **FastAPI** for the ingest/admin HTTP API.
- **PostgreSQL** for all durable state — clients, rules, events, dispatches.
- **Celery** (broker: Redis) for background processing: matching new events
  into dispatches, and a periodic beat task that polls for due dispatches.
- **Alembic** for schema migrations.
- **Docker Compose** to run all of it with one command.

## Running it

Prerequisites: Docker and Docker Compose.

### Start the Application Stack
```bash
docker compose up --build
```

This brings up, in order: Postgres, Redis, a one-shot `migrate` service
(runs `alembic upgrade head`), the API, a Celery worker, and Celery beat.

*   **Studio Dashboard & API**: [http://localhost:8000](http://localhost:8000)
*   **Postgres**: exposed on host port **5433** (container-internal port is standard 5432; only the host mapping was moved to avoid clashing with a host Postgres).
*   **Redis**: exposed on host port **6380** (container-internal 6379, same reasoning).

Services talk to each other over the Docker network using the standard
ports, so this only matters if you want to connect to Postgres/Redis from
your host machine directly (e.g. `psql -h localhost -p 5433`).

### Monitor Logs
```bash
# View worker logs
docker compose logs -f worker

# View all container logs
docker compose logs -f
```

## Exercising the system

There's no auth-protected admin UI — two unauthenticated `/admin/*` endpoints,
a seed script, and a small visual demo page exist purely so you can drive the
system from the outside without hand-editing the database. Pick whichever is
more convenient.

### Option 0: the demo UI

Open **http://localhost:8000/** (served from `app/static/`). Click **Seed
Workspace** to get an API key, then click **Simulate** on a persona card (or
use the Custom Event Dispatcher) to fire an event. The Live Empathy Stream
polls `/dispatches` every 2 seconds and shows exactly what happened —
sent, pending, sampled out, or suppressed as a duplicate. Click any stream
item to open the Decision Trail panel, which walks through the same
match → sample → dedup → dispatch pipeline `process_event` actually ran,
using the dispatch's real stored fields (not a mock).

This is a demo/QA tool, not a deliverable UI for Listenery customers — it
has no auth of its own beyond the API key you paste in, and talks to the same
`/events`, `/admin/seed`, and `/dispatches` endpoints described below.

### Option A: seed script

```bash
docker compose exec api python -m app.admin.seed
```

Prints a `client_id`, `api_key`, and two rule IDs:
- `user_churned` → immediate send, 100% sample, 24h dedup window
- `feature_tried` → 24h delayed send, 20% sample, 30-day dedup window

### Option B: admin endpoints

```bash
# create a client
curl -s -X POST localhost:8000/admin/clients -H 'Content-Type: application/json' \
  -d '{"name": "Acme Inc"}'
# => {"id": "...", "name": "Acme Inc", "api_key": "..."}

# create a rule (immediate send, 100% sample, 1-day dedup window)
curl -s -X POST localhost:8000/admin/rules -H 'Content-Type: application/json' \
  -d '{
    "client_id": "<client id from above>",
    "event_name": "user_churned",
    "interview_id": "interview_churn_v1",
    "delay_seconds": 0,
    "sample_percent": 100,
    "dedup_window_seconds": 86400
  }'
```

### Send an event and watch a dispatch happen

```bash
curl -s -X POST localhost:8000/events \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "event_name": "user_churned",
    "user_id": "user_123",
    "email": "user123@example.com",
    "properties": {"plan": "pro"},
    "timestamp": "2026-08-14T10:00:00Z"
  }'
# => 202 {"event_id": "...", "status": "accepted"}
```

Within a couple of seconds the worker matches this against the rule, and
(since `delay_seconds` is 0 and the timestamp is in the past) the next beat
tick fires the send. Check what happened:

```bash
curl -s "localhost:8000/dispatches?user_id=user_123" -H "Authorization: Bearer <api_key>"
```

You'll see a `Dispatch` row with `status: "sent"`. Look at the worker
container logs (`docker compose logs worker`) to see the structured
`send_interview` payload the stub logged instead of actually emailing/texting
anyone.

To see **sampling** in action, send several `feature_tried` events for
different `user_id`s — roughly 20% will get a `pending`/`sent` dispatch and
the rest will land as `skipped_sampled_out`.

To see **dedup** in action, send the same `event_name` + `user_id` twice
within the rule's `dedup_window_seconds` — the second one becomes a
`Dispatch` row with `status: "skipped_duplicate"` and a `skip_reason`
pointing at the dispatch it collided with.

## Running tests

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest tests/ -v
```

Tests cover the sampling function and the dedup logic in isolation (no
database required for either) — see `app/sampling.py` and `app/dedup.py`,
and `tests/test_sampling.py` / `tests/test_dedup.py`.

## API surface

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /events` | `Authorization: Bearer <api_key>` | Ingest an event. Validates, persists, enqueues, returns 202. No matching/sampling/dedup logic runs on this path. |
| `POST /admin/clients` | none | Create a client, get back an `api_key`. Local demo convenience only. |
| `POST /admin/rules` | none | Create a rule for a client. Local demo convenience only. |
| `POST /admin/seed` | none | Create a demo client with the two seed rules in one call; powers the "Seed Workspace" button in the demo UI. |
| `GET /dispatches?user_id=...` | `Authorization: Bearer <api_key>` | Inspect dispatches for the authenticated client, optionally filtered by user. For demo/debugging. |
| `GET /` , `GET /demo` | none | Serves the visual demo UI (`app/static/index.html`). |

## Project layout

```
app/
  main.py            FastAPI app: /events, /admin/*, /dispatches
  config.py          env-driven settings
  db.py              SQLAlchemy engine/session
  models.py          Client, Rule, Event, Dispatch
  schemas.py         Pydantic request/response models
  auth.py            API-key -> Client lookup
  sampling.py         pure, unit-tested sampling function
  dedup.py            pure, unit-tested dedup-matching function
  sender.py           Sender protocol + LoggingSender stub
  worker/
    celery_app.py     Celery app + beat schedule
    tasks.py          process_event (match/sample/dedup), dispatch_due (poll + send)
  admin/
    seed.py           local demo data
  static/             demo UI (index.html + dashboard.js), served at GET /
alembic/              migrations
tests/
  test_sampling.py
  test_dedup.py
docker-compose.yml
Dockerfile
```
