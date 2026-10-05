# Implementation Plan — Audimax full-stack app

Companion to `PROJECT_BUILD_PLAN.md`. That file holds the *why*; this one holds the *what and in which order*. Follows the API-first sequence from the build plan: screens → response shapes → endpoints → service layer → DB models last.

Verified against the installed versions while writing: FastAPI 0.141.1 (`app.frontend()` exists), Python 3.14, Docker 29 / Compose v5, Node 25, pnpm 11.

---

## 0. Target layout

```
audimax/
├── docker-compose.yml           # app + worker + postgres (dev and prod use the same file)
├── docker-compose.override.yml  # dev only: bind-mounts, fastapi dev, vite dev server
├── Caddyfile                    # prod only (Phase 4 of the build plan)
├── .env.example                 # every variable, with placeholders  ← committed
├── .env                         # real values                        ← gitignored (already)
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic/                 # migrations
│   ├── app/
│   │   ├── main.py              # FastAPI(), routers, app.frontend("/", directory="dist")
│   │   ├── config.py            # pydantic-settings: Settings()
│   │   ├── db.py                # async engine + session dependency
│   │   ├── auth.py              # session cookie / API token dependency
│   │   ├── storage.py           # R2 client (upload, presigned URL)
│   │   ├── jobs/                # procrastinate app + one task per pipeline stage
│   │   ├── models/              # SQLAlchemy tables (written LAST, Phase 3)
│   │   ├── schemas/             # Pydantic response shapes (exists)
│   │   ├── routers/             # courses, lectures, documents, chat, mindmap, jobs, auth
│   │   └── services/            # transcription, translation, english_lecture, retrieval
│   ├── scripts/                 # the prototype pipeline (exists) — stays as the CLI
│   └── dist/                    # frontend build output, copied in by the Dockerfile
└── frontend/
    ├── package.json
    ├── vite.config.ts           # proxy /api → backend in dev
    ├── openapi-ts.config.ts     # generated client from backend/openapi.json
    ├── components.json          # shadcn
    └── src/
        ├── routes/              # TanStack Router file routes
        ├── client/              # GENERATED — never edited by hand
        ├── components/ui/       # shadcn
        └── lib/
```

Two processes share one image: `app` runs `fastapi run`, `worker` runs `procrastinate worker`. Same code, same dependencies, different command.

---

## 1. Docker Compose

### `docker-compose.yml`

```yaml
services:
  db:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_DB: audimax
      POSTGRES_USER: audimax
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U audimax"]
      interval: 5s
      retries: 10

  app:
    build: { context: ., dockerfile: backend/Dockerfile }   # root context: Dockerfile needs frontend/ too
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg://audimax:${POSTGRES_PASSWORD}@db:5432/audimax
    depends_on:
      db: { condition: service_healthy }
    ports:
      - "8000:8000"
    command: ["fastapi", "run", "app/main.py", "--port", "8000", "--proxy-headers"]

  worker:
    build: { context: ., dockerfile: backend/Dockerfile }
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg://audimax:${POSTGRES_PASSWORD}@db:5432/audimax
    depends_on:
      db: { condition: service_healthy }
    command: ["procrastinate", "--app=app.jobs.queue.task_queue", "worker", "--concurrency=4"]

volumes:
  pgdata:
```

### `docker-compose.override.yml` (dev; Compose picks it up automatically)

```yaml
services:
  app:
    volumes:
      - ./backend/app:/code/app
    environment:
      FASTAPI_ENV: development      # app.frontend() only warns if dist/ is missing
    command: ["fastapi", "dev", "app/main.py", "--host", "0.0.0.0", "--port", "8000"]
  worker:
    volumes:
      - ./backend/app:/code/app
  db:
    ports:
      - "5432:5432"
```

In dev the React app runs on the Vite dev server (`pnpm dev`, port 5173) with `/api` proxied to `localhost:8000`; `app.frontend()` is only used in the production image. That keeps hot reload on both sides.

### `backend/Dockerfile` (multi-stage: build frontend, then Python image)

```dockerfile
FROM node:25-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY frontend/ .
RUN pnpm build                       # → /fe/dist

FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /code
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini .
COPY --from=frontend /fe/dist ./dist
ENV PATH="/code/.venv/bin:$PATH"
EXPOSE 8000
CMD ["fastapi", "run", "app/main.py", "--port", "8000", "--proxy-headers"]
```

