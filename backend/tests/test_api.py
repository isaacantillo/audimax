import pymupdf
import pytest

from app.db import SessionLocal
from app.jobs import pipeline as p
from app.jobs import tasks
from app.models import Lecture
from tests.conftest import make_audio


@pytest.fixture
def deferred(monkeypatch):
    """The API enqueues jobs; tests run the stages themselves, so just record what was enqueued."""
    calls: list[tuple[str, dict]] = []

    async def fake_defer(task, lecture_id, **kw):
        calls.append((task.name, {"lecture_id": lecture_id, **kw}))

    async def fake_document(**kw):
        calls.append(("process_document", kw))

    monkeypatch.setattr(tasks, "defer", fake_defer)
    monkeypatch.setattr(tasks.process_document, "defer_async", fake_document)
    return calls


async def test_everything_requires_login(client):
    for path in ("/api/courses", "/api/jobs", "/api/media/lectures/x"):
        assert (await client.get(path)).status_code == 401
    assert (await client.get("/api/health")).status_code == 200


async def test_login_rejects_bad_credentials(client):
    assert (await client.post("/api/auth/login", json={"username": "tester", "password": "nope"})).status_code == 401
    assert (await client.post("/api/auth/login", json={"username": "ghost", "password": "x"})).status_code == 401


async def test_upload_process_and_read_a_lecture(authed, tmp_path, deferred):
    course = (await authed.post("/api/courses", json={"name": "SE1"})).json()
    assert course["lecture_count"] == 0

    files = [("files", (f"SE1_L1_{n}.mp3", make_audio(tmp_path / f"a{n}.mp3", s).read_bytes(), "audio/mpeg")) for n, s in ((2, 30), (1, 40))]
    r = await authed.post("/api/lectures", data={"course_id": course["id"], "english": "true"}, files=files)
    assert r.status_code == 201, r.text
    lecture = r.json()
    assert lecture["title"] == "SE1_L1"  # derived from the file names, part suffix dropped
    assert deferred == [("transcribe_lecture", {"lecture_id": lecture["id"], "english": True})]

    detail = (await authed.get(f"/api/lectures/{lecture['id']}")).json()
    assert detail["status"] == "uploaded"
    assert [x["filename"] for x in detail["parts"]] == ["SE1_L1_1.mp3", "SE1_L1_2.mp3"], "parts must be ordered by filename"

    # The English version cannot be requested before the lecture is processed.
    assert (await authed.post(f"/api/lectures/{lecture['id']}/english")).status_code == 409

    import uuid
    lid = uuid.UUID(lecture["id"])
    await p.run_transcribe(lid)
    await p.run_translate(lid)
    await p.run_index(lid)

    detail = (await authed.get(f"/api/lectures/{lecture['id']}")).json()
    assert detail["status"] == "ready" and len(detail["transcript_segments"]) > 10
    assert detail["transcript_segments"][0]["text_translated"].startswith("[EN]")
    assert detail["parts"][1]["offset"] == pytest.approx(detail["parts"][0]["duration"], abs=0.01)
    assert detail["english"] is None

    # English lecture
    assert (await authed.post(f"/api/lectures/{lecture['id']}/english")).status_code == 202
    assert (await authed.get(f"/api/lectures/{lecture['id']}")).json()["status"] == "chunking"
    for stage in (p.run_english_plan, p.run_english_write, p.run_english_voice, p.run_english_assemble, p.run_english_index):
        await stage(lid)

    detail = (await authed.get(f"/api/lectures/{lecture['id']}")).json()
    english = detail["english"]
    assert detail["status"] == "english_ready" and english["audio_url"].startswith("/api/media/lectures/")
    paragraphs = [x for c in english["chunks"] for x in c["paragraphs"]]
    assert paragraphs and all(x["end"] > x["start"] for x in paragraphs)
    # "Hear original" lands in the right recording at the right time.
    late = max(paragraphs, key=lambda x: x["source_start"])
    assert late["source_part"] == 1 and late["source_part_start"] == pytest.approx(late["source_start"] - detail["parts"][1]["offset"], abs=0.01)

    # Audio is served (local storage in tests).
    audio = await authed.get(english["audio_url"])
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/mpeg" and len(audio.content) > 1000

    # Rerun one chunk.
    assert (await authed.post(f"/api/lectures/{lecture['id']}/english/chunks/0/rerun")).status_code == 202
    assert (await authed.get(f"/api/lectures/{lecture['id']}")).json()["status"] == "scripting"
    assert deferred[-1][0] == "english_write"

    # Lists and summary
    lectures = (await authed.get(f"/api/courses/{course['id']}/lectures")).json()
    assert lectures[0]["has_english"] and "Stub summary" in lectures[0]["summary"]
    assert (await authed.get(f"/api/lectures/{lecture['id']}/summary")).json()["status"] in ("scripting", "english_ready")
    assert (await authed.get("/api/courses")).json()[0]["has_active_jobs"] is True  # mid-rerun


