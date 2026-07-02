# A.A.T.H Backend

FastAPI + PostgreSQL (pgvector) + Redis backend for **A.A.T.H** (Artificial
Assistant To Human), an AI Personal Assistant. Implements the MVP v1 core: multi-user auth, tasks/projects,
semantic memory, duplicate detection, and a retrieve-then-generate chat endpoint.

See [`../assime_prd_v2.md`](../assime_prd_v2.md) for the full product spec.

## Stack
- **FastAPI** (async) — REST API
- **PostgreSQL 16 + pgvector** — structured data + semantic memory
- **Redis** — cache / rate-limit (wired in config; used more in later phases)
- **SQLAlchemy 2.0 async + Alembic** — ORM + migrations
- **OpenAI** — two-tier model strategy behind a swappable `LLMClient`

## Prerequisites
- Python 3.12+
- Docker (for Postgres + Redis)

## Setup

```bash
cd backend

# 1. Start Postgres (pgvector) + Redis
docker compose up -d

# 2. Create a virtualenv and install deps
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS/Linux
pip install -r requirements.txt

# 3. Configure env
copy .env.example .env            # Windows  (cp on macOS/Linux)
# Edit .env: set SECRET_KEY, and OPENAI_API_KEY if you want real AI.
# Without a key the app boots and uses a clearly-labelled stub LLM so
# auth/CRUD/memory tables all work offline.

# 4. Run migrations (creates pgvector extension + all tables)
alembic upgrade head

# 5. Run the API
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs for interactive API docs.

## Quick smoke test
```bash
# Register (returns a bearer token)
curl -X POST localhost:8000/auth/register -H "Content-Type: application/json" \
  -d '{"email":"me@example.com","password":"supersecret","display_name":"Mahesh"}'

# Use the token for everything else:
#   Authorization: Bearer <access_token>
```

## Layout
```
app/
  core/        config, database (async), security (jwt + bcrypt)
  models/      SQLAlchemy ORM (User, Project, Task, Memory[pgvector], ...)
  schemas/     Pydantic request/response models
  services/    llm (OpenAI client), memory_service (embed + search + dedupe)
  api/routes/  auth, projects, tasks, chat
  main.py      app factory
alembic/       migrations (0001 = initial schema + pgvector)
```

## Endpoints (MVP)
| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register` `/auth/login` | multi-user auth |
| GET/PATCH | `/auth/me` `/auth/me/settings` | profile + timezone/quiet hours |
| CRUD | `/projects` | user-scoped projects |
| CRUD | `/tasks` | tasks (+ duplicate detection on create) |
| POST | `/tasks/{id}/complete` | explicit completion (never assumed) |
| POST | `/tasks/{id}/overdue-reason` | accountability reason capture |
| POST | `/chat` | retrieve-then-generate assistant reply |
| POST | `/memory/search` | semantic search over your memory |

## Notes
- **Retrieve-then-generate:** `/chat` embeds the message, pulls the most relevant
  memories, and grounds the reply in them. No relevant memory → it says so and
  asks, rather than hallucinating.
- **Model choice is config, not code** (`.env`). Swap GPT versions freely; verify
  exact model IDs against current OpenAI docs.
- **Not yet built (later phases):** scheduling/briefings, notifications, offline
  sync endpoint, weekly/monthly reviews. See PRD §16.