Build context is the repo root so the frontend stage can see `frontend/`. ffmpeg is needed by the worker for the English-lecture assemble step.

### Serving the SPA — `app/main.py`

```python
from fastapi import FastAPI
from app.routers import auth, courses, lectures, documents, chat, mindmap, jobs

app = FastAPI(title="Audimax")

api = APIRouter(prefix="/api")
for r in (auth, courses, lectures, documents, chat, mindmap, jobs):
    api.include_router(r.router)
app.include_router(api)

# Low-priority: API routes are matched first; anything else falls back to dist/index.html
# (fallback="auto" does that when index.html exists and there is no 404.html).
app.frontend("/", directory="dist")
```

All API routes live under `/api` so there is no overlap with frontend paths. `check_dir="auto"` means: in `fastapi dev` (FASTAPI_ENV=development) a missing `dist/` is a warning; in `fastapi run` it is an error, which is what you want in the image.

---

## 2. Environment — `.env.example`

```bash
# --- Database ---
POSTGRES_PASSWORD=change-me

# --- Auth ---
SESSION_SECRET=generate-with: python -c "import secrets; print(secrets.token_urlsafe(48))"
ADMIN_PASSWORD=change-me                 # single user; hashed on first start, then this can be removed

# --- External APIs (already in backend/.env) ---
OPENROUTER_API_KEY=
DEEPL_API_KEY=
TAVILY_API_KEY=

# --- Cloudflare R2 (S3-compatible) ---
# Create a bucket in the Cloudflare dashboard → R2, then an API token with
# "Object Read & Write" scoped to that bucket. Fill these in:
R2_ACCOUNT_ID=                           # dashboard → R2 → "Account ID" on the right
R2_ACCESS_KEY_ID=                        # from the API token
R2_SECRET_ACCESS_KEY=                    # from the API token (shown once)
R2_BUCKET_NAME=audimax
# Derived, no need to change:
R2_ENDPOINT_URL=https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com

# --- Models (override without a code change) ---
TRANSCRIBE_MODEL=microsoft/mai-transcribe-2
LLM_MODELS=google/gemini-3.8-flash,anthropic/claude-sonnet-5.5
TTS_PROVIDERS=gemini:google/gemini-3.1-flash-tts-preview:Charon,qwen:qwen/qwen-audio-3.0-tts-plus:longanlufeng
EMBEDDING_MODEL=openai/text-embedding-3-large
```

`app/config.py` reads this with `pydantic-settings` (`class Settings(BaseSettings)`, `model_config = SettingsConfigDict(env_file=".env")`). `storage.py` builds the R2 client with `boto3.client("s3", endpoint_url=settings.r2_endpoint_url, aws_access_key_id=..., aws_secret_access_key=..., region_name="auto")`. Until the R2 values are filled in, `storage.py` falls back to writing under `backend/data/` so local dev works without an account.

---

## 3. Backend

### 3.1 Dependencies to add (`uv add`)

```
sqlalchemy[asyncio] psycopg[binary,pool] alembic pgvector
procrastinate[psycopg]
boto3
argon2-cffi            # password hash
itsdangerous           # not needed if sessions are opaque tokens in Postgres (decision 13) — skip
python-multipart       # file uploads
docling                # PDF slides (Phase 6; add then)
```

Dev: `pytest pytest-asyncio httpx ruff`.

### 3.2 Response shapes (exist, extend)

Already in `app/schemas/`: `Course`, `CourseSummary`, `Lecture`, `LectureSummary`, `TranscriptSegment`, `TranscriptDetails`, `DocumentSummary`, `AudioSummary`, `MindMap*`, `FileProcessingStatus`.

Add:

