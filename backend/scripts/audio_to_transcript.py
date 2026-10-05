from deepl.api_data import TextResult
import os
import subprocess
import tempfile
from pathlib import Path

from openai import OpenAI
from deepl import DeepLClient
from dotenv import load_dotenv

load_dotenv()

FILE = "psy_de"
MODEL="microsoft/mai-transcribe-2"

DATA_FOLDER = Path("data")
RESULTS_FOLDER = DATA_FOLDER / "results"
RESULTS_FOLDER.mkdir(parents=True, exist_ok=True)


openai_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

deepl_auth_key= os.getenv(key="DEEPL_API_KEY")
if deepl_auth_key is None:
    raise Exception("No DeepL API Key")

deepl_client = DeepLClient(deepl_auth_key)

# MAI-Transcribe 2 rejects m4a/aac uploads with a provider 400; these are accepted.
SUPPORTED_UPLOAD_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg"}


def to_supported_audio(path: Path) -> Path:
    """Transcode to mono 16 kHz mp3 unless the provider already accepts the file."""
    if path.suffix.lower() in SUPPORTED_UPLOAD_SUFFIXES:
        return path

    converted = Path(tempfile.gettempdir()) / f"{path.stem}.mp3"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(path),
         "-ac", "1", "-ar", "16000", str(converted)],
        check=True,
    )
    return converted


def transcribe(path: Path):
    """Transcribe with segment-level timestamps (verbose_json)."""
    with to_supported_audio(path).open("rb") as f:
        return openai_client.audio.transcriptions.create(
            model=MODEL,
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )


if __name__ == "__main__":
    result = transcribe(DATA_FOLDER / f"{FILE}.m4a")

    print("Languague:", result.language)
    print("Duration:", result.duration)


    (RESULTS_FOLDER / f"{FILE}.txt").write_text(result.text, encoding="utf-8")
    (RESULTS_FOLDER / f"{FILE}.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )

    if result.language.lower() not in ("english", "en"):
        translation: TextResult | list[TextResult] = deepl_client.translate_text(
            result.text, target_lang="en-US"
        )
        translated_text = (
            translation.text if isinstance(translation, TextResult) else translation[0].text
        )
        (RESULTS_FOLDER / f"{FILE}_translated.txt").write_text(translated_text, encoding="utf-8")