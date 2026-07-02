# Project: A.A.T.H — AI Personal Assistant

> **A.A.T.H** = *Artificial Assistant To Human*

**Version:** 2.0 (engineering-ready)
**Supersedes:** `assime_prd.txt` (v1.0 — vision doc)
**Status:** Draft for build
**Owner:** Mahesh

> This version keeps the original vision intact and adds the missing engineering
> decisions: memory/retrieval architecture, AI model choice, voice pipeline,
> proactivity engine, security/privacy, sync strategy, phased milestones, and a
> concrete MVP v1 scope. Sections marked **[NEW]** were not in v1. Sections marked
> **[GAP → RESOLVED]** close a hole that would have bitten us mid-build.

---

## 1. Vision (unchanged from v1)

Build an **Android-first AI Personal Assistant** that behaves like a real executive
assistant, not a chatbot or to-do app. It should:

- Remember everything the user has committed to.
- Keep the user accountable and ask follow-up questions.
- Learn from previous conversations and reference past work.
- Prevent duplicate work; understand **projects**, not isolated tasks.
- Be proactive, not reactive. Feel like A.A.T.H.
- Get smarter every day because its memory grows.

**North-star:** *"I never forget anything anymore, and someone is keeping me accountable."*

---

## 2. Core Philosophy (unchanged)

Traditional to-do: create → remind → complete → forgotten.
A.A.T.H: create → understand **why** → remember forever → follow up → learn →
reference past work → become a long-term assistant.

---

## 3. Guiding Principles [NEW]

These are the rules every feature and PR must respect.

1. **Local-first for the cheap stuff.** Reminders, alarms, timers, notifications
   run on-device (WorkManager). No network, no AI, no cost.
2. **AI only when reasoning is required.** Planning, reflection, memory search,
   task breakdown, coaching, reviews. Everything else is deterministic code.
3. **Retrieve before you generate.** Never let the model answer from nothing —
   always pull relevant memory first, then reason over it. This is how we keep
   the "never hallucinate" promise.
4. **Confirm, don't assume.** Never mark work complete or duplicate a task
   without user confirmation.
5. **Offline must degrade gracefully.** The app is usable on a train with no
   signal: view tasks, add tasks, get local reminders. AI features queue.
6. **Privacy is a feature.** This is the user's second brain. Treat every note,
   key, and client conversation as confidential by default.
7. **Never spam.** Notification budget is enforced in code, not left to the model.

---

## 4. Target Platform (unchanged, with detail)

| Layer | Choice |
|---|---|
| OS | Android (min SDK 26 / Android 8.0, target latest) |
| UI | Jetpack Compose + Material 3 |
| Language | Kotlin |
| Theme | Dark mode first, light mode supported |
| Interaction | Voice-first, chat-driven, minimal forms |

---

## 5. Tech Stack (locked) [GAP → RESOLVED]

### 5.1 Android client
- **UI:** Jetpack Compose, Material 3, Compose Navigation
- **Architecture:** Clean Architecture + MVVM, Repository pattern
- **DI:** Hilt
- **Async:** Coroutines + Flow
- **Local DB / offline cache:** Room
- **Background work:** WorkManager (reminders, sync, briefing triggers)
- **Networking:** Retrofit + OkHttp + Kotlinx Serialization (or Moshi)
- **Realtime (optional):** OkHttp WebSocket for live chat streaming
- **Push:** Firebase Cloud Messaging (FCM)
- **Auth on device:** Firebase Auth SDK (token) + BiometricPrompt to unlock app
- **Voice:** Android `SpeechRecognizer` (STT) + `TextToSpeech` (TTS) for MVP

### 5.2 Backend
- **Framework:** FastAPI (Python 3.12+), REST + optional WebSocket
- **DB:** PostgreSQL 16
- **Vector search:** **`pgvector`** extension on the same Postgres [GAP → RESOLVED]
  — no separate vector DB needed for v1; keeps ops simple.
