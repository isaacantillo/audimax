import uuid

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

    monkeypatch.setattr(tasks, "defer", fake_defer)
    return calls


async def run_original(lecture_id):
    await p.run_transcribe(lecture_id)
    await p.run_translate(lecture_id)
    await p.run_summary(lecture_id)


async def run_english(lecture_id):
    for stage in (p.run_english_plan, p.run_english_write):
        await stage(lecture_id)


async def test_everything_requires_login(client):
    for path in ("/api/courses", "/api/jobs", "/api/search?q=hello", "/api/media/lectures/x"):
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

    lid = uuid.UUID(lecture["id"])
    await run_original(lid)

    detail = (await authed.get(f"/api/lectures/{lecture['id']}")).json()
    assert detail["status"] == "ready" and len(detail["transcript_segments"]) > 10
    assert detail["transcript_segments"][0]["text_translated"].startswith("[EN]")
    assert detail["parts"][1]["offset"] == pytest.approx(detail["parts"][0]["duration"], abs=0.01)
    assert detail["english"] is None

    # English lecture
    assert (await authed.post(f"/api/lectures/{lecture['id']}/english")).status_code == 202
    assert (await authed.get(f"/api/lectures/{lecture['id']}")).json()["status"] == "chunking"
    for stage in (p.run_english_plan, p.run_english_write):
        await stage(lid)

    detail = (await authed.get(f"/api/lectures/{lecture['id']}")).json()
    assert detail["status"] == "english_ready"
    paragraphs = [x for c in detail["english"]["chunks"] for x in c["paragraphs"]]
    assert paragraphs and set(detail["english"]) == {"chunks"}, "the English version is text only"
    assert all(set(x) == {"id", "text", "source_start", "source_part", "source_part_start"} for x in paragraphs)
    # "Hear original" lands in the right recording at the right time.
    late = max(paragraphs, key=lambda x: x["source_start"])
    assert late["source_part"] == 1 and late["source_part_start"] == pytest.approx(late["source_start"] - detail["parts"][1]["offset"], abs=0.01)

    # Rerun one chunk.
    assert (await authed.post(f"/api/lectures/{lecture['id']}/english/chunks/0/rerun")).status_code == 202
    assert (await authed.get(f"/api/lectures/{lecture['id']}")).json()["status"] == "scripting"
    assert deferred[-1][0] == "english_write"

    # Lists and summary
    lectures = (await authed.get(f"/api/courses/{course['id']}/lectures")).json()
    assert lectures[0]["has_english"] and "Stub summary" in lectures[0]["summary"]
    assert (await authed.get(f"/api/lectures/{lecture['id']}/summary")).json()["status"] == "scripting"
    assert (await authed.get("/api/courses")).json()[0]["has_active_jobs"] is True  # mid-rerun


async def test_upload_validation(authed, deferred):
    course = (await authed.post("/api/courses", json={"name": "SE1"})).json()
    r = await authed.post("/api/lectures", data={"course_id": course["id"]}, files=[("files", ("notes.txt", b"hi", "text/plain"))])
    assert r.status_code == 422
    r = await authed.post("/api/lectures", data={"course_id": "00000000-0000-0000-0000-000000000000"}, files=[("files", ("a.mp3", b"x", "audio/mpeg"))])
    assert r.status_code == 404
    assert deferred == []


async def test_search_finds_words_in_transcripts_and_english_scripts(authed, lecture_id):
    await run_original(lecture_id)
    await run_english(lecture_id)
    async with SessionLocal() as db:
        course_id = str((await db.get(Lecture, lecture_id)).course_id)  # type: ignore[union-attr]

    r = (await authed.get("/api/search", params={"q": "softwareentwicklung"})).json()  # case-insensitive
    kinds = {h["kind"] for h in r["hits"]}
    assert kinds == {"transcript", "english"}
    german = [h for h in r["hits"] if h["kind"] == "transcript"]
    assert german and all("oftwareentwicklung" in (h["text"] + (h["text_translated"] or "")) for h in german)
    assert all(h["lecture_id"] == str(lecture_id) and h["lecture_title"] == "SE1 L1" for h in r["hits"])
    # Hits come in timeline order, so results read like the lecture.
    starts = [h["start"] for h in german]
    assert starts == sorted(starts)

    # A part of a word matches too ("Vererbung" inside "Mehrfachvererbung").
    assert (await authed.get("/api/search", params={"q": "entwicklung"})).json()["hits"]

    # Filtering by course; another course has nothing.
    assert (await authed.get("/api/search", params={"q": "Wort", "course_id": course_id})).json()["hits"]
    other = (await authed.post("/api/courses", json={"name": "Other"})).json()
    assert (await authed.get("/api/search", params={"q": "Wort", "course_id": other["id"]})).json()["hits"] == []

    # Wildcards are matched literally, not as "everything".
    assert (await authed.get("/api/search", params={"q": "%%"})).json()["hits"] == []
    assert (await authed.get("/api/search", params={"q": "W_rt"})).json()["hits"] == []

    # Limits are reported, not silent.
    small = (await authed.get("/api/search", params={"q": "Wort", "limit": 3})).json()
    assert small["truncated"] is True and len([h for h in small["hits"] if h["kind"] == "transcript"]) == 3

    assert (await authed.get("/api/search", params={"q": "x"})).status_code == 422, "one letter would match everything"
    assert (await authed.get("/api/search", params={"q": "zzzzqqq"})).json() == {"query": "zzzzqqq", "hits": [], "truncated": False}


