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

    openrouter_api_key: str = ""
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
    def r2_endpoint_url(self) -> str:
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"

    @property
    def r2_configured(self) -> bool:
        values = (self.r2_account_id, self.r2_access_key_id, self.r2_secret_access_key)
        # "<placeholder>" values from .env.example count as unset.
        return all(v and not v.startswith("<") for v in values)


settings = Settings()
