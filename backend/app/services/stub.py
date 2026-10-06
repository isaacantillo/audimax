"""Deterministic offline stand-ins for every AI call (AI_STUB=1). Same shapes, no network.

Good enough to exercise the whole pipeline, retrieval and UI. The text is obviously fake."""

import hashlib
import math
import re
import struct
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel

_UNIT_LINE = re.compile(r"^\[(\d+)\] \([\d:]+\) (.*)$", re.M)


def _units(text: str) -> list[tuple[int, str]]:
    return [(int(n), t) for n, t in _UNIT_LINE.findall(text)]


def _terms(text: str) -> list[str]:
    return [w for w in re.findall(r"[A-ZÄÖÜ][a-zäöüß]{7,}", text)]


def ask(system: str, user: str, schema: type[BaseModel]) -> Any:
    name = schema.__name__
    units = _units(user)
    if name == "ChunkPlan":
        return schema.model_validate(
            {"chunks": [{"first_unit": n, "title": f"Topic {i + 1}"} for i, (n, _) in enumerate(units[::6])]}
        )
    if name == "Checklist":
        return schema.model_validate(
            {
                "items": [
                    {
                        "id": i + 1,
                        "kind": "explanation",
                        "content": text[:200],
                        "german_terms": _terms(text)[:1],
                    }
                    for i, (_, text) in enumerate(units[:6])
                ]
            }
        )
    if name == "Glossary":
        seen: dict[str, str] = {}
        for term in _terms(user):
            seen.setdefault(term, f"{term.lower()} (en)")
        return schema.model_validate({"terms": [{"german": g, "english": e} for g, e in list(seen.items())[:5]]})
    if name == "Script":
        paragraphs = []
        for i in range(0, len(units), 2):
            pair = units[i : i + 2]
            paragraphs.append(
                {
                    "text": "In English: " + " ".join(t for _, t in pair),
                    "first_unit": pair[0][0],
                    "last_unit": pair[-1][0],
                }
            )
        return schema.model_validate({"paragraphs": paragraphs})
    if name == "Verdict":
        return schema.model_validate({"missing_items": [], "invented": []})
    if name == "MindMapDraft":
        words = list(dict.fromkeys(_terms(user)))[:5] or ["Topic"]
        return schema.model_validate(
            {
                "nodes": [{"key": w, "label": w, "summary": f"About {w}."} for w in words],
                "edges": [
                    {"source": a, "target": b, "relation": "relates to"} for a, b in zip(words, words[1:], strict=False)
                ],
            }
        )
    raise NotImplementedError(f"no stub for {name}")


def complete(messages: list[dict[str, str]]) -> str:
    last = messages[-1]["content"]
    if "SUMMARY_REQUEST" in messages[0]["content"]:
        return "## Summary\n\n- Stub summary of the lecture.\n- Second point."
    return "Stub answer based on the sources [1]." if "[1]" in last else "Stub answer."


def embedding(text: str, dims: int) -> list[float]:
    """Hashed bag of words: texts sharing words get nearby vectors, so retrieval tests are meaningful."""
    vec = [0.0] * dims
    for token in re.findall(r"\w+", text.lower()):
        h = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big")
        vec[h % dims] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def speech(text: str, rate: int = 24000) -> bytes:
    from app.services.llm import pcm_to_wav

    seconds = max(0.5, len(text) * 0.05)
    samples = (int(32000 * 0.2 * math.sin(2 * math.pi * 330 * i / rate)) for i in range(int(seconds * rate)))
    return pcm_to_wav(struct.pack(f"<{int(seconds * rate)}h", *samples), rate)


def transcript(path: Path) -> dict[str, Any]:
    """Fake German transcript for any audio file: ~2.5 words/second, a sentence every 9 words."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    duration = float(out)
    words = []
    for i in range(int(duration * 2.5)):
        end_of_sentence = i % 9 == 8
        tag = "".join(chr(97 + int(d)) for d in str(i))  # letters, so "Wort8." is not mistaken for a date
        word = f"Wort{tag}" if i % 7 else f"Softwareentwicklung{tag}"
        words.append(
            {"word": word + ("." if end_of_sentence else ""), "start": round(i / 2.5, 2), "end": round(i / 2.5 + 0.35, 2)}
        )
    return {"language": "german", "duration": duration, "text": " ".join(w["word"] for w in words), "words": words,
            "segments": [{"start": 0.0, "end": duration, "text": " ".join(w["word"] for w in words)}]}
