# Audimax

Record German university lectures, get a searchable transcript with English translation, a summary, a mind map, chat with citations, and an **English re-performed version of each lecture as audio**: every explanation, example, tip and exam hint kept, only the noise removed.

FastAPI + Postgres (pgvector) + a Procrastinate worker on the backend; React, TanStack Router/Query, shadcn on the front, served by FastAPI itself (`app.frontend()`).

## Run it

```bash
cp .env.example .env        # then fill in OPENROUTER_API_KEY, DEEPL_API_KEY, ADMIN_PASSWORD, R2_* …
docker compose up -d --build
```

Open <http://localhost:8000> and log in as `ADMIN_USERNAME` / `ADMIN_PASSWORD` from `.env`. Four containers: `db`, `migrate` (one-shot, creates the tables), `app` (API + UI), `worker` (all background jobs).

**No credit / no keys?** Set `AI_STUB=true` in `.env`. Transcription, translation, LLM, TTS and embeddings are replaced by deterministic fakes, so the whole pipeline and UI work offline and for free (the text is obviously fake).

### What happens to an upload

`uploaded → transcribing → transcribed → translating → indexing → ready`, then optionally (button on the lecture, or a checkbox at upload) `chunking → scripting → voicing → assembling → english_ready`. Watch it on the **Activity** page; failed steps show the reason and can be retried. A lecture recorded in several files (`SE1_L1_1.m4a`, `SE1_L1_2.m4a`) is uploaded together and treated as one lecture.

## Cloudflare R2

Recordings and generated audio go to R2 when `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` are set (dashboard → R2 → Manage R2 API Tokens → Object Read & Write, scoped to the bucket). Otherwise they are stored in a Docker volume, which is fine for trying it out.

## Phone upload (iOS Shortcut)

Settings page → create an API token (shown once), then:

```bash
curl -X POST https://YOUR_DOMAIN/api/lectures \
  -H "Authorization: Bearer $TOKEN" \
  -F course_id=<course uuid> -F "files=@lecture.m4a"
```

## Develop

```bash
docker compose up -d db                 # Postgres on :5432
cd backend && uv run alembic upgrade head
uv run fastapi dev app/main.py          # API on :8000
uv run procrastinate --app=app.jobs.queue.task_queue worker   # background jobs
cd frontend && pnpm install && pnpm dev # UI on :5173, proxies /api to :8000
```

- Changed an API shape? `cd frontend && pnpm gen` re-exports the OpenAPI schema and regenerates the typed client in `src/client/`; TypeScript then points at every screen that no longer matches.
- Tests (`cd backend && uv run pytest`) run against a real Postgres (`audimax_test`, created on the fly) with the offline stubs and a temp object store. They never touch OpenRouter, DeepL or R2.
- `backend/scripts/pipeline.py` is the standalone CLI version of the lecture pipeline (files in, files out), handy for trying prompts without the app.

## Production (a VPS)

1. Point your domain's DNS at the server; set `DOMAIN` in `.env` (and real secrets, `COOKIE_SECURE` is switched on by the overlay).
2. `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`. Caddy gets the HTTPS certificate; only ports 80/443 are exposed.
3. Schedule `scripts/backup.sh` (nightly `pg_dump`, keeps 14) and copy `backups/` off the machine. Recordings are in R2; the database is the part a dead disk would take.

## Layout

```
backend/app/
  routers/    HTTP endpoints (all under /api, everything but /health and /auth/login needs a login)
  jobs/       pipeline.py = the stages, tasks.py = queue tasks that chain them
  services/   transcription, english_lecture (prompts), retrieval, insights, documents, llm, stub
  models/     SQLAlchemy tables      schemas/   API shapes (source of the TypeScript client)
frontend/src/routes/   screens (file-based routing)    components/   chat, mind map, player bits
```

Design notes and decisions: `IMPLEMENTATION_PLAN.md`.