async def test_english_hits_name_the_paragraph_and_the_moment_in_the_original(authed, lecture_id):
    await run_original(lecture_id)
    await run_english(lecture_id)
    hits = [h for h in (await authed.get("/api/search", params={"q": "In English"})).json()["hits"] if h["kind"] == "english"]
    assert hits and all(h["paragraph_id"] and h["text"].startswith("In English") for h in hits)

    detail = (await authed.get(f"/api/lectures/{lecture_id}")).json()
    by_id = {x["id"]: x for c in detail["english"]["chunks"] for x in c["paragraphs"]}
    assert {h["paragraph_id"] for h in hits} == set(by_id)
    assert all(h["start"] == pytest.approx(by_id[h["paragraph_id"]]["source_start"]) for h in hits), "start is the original's time"
    assert all(h["paragraph_id"] is None for h in (await authed.get("/api/search", params={"q": "Wort"})).json()["hits"] if h["kind"] == "transcript")


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
    assert (await authed.get("/api/search", params={"q": "Wort"})).json()["hits"] == []


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

    for key in list(login_failures._failures):
        login_failures.reset(key)
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


async def test_transcript_download_in_each_version(authed, lecture_id):
    url = f"/api/lectures/{lecture_id}/transcript.txt"
    assert (await authed.get(url)).status_code == 409, "nothing to download before the transcript exists"
    await run_original(lecture_id)

    german = await authed.get(url, params={"version": "original"})
    assert german.status_code == 200 and german.headers["content-type"] == "text/plain; charset=utf-8"
    assert 'attachment; filename="SE1 L1 - original.txt"' in german.headers["content-disposition"]
    body = german.text.splitlines()
    assert body[0] == "SE1 L1" and body[1].startswith("German original · 1:10")
    assert "Recordings: SE1_L1_1.mp3 from 0:00, SE1_L1_2.mp3 from 0:40" in german.text, "the header says where each file starts"
    sentences = [l for l in body if l.startswith("[")]
    detail = (await authed.get(f"/api/lectures/{lecture_id}")).json()["transcript_segments"]
    assert len(sentences) == len(detail) and sentences[0].startswith("[0:00] ")
    assert "[EN]" not in german.text

    english = (await authed.get(url, params={"version": "translation"})).text
    assert english.splitlines()[1].startswith("English translation")
    assert f"[0:00] {detail[0]['text_translated']}" in english
    assert f"[0:00] {detail[0]['text_original']}" not in english, "the translation file has no untranslated lines"

    both = (await authed.get(url, params={"version": "both"})).text
    lines = both.split("\n")
    first = next(i for i, l in enumerate(lines) if l.startswith("[0:00]"))
    assert lines[first].endswith(detail[0]["text_original"])
    assert lines[first + 1].strip() == detail[0]["text_translated"] and lines[first + 1].startswith("      "), "translation sits under its sentence"
    assert lines[first + 2] == "", "a blank line between sentence pairs"

    plain = (await authed.get(url, params={"version": "original", "timestamps": "false"})).text
    assert "[0:00]" not in plain and detail[0]["text_original"] in plain

    assert (await authed.get(url, params={"version": "klingon"})).status_code == 422
    assert (await authed.get(url)).text == german.text, "the default is the German original"


async def test_transcript_download_handles_accents_and_hour_long_clocks(authed, lecture_id):
    from app.services.export import clock

    assert [clock(s) for s in (0, 59, 61, 3599, 3600, 3725)] == ["0:00", "0:59", "1:01", "59:59", "1:00:00", "1:02:05"]
    await run_original(lecture_id)
    async with SessionLocal() as db:
        lecture = await db.get(Lecture, lecture_id)
        lecture.title = "Softwaretechnik Übung/Teil 1"  # type: ignore[union-attr]
        await db.commit()
    r = await authed.get(f"/api/lectures/{lecture_id}/transcript.txt", params={"version": "both"})
    disposition = r.headers["content-disposition"]
    assert 'filename="Softwaretechnik _bung_Teil 1 - both.txt"' in disposition, "ASCII fallback has no path separators"
    assert "filename*=UTF-8''Softwaretechnik%20%C3%9Cbung%2FTeil%201%20-%20both.txt" in disposition
    assert r.text.startswith("Softwaretechnik Übung/Teil 1\n")


async def test_transcript_download_requires_login(client, lecture_id):
    assert (await client.get(f"/api/lectures/{lecture_id}/transcript.txt")).status_code == 401
