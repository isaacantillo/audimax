# Audimax

Record German university lectures and get: a transcript with English translation, a study summary, a search box over everything, and an optional **English version of each lecture, as text**: the lecture re-told in natural English, every explanation, example, tip and exam hint kept, only the noise removed, German key terms given once.

FastAPI + Postgres + a Procrastinate worker on the backend; React, TanStack Router/Query, shadcn on the front. Front and back are separate containers: the built frontend is served by nginx, which also forwards `/api` to FastAPI. Deployed with Dokploy, whose Traefik does HTTPS.

## Run it

```bash
cp .env.example .env        # then fill in OPENROUTER_API_KEY, ADMIN_PASSWORD, R2_* …
docker compose up -d --build
```

Open <http://localhost:3000> and log in as `ADMIN_USERNAME` / `ADMIN_PASSWORD` from `.env`. Five containers: `db`, `migrate` (one-shot, creates the tables), `app` (the API, also on <http://localhost:8000/docs>), `worker` (all background jobs) and `web` (the UI: nginx serving the built frontend and forwarding `/api` to `app`).

This is the same `docker-compose.yml` Dokploy deploys, with `docker-compose.override.yml` merged in for local use: it publishes the ports, runs the backend with hot reload (`backend/app` is mounted) and turns off HTTPS-only cookies. The frontend is the real production build behind the real nginx config, so routing, caching and the WebSocket behave as on the server. After changing frontend code run `docker compose up -d --build web`, or use `pnpm dev` (below) for hot reload.

**No credit / no keys?** Set `AI_STUB=true` in `.env`. Transcription, translation and the LLM are replaced by deterministic fakes, so the whole pipeline and UI work offline and for free (the text is obviously fake).

### What happens to an upload

`uploaded → transcribing → transcribed → translating → summarizing → ready`, then optionally (button on the lecture, or a checkbox at upload) `chunking → scripting → english_ready`. The English version is a checked text: each topic is rewritten, then verified against a checklist of what the German contained, and rewritten again if something is missing or invented. Watch it on the **Activity** page; failed steps show the reason and can be retried. A lecture recorded in several files (`SE1_L1_1.m4a`, `SE1_L1_2.m4a`) is uploaded together and treated as one lecture.

## Live subtitles

The **Live** page (or **Go live** on a course) shows subtitles of what the lecturer is saying, a second or two behind, in the browser on an iPad or MacBook. Press Start, allow the microphone, and use the size and full-screen buttons for a readable view. When you stop, **Save as lecture** turns the recording into a normal lecture (accurate transcript, translation, summary, optionally the English version); **Discard** throws it away.

- Needs `OPENAI_API_KEY` (OpenAI's realtime transcription; OpenRouter has no streaming speech-to-text). Model and language: `LIVE_TRANSCRIBE_MODEL` (default `gpt-live-transcribe`), `LIVE_LANGUAGE` (default `de`). With `AI_STUB=true` the subtitles are fake and nothing leaves the machine.
- The browser streams the audio to the app (`/api/live/ws`), which passes it on to OpenAI and keeps a copy until it is saved or discarded (unsaved copies are deleted after three days).
- Microphone access needs HTTPS (or `localhost`). To try it on the iPad before deploying, give your local stack a temporary HTTPS address: `cloudflared tunnel --url http://localhost:3000` (no account needed) prints a `https://….trycloudflare.com` URL to open on the iPad. Stop it when done: anyone with the URL reaches your login page. On the iPad keep Safari in front: the screen is kept awake, but switching apps pauses the microphone. A dropped connection reconnects by itself and keeps up to a minute of audio meanwhile.

## Download transcripts

On a lecture's Transcript tab, **Download as .txt** saves the transcript as a UTF-8 text file: the German original, the English translation, or both (each German sentence followed by its translation). Every sentence starts with its time in the lecture, and a lecture recorded in several files gets one continuous clock (the header lists where each file starts). Also available as `GET /api/lectures/<id>/transcript.txt?version=original|translation|both&timestamps=true|false`.

## Search

The **Search** page finds a word or phrase in the German transcripts, their English translations and the English versions (case-insensitive, matches inside words too). Each hit opens the lecture at that moment. It is plain Postgres text matching: no AI, no cost.

## Cloudflare R2

Your recordings go to R2 when `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` are set (dashboard → R2 → Manage R2 API Tokens → Object Read & Write, scoped to the bucket). Otherwise they are stored in a Docker volume, which is fine for trying it out.

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

## Production (Dokploy on a VPS)

1. Point your domain's DNS A record at the VPS.
2. In Dokploy create a **Compose** app from this repository with Compose path `./docker-compose.yml` (the override is local only and is not used). Turn on **Isolated Deployment**, so all five services share their own network and nginx reaches `app` by name.
3. **Environment**: the variables from `.env.example` with real values (Dokploy writes them to the `.env` the services load). Leave `COOKIE_SECURE` out: the compose file makes cookies HTTPS-only.
4. **Domains**: your domain on the `web` service, container port 80, HTTPS on with Let's Encrypt. Traefik terminates HTTPS and forwards to nginx; nothing else is reachable from outside.
5. Deploy. Check with **Preview Compose** first if you want to see what Dokploy adds.
6. Schedule `scripts/backup.sh` (nightly `pg_dump`, keeps 14) from the directory Dokploy checked the repo out to, and copy `backups/` off the machine. Recordings are in R2; the database is the part a dead disk would take.

## Layout

```
backend/app/
  routers/    HTTP endpoints (all under /api, everything but /health and /auth/login needs a login)
  jobs/       pipeline.py = the stages, tasks.py = queue tasks that chain them
  services/   transcription, english_lecture (prompts), summary, llm, live, stub
  models/     SQLAlchemy tables      schemas/   API shapes (source of the TypeScript client)
backend/Dockerfile     the API / migrate / worker image (Python only)
frontend/src/routes/   screens (file-based routing)    hooks/   audio player, live subtitles
frontend/Dockerfile    Vite build served by nginx      frontend/nginx.conf   static files, caching, /api → app
```

Design notes and decisions: `IMPLEMENTATION_PLAN.md`.
