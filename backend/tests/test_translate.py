import pytest

from app.services import llm
from app.services import transcription as tr


async def test_llm_translation_keeps_sentence_order_across_batches(monkeypatch):
    async def fake_ask(system, user, schema, **_):
        import json

        items = json.loads(user)
        return schema(sentences=[{"id": s["id"], "en": f"EN:{s['de']}"} for s in reversed(items)])

    monkeypatch.setattr(llm, "ask", fake_ask)
    texts = [f"Satz {i}." for i in range(tr.LLM_BATCH * 2 + 5)]
    assert await tr.translate_llm(texts) == [f"EN:{t}" for t in texts]


async def test_llm_translation_retries_once_then_fails_on_missing_ids(monkeypatch):
    calls = 0

    async def fake_ask(system, user, schema, **_):
        nonlocal calls
        calls += 1
        return schema(sentences=[{"id": 0, "en": "only one"}])

    monkeypatch.setattr(llm, "ask", fake_ask)
    with pytest.raises(ValueError, match="alignment"):
        await tr.translate_llm(["Eins.", "Zwei."])
    assert calls == 2