- **Cache / queues / rate-limit:** Redis
- **Background jobs:** Celery (or APScheduler for v1) for briefings, reviews,
  follow-up scheduling
- **Push fan-out:** Firebase Admin SDK → FCM
- **Migrations:** Alembic
- **Validation:** Pydantic v2

### 5.3 AI layer [GAP → RESOLVED — v1 named a non-existent "GPT-5.5"]
Provider: **OpenAI** (per your call). Use a two-tier model strategy so we don't
pay premium prices for cheap tasks:

| Task | Tier | Suggested model* |
|---|---|---|
| Intent parsing, classification, duplicate check, tag extraction | **Cheap/fast** | `gpt-4o-mini` (or `gpt-4.1-mini`) |
| Planning, coaching, weekly/monthly review, task breakdown, memory synthesis | **Reasoning** | `gpt-4o` / `gpt-4.1` (or an `o`-series reasoning model for reviews) |
| Embeddings for memory search | **Embeddings** | `text-embedding-3-small` (1536-d) |

\* Pin exact model IDs in config, not in code. The provider/model is swappable
behind an `LLMClient` interface so we can change GPT versions (or providers)
without touching feature code. **Verify the exact current model IDs and pricing
in the OpenAI docs at build time — do not hardcode from memory.**

**Cost controls:** cache embeddings, cache system prompts, batch where possible,
set per-user daily token budgets in Redis, and always retrieve-then-generate to
keep prompts small.

---

## 6. Memory & Retrieval Architecture [NEW — biggest missing piece in v1]

This is the technical heart of the product. "Remembers forever" + "memory search"
+ "duplicate detection" all depend on it.

### 6.1 What we store
- **Structured memory** (Postgres tables): tasks, projects, people, meetings,
  notes, decisions, files, reminders — the facts.
- **Semantic memory** (`pgvector`): every meaningful item (task, note, decision,
  meeting summary, chat turn worth remembering) is embedded and stored with a
  vector + metadata (type, project_id, person_id, created_at, source).

### 6.2 Write path (how memory grows)
1. User speaks/types → intent parsed (cheap model).
2. Structured record written to Postgres.
3. A short canonical text ("memory chunk") is generated and embedded.
4. Embedding + metadata stored in the `memories` table (`pgvector`).

### 6.3 Read path (retrieve-before-generate)
1. Query embedded → top-K semantic search over `pgvector`, filtered by metadata
   (e.g., project, recency).
2. Optionally re-rank / dedupe.
3. Relevant chunks + structured facts injected into the prompt.
4. Reasoning model answers **only** from retrieved context; if nothing relevant,
   it says so and asks the user (no hallucination).

### 6.4 Duplicate detection (uses the same pipeline)
On new task creation → embed the title/description → semantic search existing
tasks → if similarity > threshold, ask: *same / new / follow-up?* Never blindly
duplicate.

### 6.5 Memory hygiene [NEW]
- **Decay/summarization:** old chat turns get summarized into durable memory,
  raw turns pruned. Keeps retrieval sharp and storage bounded.
- **Confidence + source** stored on every memory so the assistant can cite where
  a fact came from.

---

## 7. Voice Pipeline [GAP → RESOLVED — v1 said "voice-first" with no spec]

- **MVP:** on-device `SpeechRecognizer` (STT) + `TextToSpeech` (TTS). Free, works
  offline-ish, no extra cost. Push-to-talk button (no wake word in v1).
- **Phase 3+:** optional cloud STT (e.g., Whisper) for higher accuracy; optional
  wake word ("Hey A.A.T.H") via a lightweight on-device keyword spotter.
- **Fallback:** every voice action has a typed/tap equivalent. Voice is a layer,
  never the only path.
- **Voice commands v1:** add task, mark complete, move to tomorrow, cancel
  reminder, "what's next", "summarize my day".

