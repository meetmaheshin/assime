# Deploying AARTH to Railway

The backend is a single Docker service + a Postgres (pgvector) database. Deploy it
once and **every client** — the web PWA and any future native Android/iOS app —
talks to the same HTTPS URL.

## 1. Create the project
1. Railway → **New Project → Deploy from GitHub repo** → pick `meetmaheshin/assime`.
2. Open the created **service → Settings**:
   - **Root Directory:** `backend` (so it builds `backend/Dockerfile`).
   - Railway auto-detects the Dockerfile. No start command needed (the image runs
     `alembic upgrade head` then uvicorn on `$PORT`).

## 2. Add the database (pgvector)
The app needs the `vector` extension. Two options:

**A. Railway Postgres (try first):** service → **+ New → Database → Add PostgreSQL**.
Recent Railway Postgres includes pgvector, and migration `0001` runs
`CREATE EXTENSION IF NOT EXISTS vector` automatically.

**B. If migration fails on the extension:** deploy a pgvector image instead —
**+ New → Empty Service → Deploy from Docker Image** → `pgvector/pgvector:pg16`,
add a **Volume** at `/var/lib/postgresql/data`, and set service variables
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`. Build `DATABASE_URL` from those.

## 3. Environment variables (on the web service)
Set these under the service → **Variables**:

```
ENV=production
SECRET_KEY=<run: python -c "import secrets;print(secrets.token_urlsafe(48))">
DATABASE_URL=${{Postgres.DATABASE_URL}}     # reference the DB service

# LLM (Azure OpenAI)
LLM_PROVIDER=azure
AZURE_OPENAI_API_KEY=<your key>
AZURE_OPENAI_ENDPOINT=https://<resource>.cognitiveservices.azure.com/
AZURE_OPENAI_API_VERSION=2024-12-01-preview
AZURE_DEPLOYMENT_REASONING=gpt-4.1-nano
AZURE_DEPLOYMENT_CHEAP=gpt-4.1-nano

# Embeddings (local ONNX — free, baked into the image)
EMBEDDING_PROVIDER=local
LOCAL_EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBED_DIM=384

# Voice (Cartesia)
CARTESIA_API_KEY=<your key>
CARTESIA_VERSION=2024-11-13
CARTESIA_TTS_MODEL=sonic-2
CARTESIA_STT_MODEL=ink-whisper
CARTESIA_VOICE_ID=f6141af3-5f94-418c-80ed-a45d450e7e2e
```

`DATABASE_URL` may arrive as `postgresql://…`; the app converts it to the async
driver automatically.

## 4. Deploy + get a URL
1. Trigger a deploy (push to `main` or Railway → Deploy).
2. Service → **Settings → Networking → Generate Domain**.
3. Open `https://<your-domain>/` → it redirects to the app. Install it from the
   gear → **Install AARTH** (or Add to Home Screen).

## 5. (Optional) seed a demo account
Service → **⋮ → Run a command** (or Railway CLI `railway run`):
```
python seed.py      # creates demo@aath.app / demo12345
```
Or just register a fresh account in the UI.

## Notes
- **Memory/STT/TTS** all work on the deployed URL over HTTPS (mic + install need
  HTTPS, which Railway provides).
- **Resources:** with ONNX embeddings the image is light; a small instance is
  plenty for ~100 users. Single instance is fine (migrations run at boot).
- **Mobile app later:** point the native app's API base at this same URL. No
  second backend needed.
- **Rotate keys** that were shared during development once you're live.
