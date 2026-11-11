from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Direct or pooled Postgres connection string for the Supabase project.
    # The backend connects as the table owner, so RLS does not apply to it:
    # every query in this service must scope by workspace_id explicitly.
    database_url: str

    # e.g. https://<project-ref>.supabase.co
    supabase_url: str

    # Legacy HS256 JWT secret. Leave unset to verify tokens with the project's
    # asymmetric signing keys (JWKS), which is the recommended setup.
    supabase_jwt_secret: str | None = None
    jwt_audience: str = "authenticated"

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    @property
    def jwt_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def jwks_url(self) -> str:
        return f"{self.jwt_issuer}/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
