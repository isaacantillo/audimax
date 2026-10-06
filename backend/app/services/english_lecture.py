"""The English re-performed lecture: prompts, structured outputs and the blocking/async helpers
used by the worker (app/jobs) and by scripts/pipeline.py (CLI)."""

import asyncio
import hashlib
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.services import llm
from app.services.transcription import Unit

MAX_WRITE_ATTEMPTS = 3
SAMPLE_RATE = 24_000
PARAGRAPH_PAUSE = 0.6
CHUNK_PAUSE = 1.4


# ---------- LLM output shapes ----------

class ChunkStart(BaseModel):
    first_unit: int
    title: str


class ChunkPlan(BaseModel):
    chunks: list[ChunkStart]


class ChecklistItem(BaseModel):
    id: int
    kind: Literal["definition", "explanation", "example", "tip", "exam_hint", "fact"]
    content: str
    german_terms: list[str]


class Checklist(BaseModel):
    items: list[ChecklistItem]


class Term(BaseModel):
    german: str
    english: str


class Glossary(BaseModel):
    terms: list[Term]


class Paragraph(BaseModel):
    text: str
    first_unit: int
    last_unit: int


class Script(BaseModel):
    paragraphs: list[Paragraph]


class Verdict(BaseModel):
    missing_items: list[int]
    invented: list[str]


# ---------- prompts ----------

CHUNK_PROMPT = """You segment a German university lecture transcript into topic chunks.
Each line is "[unit id] (mm:ss) sentence". Return the first unit id and a short English title
for each chunk. A chunk covers one coherent explanation, typically 3-6 minutes of speech.
Chunks are contiguous and in order; the first chunk starts at unit 0. Pure admin talk
(room changes, attendance, breaks) may be its own short chunk."""

CHECKLIST_PROMPT = """You extract a complete content checklist from one chunk of a German
university lecture. List, in order, EVERY definition, explanation step, example, tip, fact and
exam hint ("das kommt in der Klausur", "merken Sie sich", ...). Be exhaustive: this list is used
to prove nothing was lost in an English rewrite. Write `content` as one precise English
sentence. Put the German subject-specific terms involved in `german_terms` exactly as spoken
(not everyday words like "Klausur"). Course rules count as content: exam format, grading,
deadlines, submission rules, required materials, recommended reading, academic honesty and
anything about what is or is not exam-relevant. Skip only filler, false starts, repetition and
throwaway logistics (mic checks, attendance/QR codes, room changes, breaks); a chunk that is
nothing but those gets an empty list."""

GLOSSARY_PROMPT = """You pick the German key terms a student must know for a German-language
exam on this lecture. You get candidate terms with the checklist content they came from.
Keep only genuine subject terms a student would have to write or recognise in the exam
(e.g. "Vererbung", "technische Schulden", "Anforderungsdefinition"). Drop:
- words that are the same or nearly the same in English (Test, Analyse, Integration, Komplexität),
- English loanwords (Best Practices, Coding), proper names, products, course codes, file names,
- everyday words (Daten, Klassen, Methoden, programmieren, Folie).
Usually 5-20 terms per lecture. Use the base form, deduplicated, with the English equivalent."""

WRITE_PROMPT = """You are a fluent English-speaking professor re-delivering a German lecture.
Rewrite the German chunk below directly into natural spoken English, in the professor's own
teaching voice: same explanations, same examples, same tips and exam hints, same order.
It is not a summary and not a sentence-by-sentence dub. Drop filler ("ähm"), repetition,
false starts and admin talk. Do not add facts, examples or claims that are not in the source.

- Every checklist item must appear in the script.
- For each term under "Introduce", the first time it comes up, say the English term and then the
  German one, e.g. "working memory, in German Arbeitsgedächtnis,". Students are examined in German.
  Say no other German words: everything else is in English only.
- Write for the ear: short paragraphs (2-5 sentences), no lists, no markdown, no headings,
  spell out symbols and formulas the way a professor would say them.
- For each paragraph give the first and last German unit id it is based on."""