async def test_upload_validation(authed, deferred):
    course = (await authed.post("/api/courses", json={"name": "SE1"})).json()
    r = await authed.post("/api/lectures", data={"course_id": course["id"]}, files=[("files", ("notes.txt", b"hi", "text/plain"))])
    assert r.status_code == 422
    r = await authed.post("/api/lectures", data={"course_id": "00000000-0000-0000-0000-000000000000"}, files=[("files", ("a.mp3", b"x", "audio/mpeg"))])
    assert r.status_code == 404
    assert deferred == []


async def test_mindmaps_and_course_scope(authed, lecture_id):
    await p.run_transcribe(lecture_id)
    await p.run_translate(lecture_id)
    await p.run_index(lecture_id)
    async with SessionLocal() as db:
        course_id = (await db.get(Lecture, lecture_id)).course_id  # type: ignore[union-attr]

    lecture_map = (await authed.get(f"/api/lectures/{lecture_id}/mindmap")).json()
    assert lecture_map["nodes"] and lecture_map["edges"]
    ids = {n["id"] for n in lecture_map["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in lecture_map["edges"])

    course_map = (await authed.get(f"/api/courses/{course_id}/mindmap")).json()
    assert course_map["nodes"]
    # Cached: the same ids come back until refreshed.
    assert (await authed.get(f"/api/courses/{course_id}/mindmap")).json() == course_map
    assert (await authed.post(f"/api/courses/{course_id}/mindmap/refresh")).json() != course_map


async def test_chat_answers_with_sources_and_remembers_selection(authed, lecture_id):
    await p.run_transcribe(lecture_id)
    await p.run_translate(lecture_id)
    await p.run_index(lecture_id)
    async with SessionLocal() as db:
        course_id = str((await db.get(Lecture, lecture_id)).course_id)  # type: ignore[union-attr]

    body = {"message": "What is Softwareentwicklung?", "course_id": course_id, "lecture_ids": [str(lecture_id)]}
    r = (await authed.post("/api/chat", json=body)).json()
    assert r["message"]["role"] == "assistant"
    sources = r["message"]["sources"]
    assert sources and sources[0]["kind"] == "transcript" and sources[0]["lecture_id"] == str(lecture_id)
    assert sources[0]["title"] == "SE1 L1" and sources[0]["start"] is not None

    # Follow-up in the same thread, then the history screen shows both turns.
    await authed.post("/api/chat", json={**body, "thread_id": r["thread_id"], "message": "And more?"})
    history = (await authed.get("/api/chat/history", params={"course_id": course_id, "lecture_id": str(lecture_id)})).json()
    assert history["thread_id"] == r["thread_id"]
    assert [m["role"] for m in history["messages"]] == ["user", "assistant", "user", "assistant"]
    # A course-level chat is a different conversation.
    assert (await authed.get("/api/chat/history", params={"course_id": course_id})).json()["messages"] == []

    # Nothing selected -> no sources, and an honest answer rather than an error.
    empty = (await authed.post("/api/chat", json={"message": "hi", "course_id": course_id})).json()
    assert empty["message"]["sources"] == []

    # Web search without a key is refused clearly.
    assert (await authed.post("/api/chat", json={**body, "web": True})).status_code == 422

    sel = {"lecture_ids": [str(lecture_id)], "document_ids": [], "web": False}
    assert (await authed.put(f"/api/courses/{course_id}/chat-selection", json=sel)).status_code == 200
    assert (await authed.get(f"/api/courses/{course_id}/chat-selection")).json() == sel


async def test_slides_are_parsed_and_searchable(authed, lecture_id, tmp_path, deferred):
    async with SessionLocal() as db:
        course_id = str((await db.get(Lecture, lecture_id)).course_id)  # type: ignore[union-attr]
    pdf = tmp_path / "slides.pdf"
    doc = pymupdf.open()
    for text in ("Vererbung\n\nInheritance lets a class reuse another class.", "Polymorphismus\n\nOne interface, many implementations."):
        doc.new_page().insert_text((72, 72), text)
    doc.save(pdf)

    r = await authed.post("/api/documents", data={"course_id": course_id, "lecture_id": str(lecture_id)}, files={"file": ("slides.pdf", pdf.read_bytes(), "application/pdf")})
    assert r.status_code == 201 and r.json()["lecture"]["id"] == str(lecture_id)
    document_id = r.json()["id"]
    assert deferred[-1] == ("process_document", {"document_id": document_id})

    import uuid
    await p.run_document(uuid.UUID(document_id))
    detail = (await authed.get(f"/api/documents/{document_id}")).json()
    assert detail["status"] == "ready" and detail["page_count"] == 2 and len(detail["sections"]) == 2
    assert detail["file_url"].startswith("/api/media/documents/")
    assert (await authed.get(detail["file_url"])).headers["content-type"] == "application/pdf"
    assert (await authed.get(f"/api/lectures/{lecture_id}")).json()["documents"][0]["id"] == document_id
    assert (await authed.get(f"/api/courses/{course_id}/documents")).json()[0]["title"] == "slides"

    answer = (await authed.post("/api/chat", json={"message": "Vererbung inheritance", "course_id": course_id, "document_ids": [document_id]})).json()
    assert answer["message"]["sources"][0]["kind"] == "slides" and answer["message"]["sources"][0]["page"] == 1

    bad = await authed.post("/api/documents", data={"course_id": course_id}, files={"file": ("x.docx", b"x", "application/octet-stream")})
    assert bad.status_code == 422


async def test_jobs_list_and_retry_only_failed(authed):
    assert (await authed.get("/api/jobs")).json() == []
    assert (await authed.post("/api/jobs/999/retry")).status_code == 404


async def test_deleting_a_lecture_removes_its_files_and_data(authed, lecture_id):
    from app import storage

    key = f"lectures/{lecture_id}/parts/0-SE1_L1_1.mp3"
    assert storage.exists(key)
    assert (await authed.delete(f"/api/lectures/{lecture_id}")).status_code == 204
    assert not storage.exists(key)
    assert (await authed.get(f"/api/lectures/{lecture_id}")).status_code == 404


async def test_html_is_never_cached_but_hashed_assets_are():
    """After a deploy, a cached index.html would point browsers at bundles that no longer exist."""
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
    from httpx import ASGITransport, AsyncClient

    from app.http_cache import cache_headers

    mini = FastAPI()
    mini.middleware("http")(cache_headers)
    mini.get("/")(lambda: HTMLResponse("<html/>"))
    mini.get("/lectures/abc")(lambda: HTMLResponse("<html/>"))
    mini.get("/assets/app-abc123.js")(lambda: PlainTextResponse("x", media_type="text/javascript"))
    mini.get("/assets/missing.js")(lambda: JSONResponse({}, status_code=404))
    mini.get("/api/health")(lambda: JSONResponse({}))

    async with AsyncClient(transport=ASGITransport(app=mini), base_url="http://t") as c:
        assert (await c.get("/")).headers["cache-control"] == "no-cache"
        assert (await c.get("/lectures/abc")).headers["cache-control"] == "no-cache"  # SPA deep link
        assert (await c.get("/assets/app-abc123.js")).headers["cache-control"] == "public, max-age=31536000, immutable"
        assert "cache-control" not in (await c.get("/assets/missing.js")).headers
        assert "cache-control" not in (await c.get("/api/health")).headers


async def test_login_is_rate_limited_after_repeated_failures(client):
    from app.routers.auth import login_failures

    login_failures.reset("127.0.0.1")
    login_failures.reset("unknown")
    bad = {"username": "tester", "password": "wrong"}
    codes = [(await client.post("/api/auth/login", json=bad)).status_code for _ in range(login_failures.max_failures)]
    assert set(codes) == {401}
    blocked = await client.post("/api/auth/login", json={"username": "tester", "password": "correct horse"})
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0, "even the right password is refused while blocked"
    for key in list(login_failures._failures):
        login_failures.reset(key)
    assert (await client.post("/api/auth/login", json={"username": "tester", "password": "correct horse"})).status_code == 200


def test_failure_limiter_forgets_old_failures(monkeypatch):
    from app import ratelimit
    from app.ratelimit import FailureLimiter

    now = [1000.0]
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: now[0])
    limiter = FailureLimiter(max_failures=2, window=60)
    limiter.fail("a"), limiter.fail("a")
    assert limiter.blocked("a") and not limiter.blocked("b")
    now[0] += 61
    assert not limiter.blocked("a")
