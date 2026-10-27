"""Plain-text exports of a lecture's transcript."""

import datetime
import enum
from dataclasses import dataclass


class TranscriptVersion(str, enum.Enum):
    original = "original"  # the German sentences
    translation = "translation"  # the English translation
    both = "both"  # each German sentence followed by its translation


@dataclass
class Line:
    start: float
    german: str
    english: str | None


def clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def transcript_text(
    *,
    title: str,
    date: datetime.date | None,
    duration: float,
    parts: list[tuple[str, float]],
    lines: list[Line],
    version: TranscriptVersion,
    timestamps: bool = True,
) -> str:
    """`parts`: (filename, offset seconds) per recording. Timestamps are on the lecture timeline, so a
    lecture recorded in several files gets one continuous clock; the header says where each file starts."""
    label = {
        TranscriptVersion.original: "German original",
        TranscriptVersion.translation: "English translation",
        TranscriptVersion.both: "German original with English translation",
    }[version]
    head = [title, f"{label} · {clock(duration)}" + (f" · {date.isoformat()}" if date else "")]
    if len(parts) > 1:
        head.append("Recordings: " + ", ".join(f"{name} from {clock(offset)}" for name, offset in parts))
    out = ["\n".join(head), "=" * max(len(h) for h in head), ""]

    for line in lines:
        stamp = f"[{clock(line.start)}] " if timestamps else ""
        indent = " " * len(stamp)
        english = line.english or line.german  # never leave a gap if a sentence was not translated
        if version is TranscriptVersion.original:
            out.append(f"{stamp}{line.german}")
        elif version is TranscriptVersion.translation:
            out.append(f"{stamp}{english}")
        else:
            out += [f"{stamp}{line.german}", f"{indent}{english}", ""]
    return "\n".join(out).rstrip() + "\n"