---

## 8. Proactivity & Scheduling Engine [GAP → RESOLVED]

The brains behind briefings, reviews, and nudges.

### 8.1 Triggers
- **Time-based** (morning brief, lunch check, evening review): server-side
  scheduled jobs (Celery/APScheduler) computed **per user timezone**, delivered
  via FCM. WorkManager handles the on-device fallback if push is unavailable.
- **Event-based** (task overdue, deadline today, project stalled): evaluated when
  data changes or on a periodic sweep.

### 8.2 Adaptive frequency ("never spam") [NEW]
- A **notification budget** per user per day, enforced in Redis.
- Priority ordering: overdue/blocking > deadline-today > brief/review > nudges.
- If the user ignores a nudge type repeatedly, back off automatically.
- Quiet hours respected (configurable, default 22:00–07:00 local).

### 8.3 Morning Briefing / Evening Review / Accountability
Behaviour identical to v1 (§Morning Briefing, §Evening Review, §Accountability),
now with concrete triggers and timezone handling. Overdue flow stores a
structured reason: `blocked / forgot / too_busy / waiting / not_important / other`.

---

## 9. Security, Privacy & Auth [GAP → RESOLVED — absent in v1]

Non-negotiable for a "second brain" holding API keys and client data.

- **Auth:** Firebase Auth (email/Google) → JWT to backend. Backend verifies token
  on every request.
- **App lock:** BiometricPrompt / device credential to open the app.
- **Encryption in transit:** TLS everywhere.
- **Encryption at rest:** DB-level encryption; sensitive fields (e.g., stored
  secrets/"where's my API key") encrypted at the app layer with a per-user key.
- **On-device:** Room DB in app-private storage; secrets via Android Keystore /
  EncryptedSharedPreferences.
- **Data ownership:** export-my-data and delete-my-account flows (privacy + Play
  Store compliance).
- **AI data policy:** use OpenAI API tier that does **not** train on data; strip
  or minimize PII sent to the model where possible.
- **Least privilege:** backend never logs full prompt bodies containing secrets.

---

## 10. Offline & Sync Strategy [GAP → RESOLVED]

- **Source of truth:** server (Postgres). Room is a local cache + write buffer.
- **Offline reads:** tasks, projects, today's focus available from Room.
- **Offline writes:** queued locally with a `pending_sync` flag; WorkManager
  flushes when connectivity returns.
- **Conflict resolution:** last-write-wins per field for v1, with `updated_at`
  timestamps; upgrade to smarter merge later if needed.
