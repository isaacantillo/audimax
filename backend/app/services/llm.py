"""All LLM / TTS calls go through OpenRouter; AI_STUB=1 swaps in offline fakes."""

from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import settings
from app.services import stub

T = TypeVar("T", bound=BaseModel)

client = AsyncOpenAI(
    base_url=settings.openrouter_base_url,
    api_key=settings.openrouter_api_key or "missing-key",
    timeout=300,
    max_retries=3,
)


async def ask(system: str, user: str, schema: type[T], *, temperature: float = 0.3) -> T:
    """Structured output. OpenRouter tries `llm_models` in order if the first one fails."""
    if settings.ai_stub:
        return stub.ask(system, user, schema)
    models = settings.llm_model_list
    completion = await client.chat.completions.parse(
        model=models[0],
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format=schema,
        temperature=temperature,
        extra_body={"models": models},
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError(f"{completion.model} returned no structured output")
    return parsed


async def complete(messages: list[dict[str, str]], *, temperature: float = 0.2) -> str:
    if settings.ai_stub:
        return stub.complete(messages)
    models = settings.llm_model_list
    completion = await client.chat.completions.create(
        model=models[0], messages=messages, temperature=temperature, extra_body={"models": models}
    )
    return completion.choices[0].message.content or ""


async def speak(model: str, voice: str, text: str) -> bytes:
    """Text to a mono 16-bit WAV. Gemini TTS only supports raw PCM, so both providers use PCM
    and the sample rate is read from the Content-Type header (`audio/pcm;rate=24000;channels=1`)."""
    if settings.ai_stub:
        return stub.speech(text)
    response = await client.audio.speech.with_raw_response.create(
        model=model, voice=voice, input=text, response_format="pcm"
    )
    params = dict(
        part.strip().split("=", 1) for part in response.headers.get("content-type", "").split(";")[1:] if "=" in part
    )
    return pcm_to_wav(response.content, int(params.get("rate", 24000)), int(params.get("channels", 1)))


def pcm_to_wav(pcm: bytes, rate: int, channels: int = 1) -> bytes:
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm)
    return buffer.getvalue()
