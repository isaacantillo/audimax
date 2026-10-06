"""The study summary of a lecture, written from its English translation."""

from app.services import llm

MAX_CHARS = 150_000

SUMMARY_SYSTEM = """SUMMARY_REQUEST. You write a study summary of a German university lecture
from its English translation. Markdown, in English, structured as: a two-sentence overview;
"Key concepts" (each with the German term in brackets where the lecture uses one);
"Examples and tips"; "Exam hints" (only what the lecturer actually flagged as exam-relevant,
omit the section if none). Be concrete, do not invent anything, do not exceed 600 words."""


async def summarize(title: str, english: str) -> str:
    return await llm.complete(
        [
            {"role": "system", "content": SUMMARY_SYSTEM},
            {"role": "user", "content": f"Lecture: {title}\n\n{english[:MAX_CHARS]}"},
        ]
    )
