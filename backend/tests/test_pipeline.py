from sqlalchemy import select

from app.db import SessionLocal
from app.jobs import pipeline as p
from app.models import Chunk, Lecture, LecturePart, Paragraph, Unit
from app.services import english_lecture as el
from app.services import llm


async def lecture_row(lecture_id) -> Lecture:
    async with SessionLocal() as db:
        return await db.get(Lecture, lecture_id)  # type: ignore[return-value]


async def run_original(lecture_id):
    await p.run_transcribe(lecture_id)
    await p.run_translate(lecture_id)
    await p.run_summary(lecture_id)


async def run_english(lecture_id):
    await p.run_english_plan(lecture_id)
    await p.run_english_write(lecture_id)


async def test_original_pipeline_joins_parts_on_one_timeline(lecture_id):
    await p.run_transcribe(lecture_id)
    async with SessionLocal() as db:
        parts = list((await db.execute(select(LecturePart).order_by(LecturePart.n))).scalars())
        assert parts[0].offset == 0
        assert abs(parts[1].offset - parts[0].duration) < 0.01
        assert abs((await db.get(Lecture, lecture_id)).duration - 70) < 1  # type: ignore[union-attr]

    await p.run_translate(lecture_id)
    async with SessionLocal() as db:
        units = list((await db.execute(select(Unit).order_by(Unit.n))).scalars())
        offset = parts[1].offset
    assert len(units) > 10, "sentences were not split"
    assert [u.n for u in units] == list(range(len(units)))
    assert all(a.start <= b.start for a, b in zip(units, units[1:]))
    assert all(u.text_en.startswith("[EN]") for u in units)
    # A sentence cut off at the end of recording 1 continues into recording 2.
    assert any(u.start < offset < u.end for u in units)

    await p.run_summary(lecture_id)
    lecture = await lecture_row(lecture_id)
    assert lecture.status == "ready"
    assert "Stub summary" in lecture.summary


async def test_english_version_is_written_verified_and_linked_to_the_original(lecture_id):
    await run_original(lecture_id)
    await p.run_english_plan(lecture_id)
    assert (await lecture_row(lecture_id)).status == "chunking"
    await p.run_english_write(lecture_id)
    assert (await lecture_row(lecture_id)).status == "english_ready", "writing the script is the last step: there is no audio"

    async with SessionLocal() as db:
        chunks = list((await db.execute(select(Chunk).order_by(Chunk.n))).scalars())
        paragraphs = list((await db.execute(select(Paragraph).order_by(Paragraph.chunk_n, Paragraph.n))).scalars())
        units = {u.n: u for u in (await db.execute(select(Unit))).scalars()}
    assert len(chunks) > 1 and all(c.status == "done" and c.verified for c in chunks)
    assert paragraphs and all(x.text.startswith("In English:") for x in paragraphs)
    # Every paragraph points back into the German source, in order.
    assert all(x.first_unit in units and x.last_unit in units and x.first_unit <= x.last_unit for x in paragraphs)
    firsts = [x.first_unit for x in paragraphs]
    assert firsts == sorted(firsts)


async def test_rewriting_one_chunk_leaves_the_others_alone(lecture_id):
    await run_original(lecture_id)
    await run_english(lecture_id)
    async with SessionLocal() as db:
        before = {(x.chunk_n, x.n): (x.id, x.text) for x in (await db.execute(select(Paragraph))).scalars()}

    await p.reset_chunk(lecture_id, 0)
    async with SessionLocal() as db:
        chunk = (await db.execute(select(Chunk).where(Chunk.n == 0))).scalar_one()
        assert chunk.status == "pending"
        remaining = list((await db.execute(select(Paragraph))).scalars())
    assert remaining and all(x.chunk_n != 0 for x in remaining), "only that chunk's paragraphs are removed"

    await p.run_english_write(lecture_id)
    assert (await lecture_row(lecture_id)).status == "english_ready"
    async with SessionLocal() as db:
        after = {(x.chunk_n, x.n): (x.id, x.text) for x in (await db.execute(select(Paragraph))).scalars()}
    assert set(after) == set(before)
    untouched = {k for k in before if k[0] != 0}
    assert all(after[k] == before[k] for k in untouched), "other chunks keep their very same rows (no rewrite, no new cost)"


