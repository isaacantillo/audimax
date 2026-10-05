import os
import re
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET

from deepl import DeepLClient
from dotenv import load_dotenv

load_dotenv()

RESULTS_FOLDER = Path("data/results")
FILENAME = "psy_de"
FILE = RESULTS_FOLDER / f"{FILENAME}.json"


deepl_auth_key= os.getenv(key="DEEPL_API_KEY")
if deepl_auth_key is None:
    raise Exception("No DeepL API Key")

deepl_client = DeepLClient(deepl_auth_key)



@dataclass
class Segment:
    id: int
    start: float
    end: float
    text: str
    translation: str | None

def parse_segments(segments: list) -> list[Segment]:
    sentences: list[Segment] = []
    sentence: str = ""

    for segment in segments:
        segment_text = (segment["text"] or "").strip()
        if not segment_text:
            continue

        if sentence == "":
            start = segment["start"]
        else:
            sentence += " "

        sentence += segment_text

        # "4.10." or "3." is a date or ordinal, not the end of a sentence.
        if sentence[-1] in ".?!" and not re.search(r"\d\.$", sentence):
            sentences.append(Segment(
                id=len(sentences),
                start=start,
                end=segment["end"],
                text=sentence,
                translation=None
            ))
            sentence = ""

    if sentence:
        print(sentence)
        sentences.append(Segment(
            id=len(sentences),
            start=start,
            end=segments[-1]["end"],
            text=sentence,
            translation=None
        ))

    return sentences


def segments_to_xml(segments: list[Segment]) -> str:
    body = "".join(f'<s id="{s.id}">{escape(s.text)}</s>' for s in segments)
    return f"<doc>{body}</doc>"


def attach_translations(segments: list[Segment], translated_xml: str) -> None:
    """Fill each segment's translation from the DeepL XML response, matched by id."""
    root = ET.fromstring(translated_xml)
    by_id: dict[int, str] = {}
    for elem in root.iter("s"):
        elem_id = elem.get("id")
        if elem_id is None:
            raise ValueError(f"<s> without id in response: {elem.text!r}")
        by_id[int(elem_id)] = (elem.text or "").strip()

    expected = {s.id for s in segments}
    missing = expected - by_id.keys()
    extra = by_id.keys() - expected
    if missing or extra:
        raise ValueError(
            f"alignment broken: missing={sorted(missing)} extra={sorted(extra)}"
        )

    for s in segments:
        s.translation = by_id[s.id]

def translate_segments(segments: list[Segment]) -> None:
    """Translate all segments in one DeepL call, keeping sentence alignment via <s id>."""
    translation = deepl_client.translate_text(
        segments_to_xml(segments),
        source_lang="de",
        target_lang="en-US",
        tag_handling="xml",
        outline_detection=False,
        splitting_tags=["s"],
    )
    if isinstance(translation, list):
        raise TypeError("expected a single TextResult for a single input string")

    attach_translations(segments, translation.text)


if __name__ == "__main__":
    with FILE.open("r") as f:
        result = json.load(f)

        duration: float = result["duration"]
        text: str = result["text"]

        segments = parse_segments(result["segments"])

        translate_segments(segments)

        out_path = RESULTS_FOLDER / f"{FILENAME}_units.json"
        out_path.write_text(
            json.dumps([asdict(s) for s in segments], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Wrote {len(segments)} units to {out_path}")