```python
# lectures.py
class LectureStatus(str, Enum):
    uploaded, transcribing, transcribed, translating, chunking, ready,          # original
    scripting, voicing, assembling, english_ready, failed                       # English lecture

class EnglishParagraph(BaseModel):
    id: str                 # "03.02"
    text: str
    start: float; end: float                 # in the English audio
    source_file: str; source_file_start: float   # "hear original" → which part, where

class EnglishChunk(BaseModel):
    id: int; title: str; verified: bool
    paragraphs: list[EnglishParagraph]

class EnglishLecture(BaseModel):
    audio_url: HttpUrl; duration_seconds: int
    tts_provider: str
    chunks: list[EnglishChunk]

class LecturePart(BaseModel):          # multi-file lectures
    file: str; offset: float; duration: float; audio_url: HttpUrl

# TranscriptDetails gets:  parts: list[LecturePart]; english: EnglishLecture | None; status: LectureStatus

# jobs.py
class JobSummary(BaseModel):
    id: int; task: str; status: Literal["todo","doing","succeeded","failed"]
    lecture_id: uuid.UUID | None; chunk_id: int | None
    scheduled_at: datetime; attempts: int; error: str | None

# chat.py
class ChatSource(BaseModel): kind: Literal["transcript","english","slides","web"]; ref: str; snippet: str
class ChatMessage(BaseModel): role: Literal["user","assistant"]; content: str; sources: list[ChatSource]
class ChatRequest(BaseModel): message: str; scope: list[uuid.UUID]   # lecture/document ids
```

### 3.3 Endpoints (all under `/api`)

| Method | Path | Returns | Screen |
|---|---|---|---|
| POST | `/auth/login` | sets session cookie | Login |
| POST | `/auth/logout` | — | — |
| POST | `/auth/tokens` | long-lived API token (for the phone Shortcut) | Settings |
| GET | `/courses` | `list[CourseSummary]` | Course List |
| POST | `/courses` | `Course` | Course List |
| GET | `/courses/{id}` | `CourseSummary` + lectures + documents | Course Page |
| GET | `/courses/{id}/mindmap` | `MindMapResponse` | Course Page → Mind Map |
| POST | `/lectures` (multipart: course_id, files[]) | `Lecture` | upload / Shortcut |
| GET | `/lectures/{id}` | `TranscriptDetails` | Lecture view |
| GET | `/lectures/{id}/summary` | `LectureSummary` | Summary tab |
| GET | `/lectures/{id}/mindmap` | `MindMapResponse` | Mind Map tab |
| POST | `/lectures/{id}/english` | 202, enqueues the English pipeline | Lecture view |
| POST | `/lectures/{id}/english/chunks/{n}/rerun` | 202 | Activity |
| POST | `/documents` (multipart PDF) | `DocumentSummary` | Course Page |
| GET | `/documents/{id}` | `DocumentSummary` + parsed sections | Document view |
| POST | `/chat` | `ChatMessage` (stream later) | Chat tabs |
| GET | `/jobs?status=` | `list[JobSummary]` | Activity |
| POST | `/jobs/{id}/retry` | 202 | Activity |
| GET | `/media/{key}` | 302 to presigned R2 URL (or file in dev) | audio players |

Auth is a dependency (`Depends(current_user)`) on every router except `/auth/login`. The phone Shortcut uses `Authorization: Bearer <token>`; the browser uses the cookie. One `sessions` table, `kind` column distinguishes them (decision 13).

### 3.4 Jobs — porting `scripts/pipeline.py`

The script's stages map one-to-one to procrastinate tasks. The script stays as the CLI; the task bodies import the same functions from `app/services/english_lecture.py` (move the stage functions there, leave `scripts/pipeline.py` as a thin wrapper that calls them with file paths).

```python
# app/jobs/queue.py
task_queue = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=settings.database_url_psycopg))

# app/jobs/lecture.py  — chain: each task defers the next on success
@task_queue.task(queue="transcribe", retry=2)
async def transcribe_part(lecture_id, part_id): ...        # one job per file → parallel
@task_queue.task(queue="llm")
async def merge_and_translate(lecture_id): ...             # waits until all parts done; DeepL in batches of 150
@task_queue.task(queue="llm")   async def chunk(lecture_id): ...
@task_queue.task(queue="llm")   async def checklist(lecture_id, chunk_id): ...   # one per chunk
@task_queue.task(queue="llm")   async def glossary(lecture_id): ...
@task_queue.task(queue="llm")   async def write_script(lecture_id, chunk_id): ... # write + verify, ≤3 tries
@task_queue.task(queue="tts")   async def voice(lecture_id): ...                 # all paragraphs, provider pinned on the lecture row
@task_queue.task(queue="media") async def assemble(lecture_id): ...              # ffmpeg, upload mp3 to R2, status → english_ready
@task_queue.task(queue="llm")   async def embed(lecture_id): ...                 # transcript + english paragraphs → pgvector
```