VERIFY_PROMPT = """You check an English lecture script against its German source and a
checklist. Report:
- missing_items: ids of checklist items that are absent or materially changed in the script.
- invented: claims, numbers, examples or advice in the script that the German source does not
  support (paraphrase and natural transitions are fine). Quote each briefly.
Return empty lists if the script is faithful and complete."""


# ---------- helpers ----------

def mmss(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def unit_lines(units: list[Unit]) -> str:
    return "\n".join(f"[{u.n}] ({mmss(u.start)}) {u.text}" for u in units)


_FOLD = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "s"})


def fold(text: str) -> str:
    """Lowercase and drop umlauts, so Testfall matches Testfälle (German plurals change the vowel)."""
    return text.lower().translate(_FOLD)


def mentions(term: str, text: str) -> bool:
    """Whether every word of `term` occurs in `text`, ignoring German inflection endings and umlauts."""
    haystack = fold(text)
    return all(fold(w)[: max(4, len(w) - 2)] in haystack for w in term.split())


@dataclass
class PlannedChunk:
    n: int
    title: str
    first_unit: int
    last_unit: int


async def plan_chunks(units: list[Unit]) -> list[PlannedChunk]:
    plan = await llm.ask(CHUNK_PROMPT, unit_lines(units), ChunkPlan)
    titles = {c.first_unit: c.title for c in plan.chunks if 0 <= c.first_unit < len(units)}
    titles.setdefault(0, "Introduction")
    starts = sorted(titles)
    return [
        PlannedChunk(i, titles[first], first, (starts[i + 1] if i + 1 < len(starts) else len(units)) - 1)
        for i, first in enumerate(starts)
    ]


async def extract_checklist(units: list[Unit]) -> Checklist:
    return await llm.ask(CHECKLIST_PROMPT, unit_lines(units), Checklist)


async def build_glossary(checklists: list[Checklist]) -> Glossary:
    candidates = "\n".join(
        f"{', '.join(item.german_terms)}: {item.content}"
        for checklist in checklists
        for item in checklist.items
        if item.german_terms
    )
    return await llm.ask(GLOSSARY_PROMPT, candidates or "(no candidates)", Glossary)


def introductions(glossary: Glossary, chunk_texts: list[str]) -> list[list[str]]:
    """Each glossary term is introduced in the first chunk whose German source mentions it
    (worked out up front because chunks are written in parallel)."""
    remaining = list(glossary.terms)
    out: list[list[str]] = []
    for text in chunk_texts:
        here = [t for t in remaining if mentions(t.german, text)]
        remaining = [t for t in remaining if t not in here]
        out.append([f"{t.english} = {t.german}" for t in here])
    return out


def missing_german_terms(introduce: list[str], script_text: str) -> list[str]:
    """German terms (from "english = german" entries) that the script never says. A substring check on
    the base form, so "Abhängigkeiten" counts for "Abhängigkeit"."""
    text = fold(script_text)
    terms = [entry.split(" = ", 1)[1] for entry in introduce if " = " in entry]
    return [t for t in terms if fold(t) not in text]


@dataclass
class WrittenChunk:
    paragraphs: list[Paragraph]
    verified: bool
    attempts: int
    verdict: dict


