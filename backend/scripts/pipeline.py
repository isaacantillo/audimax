"""Full lecture pipeline: German recording -> transcript -> translated units -> English lecture.

Stages (each writes into data/results/<lecture>/ and is skipped if its output exists):

    transcribe  transcript.json          MAI-Transcribe 2 (audio_to_transcript.py)
    units       units.json               sentence units + DeepL translation (resegment.py)
    chunks      chunks.json              LLM splits the lecture into topic chunks
    checklists  chunks/NN.checklist.json every definition / example / tip / exam hint per chunk
    scripts     chunks/NN.script.json    English re-performed script, verified against the checklist
    voice       clips/*.wav, tts.json    one TTS clip per paragraph; provider pinned per lecture
    assemble    lecture_en.{mp3,json,md} stitched audio, paragraph timestamps, links to the German

Rerunning only redoes what is missing. Delete chunks/03.script.json and rerun: chunk 3 is
rewritten, and only its changed paragraphs are re-voiced (clips are keyed by text hash).

Usage (from backend/):
    uv run python scripts/pipeline.py data/SE1/SE1_L1_1.m4a
    uv run python scripts/pipeline.py data/SE1/SE1_L1_1.m4a --redo scripts
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from audio_to_transcript import openai_client, transcribe
from pydantic import BaseModel
from resegment import Segment, parse_segments, translate_segments

# Generation: Gemini primary, Claude fallback (decision #7), via OpenRouter's model fallback list.
LLM_MODELS = ["google/gemini-3.8-flash", "anthropic/claude-sonnet-5.5"]

# (name, model, voice). The first one that voices the *whole* lecture wins; never mixed.
TTS_PROVIDERS = [
    ("gemini", "google/gemini-3.1-flash-tts-preview", "Charon"),
    ("qwen", "qwen/qwen-audio-3.0-tts-plus", "longanlufeng"),
]

STAGES = ["transcribe", "units", "chunks", "checklists", "scripts", "voice", "assemble"]
MAX_WRITE_ATTEMPTS = 3
WORKERS = 4
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
(not everyday words like "Klausur"). Skip only filler, false starts, repetition and
organisational talk (rooms, attendance, breaks); a chunk of pure admin gets an empty list."""

