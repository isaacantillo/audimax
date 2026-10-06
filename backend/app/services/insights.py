"""Summary and mind maps, generated from the English translation of a lecture."""

import uuid
from typing import Any

from pydantic import BaseModel

from app.services import llm

MAX_CHARS = 150_000

SUMMARY_SYSTEM = """SUMMARY_REQUEST. You write a study summary of a German university lecture
from its English translation. Markdown, in English, structured as: a two-sentence overview;
"Key concepts" (each with the German term in brackets where the lecture uses one);
"Examples and tips"; "Exam hints" (only what the lecturer actually flagged as exam-relevant,
omit the section if none). Be concrete, do not invent anything, do not exceed 600 words."""

MINDMAP_SYSTEM = """You build a mind map from study material. Return 6-14 nodes: key concepts,
each with a short label and a one-sentence summary, and edges between them with a short relation
verb phrase ("causes", "is part of", "contrasts with"). Every edge must reference node keys that
exist. Keep it connected."""


class DraftNode(BaseModel):
    key: str
    label: str
    summary: str


class DraftEdge(BaseModel):
    source: str
    target: str
    relation: str


class MindMapDraft(BaseModel):
    nodes: list[DraftNode]
    edges: list[DraftEdge]


def _to_response(draft: MindMapDraft) -> dict[str, Any]:
    ids = {n.key: str(uuid.uuid4()) for n in draft.nodes}
    return {
        "nodes": [{"id": ids[n.key], "label": n.label, "summary": n.summary} for n in draft.nodes],
        "edges": [
            {"source": ids[e.source], "target": ids[e.target], "relation": e.relation}
            for e in draft.edges
            if e.source in ids and e.target in ids and e.source != e.target
        ],
    }


async def summarize(title: str, english: str) -> str:
    return await llm.complete(
        [
            {"role": "system", "content": SUMMARY_SYSTEM},
            {"role": "user", "content": f"Lecture: {title}\n\n{english[:MAX_CHARS]}"},
        ]
    )


async def lecture_mindmap(title: str, english: str) -> dict[str, Any]:
    draft = await llm.ask(MINDMAP_SYSTEM, f"Lecture: {title}\n\n{english[:MAX_CHARS]}", MindMapDraft)
    return _to_response(draft)


async def course_mindmap(course: str, lectures: list[tuple[str, str]]) -> dict[str, Any]:
    """`lectures`: (title, summary) pairs. One map across the whole course."""
    material = "\n\n".join(f"## {title}\n{summary}" for title, summary in lectures)
    draft = await llm.ask(
        MINDMAP_SYSTEM + " Cover the whole course, linking concepts across lectures.",
        f"Course: {course}\n\n{material[:MAX_CHARS]}",
        MindMapDraft,
    )
    return _to_response(draft)
