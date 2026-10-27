"""Tests run against a real Postgres (the Compose `db`, database `audimax_test`) with the offline
AI stubs and a temp-dir object store. Never touches OpenRouter, DeepL or R2."""

import subprocess
import tempfile
import uuid
from pathlib import Path

import psycopg
import pytest

from app.config import settings  # noqa: E402

# Must happen before app.db is imported anywhere: it builds its engine from these settings.
_admin_url = settings.database_url.replace("+psycopg", "")
TEST_DB = "audimax_test"
settings.database_url = settings.database_url.rsplit("/", 1)[0] + f"/{TEST_DB}"
settings.ai_stub = True
settings.r2_account_id = settings.r2_access_key_id = settings.r2_secret_access_key = ""
_storage = tempfile.mkdtemp(prefix="audimax-test-storage-")
settings.storage_dir = _storage
settings.admin_password = ""

from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from alembic import command  # noqa: E402
from app import storage  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Course, Lecture, LecturePart, User  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def database():
    with psycopg.connect(_admin_url, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture(autouse=True)
def clean():
    yield
    with psycopg.connect(settings.database_url.replace("+psycopg", ""), autocommit=True) as conn:
        conn.execute("TRUNCATE users, courses, procrastinate_jobs RESTART IDENTITY CASCADE")


def make_audio(path: Path, seconds: int) -> Path:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}",
         "-ac", "1", "-ar", "16000", str(path)],
        check=True,
    )
    return path


@pytest.fixture
async def owner_id() -> uuid.UUID:
    """The user `tester` (password "correct horse"), who owns the fixture course and logs in as `authed`."""
    async with SessionLocal() as db:
        user = User(username="tester", password_hash=hash_password("correct horse"))
        db.add(user)
        await db.commit()
        return user.id


@pytest.fixture
async def lecture_id(tmp_path, owner_id):
    """A course with one lecture recorded in two files (40 s + 30 s), uploaded but not processed."""
    async with SessionLocal() as db:
        course = Course(user_id=owner_id, name="Software Engineering 1")
        db.add(course)
        await db.flush()
        lecture = Lecture(course_id=course.id, title="SE1 L1")
        db.add(lecture)
        await db.flush()
        for n, seconds in enumerate((40, 30)):
            audio = make_audio(tmp_path / f"SE1_L1_{n + 1}.mp3", seconds)
            key = f"lectures/{lecture.id}/parts/{n}-{audio.name}"
            storage.put_file(key, audio)
            db.add(LecturePart(lecture_id=lecture.id, n=n, filename=audio.name, audio_key=key))
        await db.commit()
        return lecture.id


@pytest.fixture
async def client(owner_id):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def authed(client):
    r = await client.post("/api/auth/login", json={"username": "tester", "password": "correct horse"})
    assert r.status_code == 200
    return client


async def login_as(client: AsyncClient, username: str, *, admin: bool = False) -> AsyncClient:
    """Create another user and switch `client`'s session cookie to them."""
    async with SessionLocal() as db:
        db.add(User(username=username, password_hash=hash_password("pw " + username), is_admin=admin))
        await db.commit()
    client.cookies.clear()
    r = await client.post("/api/auth/login", json={"username": username, "password": "pw " + username})
    assert r.status_code == 200
    return client


def new_id() -> uuid.UUID:
    return uuid.uuid4()
