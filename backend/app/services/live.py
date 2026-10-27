"""Live subtitles: the browser streams 24 kHz mono PCM16, we forward it to OpenAI's realtime
transcription and send the text back. The audio is also kept on disk so the recording can be
saved as a lecture afterwards (the normal pipeline then produces the accurate transcript)."""

import asyncio
import base64
import json
import logging
import subprocess
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from websockets.asyncio.client import connect

from app.config import settings

log = logging.getLogger("audimax.live")

SAMPLE_RATE = 24000
BYTES_PER_SECOND = SAMPLE_RATE * 2
MIN_COMMIT_BYTES = BYTES_PER_SECOND // 5  # OpenAI rejects a commit with under 100 ms of audio; stay clear of it
OPENAI_URL = "wss://api.openai.com/v1/realtime?intent=transcription"
STALE_AFTER = 3 * 24 * 3600


def live_dir() -> Path:
    path = Path(settings.storage_dir) / "live"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pcm_path(session: uuid.UUID) -> Path:
    return live_dir() / f"{session}.pcm"


def remove_stale_recordings() -> None:
    cutoff = time.time() - STALE_AFTER
    for f in live_dir().glob("*.pcm"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


def pcm_to_mp3(pcm: Path, mp3: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", str(pcm),
         "-ac", "1", "-b:a", "64k", str(mp3)],
        check=True,
    )


def session_config() -> dict[str, Any]:
    transcription: dict[str, Any] = {"model": settings.live_transcribe_model}
    # gpt-live-transcribe takes a list of languages; the older gpt-4o-transcribe family a single one.
    if settings.live_transcribe_model.startswith("gpt-live"):
        transcription["languages"] = [settings.live_language]
    else:
        transcription["language"] = settings.live_language
    return {
        "type": "session.update",
        "session": {
            "type": "transcription",
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                    "transcription": transcription,
                    # We decide when a stretch of speech ends (the browser sends "commit").
                    "turn_detection": None,
                }
            },
        },
    }


def map_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """OpenAI event -> the small message the browser understands (or None to ignore it)."""
    kind = event.get("type", "")
    if kind == "input_audio_buffer.committed":
        return {"type": "item", "id": event["item_id"], "previous": event.get("previous_item_id")}
    if kind == "conversation.item.input_audio_transcription.delta":
        return {"type": "delta", "id": event["item_id"], "text": event.get("delta", "")}
    if kind == "conversation.item.input_audio_transcription.completed":
        return {"type": "final", "id": event["item_id"], "text": event.get("transcript", "")}
    if kind == "conversation.item.input_audio_transcription.failed":
        return {"type": "error", "message": (event.get("error") or {}).get("message", "Transcription failed")}
    if kind == "error":
        return {"type": "error", "message": (event.get("error") or {}).get("message", "Transcription error")}
    return None


class OpenAIUpstream:
    async def __aenter__(self) -> "OpenAIUpstream":
        self._conn = await connect(OPENAI_URL, additional_headers={"Authorization": f"Bearer {settings.openai_api_key}"})
        await self._conn.send(json.dumps(session_config()))
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._conn.close()

    async def audio(self, pcm: bytes) -> None:
        await self._conn.send(json.dumps({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm).decode()}))

    async def commit(self) -> None:
        await self._conn.send(json.dumps({"type": "input_audio_buffer.commit"}))

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        async for raw in self._conn:
            if message := map_event(json.loads(raw)):
                yield message


class StubUpstream:
    """AI_STUB=true: every commit yields a fake sentence, word by word. No network, no cost."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._n = 0
        self._previous: str | None = None

    async def __aenter__(self) -> "StubUpstream":
        return self

    async def __aexit__(self, *_: object) -> None:
        self._queue.put_nowait(None)

    async def audio(self, pcm: bytes) -> None:
        pass

    async def commit(self) -> None:
        self._n += 1
        item = f"stub-{self._n}"
        self._queue.put_nowait({"type": "item", "id": item, "previous": self._previous})
        self._previous = item
        words = f"Das ist der Testsatz Nummer {self._n}.".split()
        for word in words[:-1]:
            self._queue.put_nowait({"type": "delta", "id": item, "text": word + " "})
        self._queue.put_nowait({"type": "final", "id": item, "text": " ".join(words)})

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        while (message := await self._queue.get()) is not None:
            yield message


def open_upstream() -> OpenAIUpstream | StubUpstream:
    if settings.ai_stub:
        return StubUpstream()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return OpenAIUpstream()
