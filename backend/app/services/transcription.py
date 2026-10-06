"""Audio -> transcript -> sentence units -> translation. Ported from scripts/audio_to_transcript.py
and scripts/resegment.py, which stay as standalone CLIs."""

import asyncio
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import deepl
from openai import OpenAI

from app.config import settings
from app.services import stub

# MAI-Transcribe 2 rejects m4a/aac uploads with a provider 400; these are accepted.
SUPPORTED_UPLOAD_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg"}
DEEPL_BATCH = 150  # units per request, well under DeepL's 128 KiB limit


def to_supported_audio(path: Path, workdir: Path) -> Path:
    """Transcode to mono 16 kHz mp3 unless the provider already accepts the file."""
    if path.suffix.lower() in SUPPORTED_UPLOAD_SUFFIXES:
        return path
    converted = workdir / f"{path.stem}.mp3"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(path), "-ac", "1", "-ar", "16000", str(converted)],
        check=True,
    )
    return converted


def transcribe_file(path: Path) -> dict[str, Any]:
    """Blocking: provider call with word + segment timestamps. Returns the raw result as a dict."""
    if settings.ai_stub:
        return stub.transcript(path)
    client = OpenAI(
        base_url=settings.openrouter_base_url, api_key=settings.openrouter_api_key, timeout=1800, max_retries=2
    )
    with tempfile.TemporaryDirectory() as tmp:
        audio = to_supported_audio(path, Path(tmp))
        with audio.open("rb") as f:
            result = client.audio.transcriptions.create(
                model=settings.transcribe_model,
                file=f,
                response_format="verbose_json",
                # Segments alone can span minutes; words give sentence-level timing.
                timestamp_granularities=["word", "segment"],
            )
    return result.model_dump()


@dataclass
class Unit:
    n: int
    start: float
    end: float
    text: str


def build_units(parts: list[dict[str, Any]]) -> list[Unit]:
    """Join the parts onto one timeline and cut sentences.

    `parts`: [{"offset": seconds, "transcript": raw provider dict}] in order. A sentence cut off
    at the end of one part continues into the next."""
    pieces: list[dict[str, Any]] = []
    for part in parts:
        transcript = part["transcript"] or {}
        source = transcript.get("words") or [
            {"word": s["text"], "start": s["start"], "end": s["end"]} for s in transcript.get("segments") or []
        ]
        pieces += [
            {"text": (w["word"] or "").strip(), "start": w["start"] + part["offset"], "end": w["end"] + part["offset"]}
            for w in source
        ]
    return _sentences(pieces)


def _sentences(pieces: list[dict[str, Any]]) -> list[Unit]:
    units: list[Unit] = []
    sentence = ""
    start = 0.0
    end = 0.0
    for piece in pieces:
        if not piece["text"]:
            continue
        if not sentence:
            start = piece["start"]
        else:
            sentence += " "
        sentence += piece["text"]
        end = piece["end"]
        # "4.10." or "3." is a date or an ordinal, not the end of a sentence.
        if sentence[-1] in ".?!" and not re.search(r"\d\.$", sentence):
            units.append(Unit(len(units), start, end, sentence))
            sentence = ""
    if sentence:
        units.append(Unit(len(units), start, end, sentence))
    return units


def _translate_batch(client: deepl.DeepLClient, texts: list[str]) -> list[str]:
    xml = "<doc>" + "".join(f'<s id="{i}">{escape(t)}</s>' for i, t in enumerate(texts)) + "</doc>"
    result = client.translate_text(
        xml,
        source_lang="de",
        target_lang="en-US",
        tag_handling="xml",
        outline_detection=False,
        splitting_tags=["s"],
    )
    if isinstance(result, list):
        raise TypeError("expected a single TextResult for a single input string")
    by_id = {int(e.get("id")): (e.text or "").strip() for e in ET.fromstring(result.text).iter("s")}
    if set(by_id) != set(range(len(texts))):
        raise ValueError(f"DeepL alignment broken: got ids {sorted(by_id)[:5]}... for {len(texts)} sentences")
    return [by_id[i] for i in range(len(texts))]


def translate(texts: list[str]) -> list[str]:
    """Blocking: German -> English, sentence-aligned, in batches."""
    if settings.ai_stub:
        return [f"[EN] {t}" for t in texts]
    client = deepl.DeepLClient(settings.deepl_api_key)
    out: list[str] = []
    for i in range(0, len(texts), DEEPL_BATCH):
        out += _translate_batch(client, texts[i : i + DEEPL_BATCH])
    return out


async def atranscribe(path: Path) -> dict[str, Any]:
    return await asyncio.to_thread(transcribe_file, path)


async def atranslate(texts: list[str]) -> list[str]:
    return await asyncio.to_thread(translate, texts)
