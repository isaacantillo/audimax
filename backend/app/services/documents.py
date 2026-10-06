"""PDF slides/scriptum -> one section per page. Isolated here so Docling can replace PyMuPDF
later without touching anything else (build plan decision 4)."""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Section:
    page: int
    heading: str | None
    text: str


def parse_pdf(path: Path) -> tuple[int, list[Section]]:
    """Blocking. Returns (page count, non-empty sections in page order)."""
    import pymupdf

    with pymupdf.open(path) as doc:
        page_count = doc.page_count

    try:
        import pymupdf4llm

        pages = pymupdf4llm.to_markdown(str(path), page_chunks=True, show_progress=False)
        raw = [(i + 1, p["text"]) for i, p in enumerate(pages)]
    except Exception:  # noqa: BLE001 - layout analysis is best effort; plain text is always available
        with pymupdf.open(path) as doc:
            raw = [(i + 1, page.get_text()) for i, page in enumerate(doc)]

    sections = []
    for page, text in raw:
        text = text.strip()
        if not text:
            continue
        match = re.search(r"^#{1,6}\s+(.+)$", text, re.M)
        sections.append(Section(page, match.group(1).strip()[:300] if match else None, text))
    return page_count, sections