Rules carried over from the script:
- **Cache is the DB now**: a task first checks whether its output rows exist and returns early. Rerunning a chunk = delete its rows + defer `write_script`.
- **TTS fallback per lecture**: `voice` tries the pinned provider; on failure it deletes that lecture's clips, updates `lectures.tts_provider`, and re-queues itself. Never mixes.
- **Clips keyed by `sha1(model|voice|text)`** in R2 under `lectures/{id}/clips/`, so a rewritten chunk re-voices only changed paragraphs.
- **Fan-in**: `checklist` and `write_script` run per chunk in parallel; the task that follows checks `count(done) == count(chunks)` and only the last finisher defers the next step (use `SELECT … FOR UPDATE` on the lecture row to avoid a double-defer).

Worker concurrency 4 matches the script's `WORKERS`. Queues let you later run `tts` with lower concurrency if OpenRouter rate-limits.

Schema: `procrastinate schema --apply` on first start (add as a one-shot `migrate` Compose service that runs `alembic upgrade head && procrastinate schema --apply`, with `app` and `worker` `depends_on` it with `condition: service_completed_successfully`).

### 3.5 DB models (Phase 3 — write them once the endpoints return dummy data)

```
users(id, email, password_hash)
sessions(id, user_id, token_hash, kind ∈ {browser, api}, expires_at)
courses(id, name, created_at)
lectures(id, course_id, title, date, status, duration, tts_provider, created_at)
lecture_parts(id, lecture_id, n, r2_key, offset, duration)
transcript_units(id, lecture_id, n, start, end, text_de, text_en)
english_chunks(id, lecture_id, n, title, first_unit, last_unit, verified, attempts, verdict jsonb)
checklist_items(id, chunk_id, n, kind, content, german_terms text[])
glossary_terms(id, lecture_id, german, english)
english_paragraphs(id, chunk_id, n, text, first_unit, last_unit, clip_key, start, end)
documents(id, course_id, lecture_id?, title, r2_key, status)
document_sections(id, document_id, heading, text, page)
embeddings(id, source_kind, source_id, lecture_id?, document_id?, vector(3072))   -- pgvector, HNSW index
chat_threads(id, scope jsonb, last_selection jsonb)   -- "remembers last selection" lives here
chat_messages(id, thread_id, role, content, sources jsonb)
```

Alembic from day one; `pgvector` extension created in the first migration.

---

## 4. Frontend

### 4.1 Scaffold

```bash
pnpm create vite frontend --template react-ts
cd frontend
pnpm add @tanstack/react-router @tanstack/react-query @tanstack/router-plugin
pnpm add -D @tanstack/router-devtools @tanstack/react-query-devtools
pnpm add -D @hey-api/openapi-ts
pnpm add tailwindcss @tailwindcss/vite
pnpm dlx shadcn@latest init        # then: add button card tabs table badge dialog sheet skeleton toast
```

`vite.config.ts`: `TanStackRouterVite()` plugin (file-based routes), tailwind plugin, and

```ts
server: { proxy: { "/api": "http://localhost:8000" } }
```

### 4.2 Generated client

`openapi-ts.config.ts`:

```ts
import { defineConfig } from "@hey-api/openapi-ts";
export default defineConfig({
  input: "../backend/openapi.json",
  output: "src/client",
  plugins: ["@hey-api/client-fetch", { name: "@tanstack/react-query", queryOptions: true }],
});
```

Backend side: a `scripts/export_openapi.py` that imports `app` and dumps `app.openapi()` to `backend/openapi.json`. Frontend `package.json` script: `"gen": "python ../backend/scripts/export_openapi.py && openapi-ts"`. Run `pnpm gen` whenever a Pydantic schema changes; TypeScript then fails to compile wherever the UI drifted from the contract — that is the point of decision 15.

