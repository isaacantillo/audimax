from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://audimax:audimax@localhost:5432/audimax"
    session_secret: str = "dev-only-change-me"

    openrouter_api_key: str = ""
    deepl_api_key: str = ""
    tavily_api_key: str = ""

    # Cloudflare R2 (S3-compatible). Empty => storage falls back to backend/data/.
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "audimax"

    @property
    def r2_endpoint_url(self) -> str:
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"

    @property
    def r2_configured(self) -> bool:
        values = (self.r2_account_id, self.r2_access_key_id, self.r2_secret_access_key)
        # "<placeholder>" values from .env.example count as unset.
        return all(v and not v.startswith("<") for v in values)


settings = Settings()