WRITE_PROMPT = """You are a fluent English-speaking professor re-delivering a German lecture.
Rewrite the German chunk below directly into natural spoken English, in the professor's own
teaching voice: same explanations, same examples, same tips and exam hints, same order.
It is not a summary and not a sentence-by-sentence dub. Drop filler ("ähm"), repetition,
false starts and admin talk. Do not add facts, examples or claims that are not in the source.

- Every checklist item must appear in the script.
- The first time a German key term from "Introduce" appears, say the English term and then the
  German one, e.g. "working memory, in German Arbeitsgedächtnis,". Students are examined in German.
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

def ask[T: BaseModel](system: str, user: str, schema: type[T]) -> T:
    completion = openai_client.chat.completions.parse(
        model=LLM_MODELS[0],
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=schema,
        temperature=0.3,
        extra_body={"models": LLM_MODELS},
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError(f"{completion.model} returned no structured output")
    return parsed


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def mmss(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def unit_lines(units: list[Segment]) -> str:
    return "\n".join(f"[{u.id}] ({mmss(u.start)}) {u.text}" for u in units)


def parallel(fn, items) -> list:
    with ThreadPoolExecutor(WORKERS) as pool:
        return list(pool.map(fn, items))


# ---------- stages ----------

class Pipeline:
    def __init__(self, audio: Path, results: Path):
        self.audio = audio
        self.name = audio.stem
        self.out = results / self.name
        self.chunk_dir = self.out / "chunks"
        self.clip_dir = self.out / "clips"
        self.out.mkdir(parents=True, exist_ok=True)

    def redo(self, stage: str) -> None:
        """Delete the outputs of `stage` and every later stage. Clips are content-addressed,
        so they survive everything except an explicit `--redo voice`."""
        for s in STAGES[STAGES.index(stage):]:
            match s:
                case "transcribe":
                    (self.out / "transcript.json").unlink(missing_ok=True)
                case "units":
                    (self.out / "units.json").unlink(missing_ok=True)
                case "chunks":
                    (self.out / "chunks.json").unlink(missing_ok=True)
                case "checklists":
                    for p in self.chunk_dir.glob("*.checklist.json"):
                        p.unlink()
                case "scripts":
                    for p in self.chunk_dir.glob("*.script.json"):
                        p.unlink()
                case "voice" if stage == "voice":
                    shutil.rmtree(self.clip_dir, ignore_errors=True)
                    (self.out / "tts.json").unlink(missing_ok=True)
                case "assemble":
                    for p in self.out.glob("lecture_en.*"):
                        p.unlink()

    def run(self) -> None:
        transcript = self.transcribe()
        units = self.units(transcript)
        chunks = self.chunks(units)
        checklists = self.checklists(chunks, units)
        scripts = self.scripts(chunks, checklists, units)
        tts, clips = self.voice(scripts)
        self.assemble(scripts, clips, tts, units, transcript["duration"])

    def transcribe(self) -> dict:
        path = self.out / "transcript.json"
        if not path.exists():
            print("transcribe: sending audio to", self.audio)
            result = transcribe(self.audio)
            path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return read_json(path)

    def units(self, transcript: dict) -> list[Segment]:
        path = self.out / "units.json"
        if not path.exists():
            segments = parse_segments(transcript["segments"])
            translate_segments(segments)
            write_json(path, [asdict(s) for s in segments])
            print(f"units: {len(segments)} sentences translated")
        return [Segment(**u) for u in read_json(path)]

    def chunks(self, units: list[Segment]) -> list[dict]:
        path = self.out / "chunks.json"
        if not path.exists():
            plan = ask(CHUNK_PROMPT, unit_lines(units), ChunkPlan)
            titles = {c.first_unit: c.title for c in plan.chunks if 0 <= c.first_unit < len(units)}
            titles.setdefault(0, "Introduction")
            starts = sorted(titles)
            chunks = []
            for i, first in enumerate(starts):
                last = (starts[i + 1] if i + 1 < len(starts) else len(units)) - 1
                chunks.append({
                    "id": i,
                    "title": titles[first],
                    "first_unit": first,
                    "last_unit": last,
                    "start": units[first].start,
                    "end": units[last].end,
                })
            write_json(path, chunks)
            print(f"chunks: {len(chunks)} topics")
        return read_json(path)

    def checklists(self, chunks: list[dict], units: list[Segment]) -> list[Checklist]:
        def one(chunk: dict) -> Checklist:
            path = self.chunk_dir / f"{chunk['id']:02d}.checklist.json"
            if not path.exists():
                source = unit_lines(units[chunk["first_unit"]:chunk["last_unit"] + 1])
                checklist = ask(CHECKLIST_PROMPT, source, Checklist)
                write_json(path, checklist.model_dump())
                print(f"checklist {chunk['id']:02d}: {len(checklist.items)} items")
            return Checklist.model_validate(read_json(path))

        return parallel(one, chunks)

    def scripts(self, chunks: list[dict], checklists: list[Checklist], units: list[Segment]) -> list[dict]:
        # German terms are introduced once per lecture, so work out where each first appears
        # before chunks are written in parallel.
        seen: set[str] = set()
        introduce: list[list[str]] = []
        for checklist in checklists:
            new = [t for item in checklist.items for t in item.german_terms if t.lower() not in seen]
            seen.update(t.lower() for t in new)
            introduce.append(list(dict.fromkeys(new)))

        def one(i: int) -> dict:
            path = self.chunk_dir / f"{i:02d}.script.json"
            if not path.exists():
                write_json(path, self.write_chunk(chunks, i, checklists[i], introduce[i], units))
            return read_json(path)

        return parallel(one, range(len(chunks)))

    def write_chunk(self, chunks, i, checklist: Checklist, introduce: list[str], units) -> dict:
        chunk = chunks[i]
        if not checklist.items:
            # Nothing worth keeping (admin talk, small talk): the chunk is left out of the audio.
            print(f"script {i:02d}: skipped, empty checklist")
            return {"chunk": chunk, "paragraphs": [], "verified": True, "attempts": 0, "verdict": None}
        source = unit_lines(units[chunk["first_unit"]:chunk["last_unit"] + 1])
        position = (
            "This is the opening chunk." if i == 0
            else f"The previous chunk was about: {chunks[i - 1]['title']}."
        ) + (" This is the final chunk." if i == len(chunks) - 1 else "")
        checklist_json = checklist.model_dump_json(indent=1)
        context = (
            f"Lecture: {self.name}\nChunk: {chunk['title']}\n{position}\n\n"
            f"Introduce (first appearance in the lecture): {', '.join(introduce) or 'none'}\n\n"
            f"Checklist:\n{checklist_json}\n\nGerman source:\n{source}"
        )

        feedback = ""
        for attempt in range(1, MAX_WRITE_ATTEMPTS + 1):
            script = ask(WRITE_PROMPT, context + feedback, Script)
            english = "\n\n".join(p.text for p in script.paragraphs)
            verdict = ask(
                VERIFY_PROMPT,
                f"Checklist:\n{checklist_json}\n\nGerman source:\n{source}\n\nEnglish script:\n{english}",
                Verdict,
            )
            ok = not verdict.missing_items and not verdict.invented
            print(f"script {i:02d}: attempt {attempt} {'ok' if ok else verdict.model_dump()}")
            if ok:
                break
            feedback = (
                "\n\nYour previous draft failed review. Rewrite the whole chunk and fix:\n"
                f"- missing checklist items: {verdict.missing_items}\n"
                f"- unsupported content to remove: {verdict.invented}"
            )

        lo, hi = chunk["first_unit"], chunk["last_unit"]
        paragraphs = []
        for n, p in enumerate(script.paragraphs):
            first = min(max(p.first_unit, lo), hi)
            last = min(max(p.last_unit, first), hi)
            paragraphs.append({"id": f"{i:02d}.{n:02d}", "text": p.text, "first_unit": first, "last_unit": last})
        return {
            "chunk": chunk,
            "paragraphs": paragraphs,
            "verified": ok,
            "attempts": attempt,
            "verdict": verdict.model_dump(),
        }

    def voice(self, scripts: list[dict]) -> tuple[dict, list[Path]]:
        state_path = self.out / "tts.json"
        texts = [p["text"] for s in scripts for p in s["paragraphs"]]
        pinned = read_json(state_path)["name"] if state_path.exists() else TTS_PROVIDERS[0][0]
        candidates = [p for p in TTS_PROVIDERS if p[0] == pinned] + [p for p in TTS_PROVIDERS if p[0] != pinned]

        for name, model, voice in candidates:
            clips = [self.clip_dir / f"{hashlib.sha1(f'{model}|{voice}|{t}'.encode()).hexdigest()[:16]}.wav" for t in texts]
            todo = [(t, c) for t, c in zip(texts, clips) if not c.exists()]
            print(f"voice: {name}, {len(todo)}/{len(clips)} clips to synthesize")
            try:
                parallel(lambda job, m=model, v=voice: self.synthesize(m, v, *job), todo)
            except Exception as e:
                # Never mix voices: the next provider re-voices the whole lecture.
                print(f"voice: {name} failed ({e}); switching the whole lecture")
                continue
            tts = {"name": name, "model": model, "voice": voice}
            write_json(state_path, tts)
            return tts, clips
        raise RuntimeError("all TTS providers failed")

    def synthesize(self, model: str, voice: str, text: str, clip: Path) -> None:
        clip.parent.mkdir(parents=True, exist_ok=True)
        # Gemini TTS only supports raw PCM; the rate comes back as "audio/pcm;rate=24000;channels=1".
        response = openai_client.audio.speech.with_raw_response.create(
            model=model, voice=voice, input=text, response_format="pcm"
        )
        params = dict(
            part.strip().split("=", 1)
            for part in response.headers["content-type"].split(";")[1:]
        )
        partial = clip.with_suffix(".part")
        with wave.open(str(partial), "wb") as out:
            out.setnchannels(int(params.get("channels", 1)))
            out.setsampwidth(2)
            out.setframerate(int(params.get("rate", SAMPLE_RATE)))
            out.writeframes(response.content)
        partial.rename(clip)

    def assemble(self, scripts, clips: list[Path], tts: dict, units: list[Segment], source_duration: float) -> None:
        wav_path = self.out / "lecture_en.wav"
        clip_iter = iter(clips)
        t = 0.0
        chunks_out = []
        with tempfile.TemporaryDirectory() as tmp, wave.open(str(wav_path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(SAMPLE_RATE)

            def silence(seconds: float) -> float:
                out.writeframes(b"\x00\x00" * int(seconds * SAMPLE_RATE))
                return int(seconds * SAMPLE_RATE) / SAMPLE_RATE

            for script in (s for s in scripts if s["paragraphs"]):
                chunk = script["chunk"]
                paragraphs_out = []
                for p in script["paragraphs"]:
                    # Per-clip loudness pass so every paragraph sits at the same level.
                    clip_wav = Path(tmp) / "clip.wav"
                    subprocess.run(
                        ["ffmpeg", "-v", "error", "-y", "-i", str(next(clip_iter)),
                         "-af", "loudnorm=I=-18:TP=-2", "-ac", "1", "-ar", str(SAMPLE_RATE),
                         "-c:a", "pcm_s16le", str(clip_wav)],
                        check=True,
                    )
                    with wave.open(str(clip_wav), "rb") as clip:
                        frames = clip.readframes(clip.getnframes())
                        length = clip.getnframes() / SAMPLE_RATE
                    out.writeframes(frames)
                    paragraphs_out.append({
                        "id": p["id"],
                        "text": p["text"],
                        "start": round(t, 2),
                        "end": round(t + length, 2),
                        "source_start": units[p["first_unit"]].start,
                        "source_end": units[p["last_unit"]].end,
                    })
                    t += length + silence(PARAGRAPH_PAUSE)
                t += silence(CHUNK_PAUSE - PARAGRAPH_PAUSE)
                chunks_out.append({
                    "id": chunk["id"],
                    "title": chunk["title"],
                    "source_start": chunk["start"],
                    "source_end": chunk["end"],
                    "verified": script["verified"],
                    "paragraphs": paragraphs_out,
                })

        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(wav_path),
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", str(SAMPLE_RATE),
             "-ac", "1", "-b:a", "64k", str(self.out / "lecture_en.mp3")],
            check=True,
        )
        wav_path.unlink()

        write_json(self.out / "lecture_en.json", {
            "lecture": self.name,
            "source_duration": source_duration,
            "duration": round(t, 2),
            "tts": tts,
            "chunks": chunks_out,
        })

        lines = [f"# {self.name}", ""]
        for c in chunks_out:
            flag = "" if c["verified"] else "  ⚠ unverified"
            lines += [f"## {c['title']}{flag}", ""]
            for p in c["paragraphs"]:
                lines += [f"{p['text']} *[{mmss(p['source_start'])}]*", ""]
        (self.out / "lecture_en.md").write_text("\n".join(lines), encoding="utf-8")

        unverified = [c["id"] for c in chunks_out if not c["verified"]]
        print(
            f"assemble: {mmss(t)} English vs {mmss(source_duration)} original "
            f"({t / source_duration:.0%}), voice {tts['name']}"
            + (f", unverified chunks: {unverified}" if unverified else "")
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio", type=Path, help="lecture recording, e.g. data/SE1/SE1_L1_1.m4a")
    parser.add_argument("--results", type=Path, default=Path("data/results"))
    parser.add_argument("--redo", choices=STAGES, help="discard this stage's output and everything after it")
    args = parser.parse_args()

    pipeline = Pipeline(args.audio, args.results)
    if args.redo:
        pipeline.redo(args.redo)
    pipeline.run()
