from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Repo-root .env (shared with Compose) first, backend/.env after it.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    # Built from postgres_password for local runs; Compose passes DATABASE_URL explicitly.
    database_url: str = ""
    postgres_password: str = "audimax"

    # Single user, created on first start if no users exist.
    admin_username: str = "admin"
    admin_password: str = ""
    cookie_secure: bool = False  # true behind HTTPS (docker-compose.yml sets it; the local override does not)
    session_days: int = 30

    # Offline mode: deterministic fake transcription/LLM/translation, no network, no cost.
    ai_stub: bool = False

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    transcribe_model: str = "microsoft/mai-transcribe-2"
    # Generation: Gemini primary, Claude fallback (OpenRouter tries them in order).
    llm_models: str = "google/gemini-3.8-flash,anthropic/claude-sonnet-5.5"
    storage_dir: str = "data/storage"  # used when R2 is not configured
    # Translation: "llm" (the models above, via OpenRouter) or "deepl" (needs DEEPL_API_KEY).
    translator: str = "llm"
    deepl_api_key: str = ""

    # Live subtitles go straight to OpenAI's realtime transcription (OpenRouter has no streaming STT).
    openai_api_key: str = ""
    live_transcribe_model: str = "gpt-live-transcribe"
    live_language: str = "de"

    # Cloudflare R2 (S3-compatible). Empty => storage falls back to backend/data/.
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "audimax"

    @model_validator(mode="after")
    def _default_database_url(self) -> "Settings":
        if not self.database_url:
            self.database_url = (
                f"postgresql+psycopg://audimax:{self.postgres_password}@localhost:5432/audimax"
            )
        return self

    @property
    def llm_model_list(self) -> list[str]:
        return [m.strip() for m in self.llm_models.split(",") if m.strip()]

    @property
    def procrastinate_dsn(self) -> str:
        return self.database_url.replace("+psycopg", "")

    @property
    def r2_endpoint_url(self) -> str:
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"

    @property
    def r2_configured(self) -> bool:
        values = (self.r2_account_id, self.r2_access_key_id, self.r2_secret_access_key)
        # "<placeholder>" values from .env.example count as unset.
        return all(v and not v.startswith("<") for v in values)


settings = Settings()
