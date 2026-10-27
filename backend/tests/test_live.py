"""Live subtitles. WebSockets need Starlette's TestClient, which runs the app in its own event loop,
so these tests are synchronous and let the app's lifespan create the user."""

import contextlib
import uuid
from concurrent.futures import CancelledError

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import storage
from app.config import settings
from app.jobs import tasks
from app.services import live

SECOND = b"\x00\x01" * live.SAMPLE_RATE  # one second of (near-)silence as PCM16


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    from app.main import app

    monkeypatch.setattr(settings, "admin_username", "tester")
    monkeypatch.setattr(settings, "admin_password", "correct horse")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    calls = []

    async def fake_defer(task, lecture_id, **kw):
        calls.append((task.name, {"lecture_id": lecture_id, **kw}))

    monkeypatch.setattr(tasks, "defer", fake_defer)
    with TestClient(app) as c:
        c.calls = calls
        yield c


@contextlib.contextmanager
def socket(c: TestClient, session: uuid.UUID):
    """TestClient cancels the app the moment the client closes, which interrupts the handler's cleanup
    awaits. A real server only delivers a disconnect, so that cancellation is ignored here."""
    with contextlib.suppress(CancelledError), c.websocket_connect(f"/api/live/ws?session={session}") as ws:
        yield ws


def login(c: TestClient) -> None:
    assert c.post("/api/auth/login", json={"username": "tester", "password": "correct horse"}).status_code == 200


def test_the_socket_requires_login(app_client):
    with pytest.raises(WebSocketDisconnect), app_client.websocket_connect(f"/api/live/ws?session={uuid.uuid4()}"):
        pass
    assert app_client.post(f"/api/live/{uuid.uuid4()}/save", json={"course_id": str(uuid.uuid4())}).status_code == 401


def test_subtitles_stream_back_and_the_recording_can_be_saved_as_a_lecture(app_client):
    login(app_client)
    course = app_client.post("/api/courses", json={"name": "SE1"}).json()
    session = uuid.uuid4()

    # A recording can be saved only once it has some length.
    assert app_client.post(f"/api/live/{session}/save", json={"course_id": course["id"]}).status_code == 404

    with socket(app_client, session) as ws:
        for _ in range(3):
            ws.send_bytes(SECOND)
        ws.send_json({"type": "commit"})
        events = []
        while not events or events[-1]["type"] != "final":
            events.append(ws.receive_json())
    assert [e["type"] for e in events][0] == "item"
    assert any(e["type"] == "delta" for e in events)
    assert events[-1] == {"type": "final", "id": events[0]["id"], "text": "Das ist der Testsatz Nummer 1."}

    # Reconnecting with the same session appends to the same recording.
    with socket(app_client, session) as ws:
        for _ in range(3):
            ws.send_bytes(SECOND)
    assert live.pcm_path(session).stat().st_size == 6 * len(SECOND)

    r = app_client.post(f"/api/live/{session}/save", json={"course_id": course["id"], "title": "Live test"})
    assert r.status_code == 201, r.text
    lecture = r.json()
    assert lecture["title"] == "Live test"
    assert app_client.calls == [("transcribe_lecture", {"lecture_id": lecture["id"]})]
    assert not live.pcm_path(session).exists(), "the raw recording is removed once it is a lecture"
    detail = app_client.get(f"/api/lectures/{lecture['id']}").json()
    assert detail["status"] == "uploaded" and detail["parts"][0]["filename"] == "live-recording.mp3"
    assert storage.exists(f"lectures/{lecture['id']}/parts/0-live-recording.mp3")


def test_a_commit_with_almost_no_audio_is_ignored_and_discard_removes_the_recording(app_client):
    login(app_client)
    session = uuid.uuid4()
    with socket(app_client, session) as ws:
        ws.send_bytes(b"\x00\x00" * 100)
        ws.send_json({"type": "commit"})  # under 100 ms: OpenAI would reject it, so we do not send it
        ws.send_bytes(SECOND)
        ws.send_json({"type": "commit"})
        assert ws.receive_json()["type"] == "item"
        assert ws.receive_json()["type"] == "delta"
    assert app_client.delete(f"/api/live/{session}").status_code == 204
    assert not live.pcm_path(session).exists()


def test_openai_events_are_mapped_for_the_browser():
    assert live.map_event({"type": "conversation.item.input_audio_transcription.delta", "item_id": "a", "delta": "Hal"}) == {
        "type": "delta", "id": "a", "text": "Hal"}
    assert live.map_event({"type": "conversation.item.input_audio_transcription.completed", "item_id": "a", "transcript": "Hallo."}) == {
        "type": "final", "id": "a", "text": "Hallo."}
    assert live.map_event({"type": "error", "error": {"message": "bad key"}}) == {"type": "error", "message": "bad key"}
    assert live.map_event({"type": "session.updated"}) is None