Client base URL: `client.setConfig({ baseUrl: "/api", credentials: "include" })` once in `main.tsx`; the generated `getLectureOptions({ path: { id } })` etc. plug straight into `useQuery`.

### 4.3 Routes (TanStack file routes ↔ screens from the build plan)

```
src/routes/
├── __root.tsx            # QueryClientProvider, nav, auth guard (redirect to /login on 401)
├── login.tsx
├── index.tsx             # Course List
├── courses.$courseId.tsx # Course Page: lectures, documents, chat (source selector), mind map
├── lectures.$lectureId.tsx
│   └── tabs: transcript | summary | mindmap | chat        (search param `?tab=`)
├── documents.$documentId.tsx
└── activity.tsx          # jobs table, retry, rerun chunk
```

### 4.4 Transcript tab (the one screen that matters first)

- `<audio>` element + `useSyncedCursor(currentTime, units)` that highlights the active unit (binary search over `start`).
- Toggle **Original / English**: swaps the audio source (`parts[n].audio_url` vs `english.audio_url`) and the text (German+English units vs English paragraphs).
- In English mode each paragraph has a **hear original** button: sets the original player to `parts[i]` where `parts[i].file == paragraph.source_file`, seeks `source_file_start`, plays.
- Chunks that are `verified: false` get a shadcn `Badge variant="destructive"` with a tooltip, and a "rerun" button that calls `POST …/chunks/{n}/rerun`.
- Activity page polls `GET /jobs` every 3 s while any job is `doing` (`refetchInterval`).

---

## 5. Order of work

Each step ends with something you can click or curl. Mirrors Phases 2–4b of the build plan.

1. **Compose up** — `db` only. `docker compose up db`, connect with psql. *(Phase 2)*
2. **Skeleton app in Docker** — Dockerfile, `app/main.py` with `/api/health`, `app.frontend("/", directory="dist")` serving a placeholder `dist/index.html`. `docker compose up` → `localhost:8000` shows the page, `/api/health` returns JSON, `/docs` works.
3. **Dummy endpoints** — every router in §3.3 returning hard-coded data matching the schemas. Export `openapi.json`.
4. **Frontend scaffold + generated client** — Vite, router, shadcn, `pnpm gen`, Course List rendering the dummy data through `useQuery`. Vite proxy to the backend.
5. **Auth** — users/sessions tables (first Alembic migration), login page, `current_user` dependency, cookie + bearer. Everything else now requires it.
6. **Upload + storage** — `POST /lectures` with multipart, `storage.py` (local fallback until R2 keys exist), `lecture_parts` rows, `GET /media/{key}`.
7. **Jobs: original pipeline** — procrastinate schema, `transcribe_part` → `merge_and_translate`, status transitions, Activity page shows it moving. First real transcript in the DB. *(Phase 3 done when the Transcript tab plays a real lecture with synced German/English units.)*
8. **Jobs: English lecture** — port `chunk … assemble` from `scripts/pipeline.py` into `services/english_lecture.py`, tasks per §3.4, English toggle + hear-original in the UI, rerun-chunk from Activity. *(Phase 4b)*
9. **Embeddings + chat** — `embed` task, retrieval scoped to one lecture, Gemini → Claude fallback, Chat tab. *(Phase 5)*
10. **Summary + mind map, then course level** — *(Phases 6–7)*
11. **Off the laptop** — VPS, same `docker-compose.yml` without the override, Caddyfile, real R2 keys in `.env`, iOS Shortcut posting to `/api/lectures` with the bearer token. *(Phase 4)*

---

## 6. Open points to decide while building

- **Streaming chat**: start with a plain JSON response; switch to SSE (`StreamingResponse`) once the non-streaming version works.
- **Fan-in locking** (§3.4): `SELECT … FOR UPDATE` on the lecture row is the simple answer; if it gets awkward, procrastinate's `lock=` argument per lecture serialises the fan-in tasks instead.
- **Clip storage**: R2 for everything (simple) vs. clips local to the worker and only the final mp3 in R2 (cheaper, but a worker rebuild loses the clip cache). Start with R2.
- **Embedding dimension**: `text-embedding-3-large` is 3072 dims; pgvector HNSW supports up to 2000 dims by default for `vector`, so either request `dimensions=1536` from the model or use `halfvec`. Decide at step 9.
