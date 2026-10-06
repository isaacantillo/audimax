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
    cookie_secure: bool = False  # set true behind HTTPS (Caddy)
    session_days: int = 30

    # Offline mode: deterministic fake transcription/LLM/TTS/embeddings, no network, no cost.
    ai_stub: bool = False

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    transcribe_model: str = "microsoft/mai-transcribe-2"
    # Generation: Gemini primary, Claude fallback (OpenRouter tries them in order).
    llm_models: str = "google/gemini-3.8-flash,anthropic/claude-sonnet-5.5"
    # name:model:voice, first one that voices a whole lecture wins; never mixed within a lecture.
    tts_providers: str = (
        "gemini:google/gemini-3.1-flash-tts-preview:Charon,"
        "qwen:qwen/qwen-audio-3.0-tts-plus:longanlufeng"
    )
    embedding_model: str = "openai/text-embedding-3-large"
    embedding_dims: int = 1536  # pgvector HNSW caps at 2000 dims for `vector`
    storage_dir: str = "data/storage"  # used when R2 is not configured
    deepl_api_key: str = ""
    tavily_api_key: str = ""

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
    def tts_provider_list(self) -> list[tuple[str, str, str]]:
        return [tuple(p.strip().split(":", 2)) for p in self.tts_providers.split(",") if p.strip()]  # type: ignore[misc]

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