async def write_chunk(
    *,
    lecture: str,
    title: str,
    previous_title: str | None,
    is_last: bool,
    checklist: Checklist,
    introduce: list[str],
    units: list[Unit],
) -> WrittenChunk:
    """Rewrite one chunk as spoken English, verify it against the checklist, retry up to 3 times."""
    source = unit_lines(units)
    position = ("This is the opening chunk." if previous_title is None else f"The previous chunk was about: {previous_title}.")
    position += " This is the final chunk." if is_last else ""
    checklist_json = checklist.model_dump_json(indent=1)
    context = (
        f"Lecture: {lecture}\nChunk: {title}\n{position}\n\n"
        f"Introduce (first appearance in the lecture): {', '.join(introduce) or 'none'}\n\n"
        f"Checklist:\n{checklist_json}\n\nGerman source:\n{source}"
    )
    feedback = ""
    best: tuple[Script, Verdict, list[str], int] | None = None  # newest draft that passed the content check
    last: tuple[Script, Verdict, list[str], int] | None = None
    for attempt in range(1, MAX_WRITE_ATTEMPTS + 1):
        script = await llm.ask(WRITE_PROMPT, context + feedback, Script)
        english = "\n\n".join(p.text for p in script.paragraphs)
        verdict = await llm.ask(
            VERIFY_PROMPT,
            f"Checklist:\n{checklist_json}\n\nGerman source:\n{source}\n\nEnglish script:\n{english}",
            Verdict,
        )
        absent = missing_german_terms(introduce, english)
        last = (script, verdict, absent, attempt)
        content_ok = not verdict.missing_items and not verdict.invented
        if content_ok:
            best = last
        if content_ok and not absent:
            break
        problems = []
        if verdict.missing_items:
            problems.append(f"- missing checklist items: {verdict.missing_items}")
        if verdict.invented:
            problems.append(f"- unsupported content to remove: {verdict.invented}")
        if absent:
            problems.append(f"- German key terms you were told to introduce but never said: {absent}. "
                            'Say each once, e.g. "test case, in German Testfall,".')
        feedback = "\n\nYour previous draft failed review. Rewrite the whole chunk and fix:\n" + "\n".join(problems)

    # Content correctness is required; a still-missing German term is only reported. Prefer the newest
    # draft that passed the content check over a later one that regressed.
    script, verdict, absent, attempt = best or last  # type: ignore[misc]
    ok = best is not None
    lo, hi = units[0].n, units[-1].n
    paragraphs = []
    for p in script.paragraphs:
        first = min(max(p.first_unit, lo), hi)
        paragraphs.append(Paragraph(text=p.text, first_unit=first, last_unit=min(max(p.last_unit, first), hi)))
    return WrittenChunk(paragraphs, ok, attempt, {**verdict.model_dump(), "missing_terms": absent})


def clip_key(lecture_id, provider_model: str, voice: str, text: str) -> str:
    digest = hashlib.sha1(f"{provider_model}|{voice}|{text}".encode()).hexdigest()[:16]
    return f"lectures/{lecture_id}/clips/{digest}.wav"


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def stitch(chunks: list[list[Path]], out_mp3: Path) -> tuple[list[list[tuple[float, float]]], float]:
    """Blocking. Normalise each clip's loudness, join with pauses, normalise the whole, write mp3.

    Returns (start, end) seconds for every clip, grouped like `chunks`, and the total duration."""
    timings: list[list[tuple[float, float]]] = []
    t = 0.0
    with tempfile.TemporaryDirectory() as tmp:
        joined = Path(tmp) / "joined.wav"
        with wave.open(str(joined), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(SAMPLE_RATE)

            def silence(seconds: float) -> float:
                frames = int(seconds * SAMPLE_RATE)
                out.writeframes(b"\x00\x00" * frames)
                return frames / SAMPLE_RATE

            for clips in chunks:
                row = []
                for i, clip in enumerate(clips):
                    normalised = Path(tmp) / f"c{len(timings)}_{i}.wav"
                    subprocess.run(
                        ["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-af", "loudnorm=I=-18:TP=-2",
                         "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(normalised)],
                        check=True,
                    )
                    with wave.open(str(normalised), "rb") as w:
                        out.writeframes(w.readframes(w.getnframes()))
                        length = w.getnframes() / SAMPLE_RATE
                    row.append((round(t, 2), round(t + length, 2)))
                    t += length + silence(PARAGRAPH_PAUSE)
                if clips:
                    t += silence(CHUNK_PAUSE - PARAGRAPH_PAUSE)
                timings.append(row)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(joined), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
             "-ar", str(SAMPLE_RATE), "-ac", "1", "-b:a", "64k", str(out_mp3)],
            check=True,
        )
    return timings, round(t, 2)


async def astitch(chunks: list[list[Path]], out_mp3: Path):
    return await asyncio.to_thread(stitch, chunks, out_mp3)