- **AI actions offline:** queued and executed on reconnect (user sees "will run
  when online").

---

## 11. Data Model

### 11.1 Tables (from v1, plus additions)
Users, Projects, Tasks, Reminders, TaskHistory, **Memories (pgvector)** [NEW],
Meetings, People, Notes, Files, Notifications, ConversationHistory,
**NotificationBudget** [NEW], **UserSettings** [NEW: timezone, quiet hours,
notification prefs, voice prefs].

### 11.2 Task fields (from v1)
Task ID, Title, Description, Project, Priority, Importance, Reason, Deadline,
Created Date, Completed Date, Status, Reminder Schedule, Dependencies, Tags,
AI Notes, Progress %, History.
**Added:** `timezone`-aware timestamps, `updated_at`, `pending_sync`, `embedding_id`.

### 11.3 Relationships (from v1)
Task **belongs to** Project · **depends on** other tasks/APIs · **blocks**
launches/other tasks. Model as edges so "what blocks the client launch?" is a
graph query.

---

## 12. Feature Set

### 12.1 Core (from v1, retained)
Morning briefing · evening review · accountability nudges · intelligent reminders
· duplicate detection · memory search · daily planning · weekly review · monthly
review · voice-first control · smart notifications · conversational task capture ·
projects with AI summary · personal knowledge base.

### 12.2 New features I'm adding [NEW]
- **Snooze with reason** — moving a task asks a one-tap why; feeds accountability.
- **Focus mode / "start highest priority"** — one action to begin the top task,
  with a timer and a check-in.
- **Smart task breakdown** — big task → AI proposes subtasks (user confirms).
- **Dependency-aware planning** — "you can't start X until Y is done."
- **Streaks & gentle momentum** — progress encouragement (never guilt) per §Personality.
- **Weekly/monthly review as shareable summary** — text card the user can save/send.
- **Undo everywhere** — every destructive action reversible (trust + safety).
- **"Explain this reminder"** — tap any nudge to see the memory/reasoning behind it.
- **People memory** — remember who said what ("what did the client say?").
- **Search across everything** — one query hits tasks, notes, meetings, people.

### 12.3 Future features (from v1, parked to roadmap)
Calendar sync, Gmail, WhatsApp, Slack, Wear OS, Desktop app, Browser extension,
Email/meeting summaries, Screen context, Computer vision, **Local LLM mode**.

---

## 13. AI Behaviour & Personality (unchanged from v1)

**Behaviour:** never hallucinate (retrieve first); if unsure, ask; never assume
completion, always confirm; challenge duplicates politely; suggest easier paths;
break large tasks; encourage progress; **never guilt-trip.**

**Personality:** professional, friendly, motivating, short answers, no fluff —
an executive assistant. Example: *"You're close to finishing Project Alpha. Only
two tasks remain. Shall we finish it today?"*

---

## 14. Screens & Navigation

**Bottom nav (v1 UI):** Home / Today's Focus · Chat · Projects · Memory · Insights · Settings.

**Screens:** Splash · Auth · Chat · Task Detail · Project Detail · Timeline ·
Calendar · Notifications · Settings · Weekly Review · Monthly Review · Memory Search.
**Added:** Focus/Session screen, Onboarding (timezone, name, first project).

---

## 15. API Surface (indicative) [NEW]

```
POST /auth/verify
GET  /me · PATCH /me/settings
GET/POST/PATCH/DELETE /tasks
GET/POST /projects · GET /projects/{id}
POST /chat                 # main conversational endpoint (streams)
POST /memory/search        # semantic + structured retrieval
POST /tasks/{id}/complete  # requires confirm
POST /reviews/weekly · POST /reviews/monthly
POST /sync                 # batch push/pull for offline queue
```
All AI endpoints go through the retrieve-then-generate pipeline (§6.3).

---

## 16. Milestones, Phases & MVP

### MVP v1 — "It remembers and keeps me on track" (ship first)
**Goal:** prove the core loop — capture → understand → remember → remind → follow up.

**In scope:**
- Auth + app lock + onboarding (name, timezone).
- Conversational task capture (chat): asks *when / why / priority / blockers*.
- Tasks + Projects CRUD, offline-capable (Room + sync).
- Local reminders via WorkManager (no AI).
- Memory store + **semantic memory search** (pgvector) — the differentiator.
- **Duplicate detection** on task creation.
- **Morning briefing** + **evening review** (timezone-aware, FCM).
- Accountability nudge for overdue tasks (with reason capture).
- Voice: on-device STT/TTS, push-to-talk, core commands.
- Two-tier OpenAI integration behind `LLMClient`; retrieve-then-generate.
- Notification budget / quiet hours ("never spam").

**Explicitly NOT in v1:** monthly review, computer vision, calendar/Gmail/WhatsApp,
wake word, desktop/wear, local LLM, cloud STT.

---

### Phase breakdown

**Phase 0 — Foundations (infra & skeleton)**
- [ ] Repo setup: Android module structure (Clean Arch), FastAPI project, Postgres+pgvector, Redis, Alembic.
- [ ] CI (lint, unit tests), env/secrets management, config-driven model IDs.
- [ ] `LLMClient` interface + OpenAI adapter (chat, cheap, embeddings) with budget guard.
- [ ] Auth end-to-end (Firebase → JWT → verified backend), app lock.

**Phase 1 — Task & Project core (offline-first)**
- [ ] Room schema + Postgres schema + `/sync` batch endpoint.
- [ ] Tasks/Projects CRUD UI (Compose), Today's Focus, Task Detail, Project Detail.
- [ ] Local reminders (WorkManager), timers, notifications — no AI.
- [ ] Conflict resolution (last-write-wins + updated_at), pending-sync queue.

**Phase 2 — Memory & intelligence (the differentiator)**
- [ ] `memories` table + embedding write path on every meaningful record.
- [ ] Retrieve-then-generate pipeline + `/memory/search`.
- [ ] Conversational capture (when/why/priority/blockers).
- [ ] Duplicate detection on create.
- [ ] Chat screen with streaming responses.

**Phase 3 — Proactivity & voice**
- [ ] Scheduling engine (per-tz jobs) → morning brief / evening review via FCM.
- [ ] Accountability overdue flow + reason capture.
- [ ] Notification budget + quiet hours + adaptive back-off.
- [ ] Voice: STT/TTS, push-to-talk, core voice commands.

**Phase 4 — Reviews, insights & polish**
- [ ] Weekly review (completed/delayed/stalled/common delay reason/suggestions).
- [ ] Insights screen, streaks/momentum, task breakdown, dependency-aware planning.
- [ ] Undo everywhere, "explain this reminder", people memory.
- [ ] Perf pass, cost pass (caching/batching), test coverage, beta release.

**Phase 5+ — Future integrations** (from §12.3): monthly review, calendar/Gmail/
WhatsApp/Slack, Wear OS, desktop, browser ext, screen context, CV, **local LLM mode.**

---

## 17. Cross-cutting TODO / Definition of Done [NEW]

- [ ] Every AI feature uses retrieve-then-generate (no bare prompts).
- [ ] Every destructive action has undo/confirm.
- [ ] Every voice action has a typed/tap equivalent.
- [ ] All timestamps timezone-aware; briefings fire in user's local time.
- [ ] Notification budget enforced; quiet hours respected.
- [ ] Offline: create/read tasks + local reminders work with no network.
- [ ] Secrets encrypted (Keystore on device, app-layer for sensitive fields).
- [ ] Model IDs + pricing verified against live OpenAI docs (not hardcoded from memory).
- [ ] Per-user token budget enforced in Redis.
- [ ] Unit tests for domain logic; meaningful comments; modular structure.

---

## 18. Open Questions to Resolve Before Coding [NEW]

1. **Single-user or multi-user from day one?** (Affects auth, data isolation, cost.)
2. **Which exact OpenAI models/pricing tier** — confirm current IDs and the
   no-training data policy.
3. **Self-hosted Postgres vs managed** (Supabase gives Postgres+pgvector+auth fast).
4. **Wake word needed in v1** or is push-to-talk acceptable? (Recommend push-to-talk.)
5. **Data residency / compliance** requirements (India user data, DPDP Act)?
6. **Budget ceiling per user/month** so we can size the AI cost controls.

---

## 19. Success Criteria (from v1, plus metrics) [GAP → RESOLVED]

**Emotional (v1):** "I never forget anything." · "Someone keeps me accountable."
· "My assistant remembers everything." · "Feels like a real PA."

**Measurable [NEW]:**
- Memory-search answer relevance (thumbs up rate).
- % overdue tasks that get a reason captured (accountability working).
- Duplicate-catch rate.
- D7 / D30 retention; briefing open rate.
- AI cost per active user per month within budget.

---

## 20. Coding Standards (unchanged from v1)

Clean Architecture · MVVM · Repository pattern · Hilt · Coroutines/Flow · Room ·
WorkManager · Material 3 · Modular architecture · Unit tests · Meaningful comments
· Scalable folder structure · Production-ready code.
