"""Each user sees only their own courses (and everything in them); an admin sees everyone's."""

import json

from sqlalchemy import text

from app.db import SessionLocal
from tests.conftest import login_as
from tests.test_api import run_original


async def queue_job(lecture_id) -> int:
    async with SessionLocal() as db:
        job_id = await db.scalar(
            text("INSERT INTO procrastinate_jobs (queue_name, task_name, args, status) VALUES ('default', 'translate_lecture', CAST(:args AS jsonb), 'failed') RETURNING id"),
            {"args": json.dumps({"lecture_id": str(lecture_id)})},
        )
        await db.commit()
        return job_id


async def test_courses_show_who_added_them(authed, lecture_id):
    courses = (await authed.get("/api/courses")).json()
    assert [(c["name"], c["added_by"]) for c in courses] == [("Software Engineering 1", "tester")]
    created = (await authed.post("/api/courses", json={"name": "Mine too"})).json()
    assert created["added_by"] == "tester"


async def test_another_user_sees_none_of_it(authed, lecture_id):
    await run_original(lecture_id)
    job_id = await queue_job(lecture_id)
    course_id = (await authed.get("/api/courses")).json()[0]["id"]
    audio = (await authed.get(f"/api/lectures/{lecture_id}")).json()["audio_url"]
    assert (await authed.get(audio)).status_code == 200
    assert (await authed.get("/api/jobs")).json()[0]["id"] == job_id

    other = await login_as(authed, "mallory")
    assert (await other.get("/api/courses")).json() == []
    assert (await other.get("/api/jobs")).json() == []
    assert (await other.get("/api/search", params={"q": "EN"})).json()["hits"] == []
    for url in (
        f"/api/courses/{course_id}",
        f"/api/courses/{course_id}/lectures",
        f"/api/lectures/{lecture_id}",
        f"/api/lectures/{lecture_id}/summary",
        f"/api/lectures/{lecture_id}/transcript.txt",
        audio,
    ):
        assert (await other.get(url)).status_code == 404, url
    assert (await other.post(f"/api/jobs/{job_id}/retry")).status_code == 404
    assert (await other.post(f"/api/lectures/{lecture_id}/english")).status_code == 404
    assert (await other.delete(f"/api/lectures/{lecture_id}")).status_code == 404
    assert (await other.delete(f"/api/courses/{course_id}")).status_code == 404
    r = await other.post("/api/lectures", data={"course_id": course_id}, files={"files": ("a.mp3", b"x", "audio/mpeg")})
    assert r.status_code == 404, "cannot upload into someone else's course"

    mine = (await other.post("/api/courses", json={"name": "Mallory's"})).json()
    assert [c["id"] for c in (await other.get("/api/courses")).json()] == [mine["id"]]


async def test_admin_sees_every_course(authed, lecture_id):
    await run_original(lecture_id)
    await queue_job(lecture_id)
    admin = await login_as(authed, "boss", admin=True)
    courses = (await admin.get("/api/courses")).json()
    assert [(c["name"], c["added_by"]) for c in courses] == [("Software Engineering 1", "tester")]
    assert (await admin.get(f"/api/lectures/{lecture_id}")).status_code == 200
    assert len((await admin.get("/api/jobs")).json()) == 1
    assert (await admin.get("/api/search", params={"q": "EN"})).json()["hits"]