async def test_failure_marks_the_lecture_with_the_reason(lecture_id, monkeypatch):
    async def boom(path):
        raise RuntimeError("provider returned 400")

    monkeypatch.setattr(p, "atranscribe", boom)
    try:
        await p.run_transcribe(lecture_id)
    except RuntimeError:
        pass
    lecture = await lecture_row(lecture_id)
    assert lecture.status == "failed" and "provider returned 400" in lecture.error


async def test_write_chunk_asks_again_when_a_planned_german_term_is_missing(monkeypatch):
    """The checklist check can pass while the exam vocabulary is silently dropped."""
    from app.services.transcription import Unit

    prompts: list[str] = []

    async def fake_ask(system, user, schema):
        if schema.__name__ == "Script":
            prompts.append(user)
            said = "test case, in German Testfall," if len(prompts) > 1 else "test case"
            return el.Script(paragraphs=[el.Paragraph(text=f"Write a {said} first.", first_unit=0, last_unit=0)])
        return el.Verdict(missing_items=[], invented=[])

    monkeypatch.setattr(llm, "ask", fake_ask)
    written = await el.write_chunk(
        lecture="L", title="T", previous_title=None, is_last=True,
        checklist=el.Checklist(items=[]), introduce=["test case = Testfall"], units=[Unit(0, 0.0, 1.0, "Schreiben Sie einen Testfall.")],
    )
    assert len(prompts) == 2 and "Testfall" in prompts[1] and "never said" in prompts[1]
    assert written.verified and written.attempts == 2 and written.verdict["missing_terms"] == []


async def test_a_missing_term_never_fails_the_chunk_and_regressions_are_not_kept(monkeypatch):
    from app.services.transcription import Unit

    drafts = iter([
        ("Good content, no German term.", el.Verdict(missing_items=[], invented=[])),       # content ok, term missing
        ("Mentions Testfall but dropped an item.", el.Verdict(missing_items=[2], invented=[])),  # regressed
        ("Good content again, still no term.", el.Verdict(missing_items=[], invented=[])),
    ])
    current: list[el.Verdict] = []

    async def fake_ask(system, user, schema):
        if schema.__name__ == "Script":
            text, verdict = next(drafts)
            current[:] = [verdict]
            return el.Script(paragraphs=[el.Paragraph(text=text, first_unit=0, last_unit=0)])
        return current[0]

    monkeypatch.setattr(llm, "ask", fake_ask)
    written = await el.write_chunk(
        lecture="L", title="T", previous_title=None, is_last=True, checklist=el.Checklist(items=[]),
        introduce=["test case = Testfall"], units=[Unit(0, 0.0, 1.0, "x")],
    )
    assert written.verified, "a missing German word alone must not mark the chunk unverified"
    assert written.paragraphs[0].text == "Good content again, still no term."
    assert written.verdict["missing_terms"] == ["Testfall"]
    assert el.missing_german_terms(["dependency = Abhängigkeit"], "the Abhängigkeiten grow") == [], "inflected forms count"


def test_glossary_terms_are_found_across_german_inflection():
    """Found on a real lecture: Testfall was assigned to no chunk because the plural is Testfälle."""
    glossary = el.Glossary(terms=[
        el.Term(german="Testfall", english="test case"),
        el.Term(german="technische Schulden", english="technical debt"),
        el.Term(german="Grenzwert", english="boundary value"),
        el.Term(german="Vererbung", english="inheritance"),
    ])
    chunks = [
        "Wir sprechen über technische Schulden und wie sie entstehen.",
        "Definieren Sie Testfälle und Grenzwerte vor der Implementierung.",
        "Vererbung wird später behandelt, und noch einmal die Testfälle.",
    ]
    assigned = el.introductions(glossary, chunks)
    assert assigned[0] == ["technical debt = technische Schulden"]
    assert sorted(assigned[1]) == ["boundary value = Grenzwert", "test case = Testfall"]
    assert assigned[2] == ["inheritance = Vererbung"], "a term is introduced once, in the first chunk that mentions it"
    assert el.missing_german_terms(["test case = Testfall"], "Define each Testfälle first.") == []
    assert el.missing_german_terms(["test case = Testfall"], "Define each test case first.") == ["Testfall"]
