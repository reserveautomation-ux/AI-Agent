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

    # Connected accounts (Gmail). All optional: without them, "Connect Gmail" explains
    # that the server isn't set up yet.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    # Must match the redirect URI registered in Google Cloud, e.g.
    # https://workforce-api.onrender.com/connections/google/callback
    google_redirect_uri: str | None = None
    # base64 of 32 random bytes; the worker needs the same value.
    token_encryption_key: str | None = None
    # Where the OAuth callback may send the owner back to, besides cors_origins.
    # The phone app's own scheme, plus the one Expo development builds use.
    app_redirect_schemes: list[str] = Field(
        default_factory=lambda: ["workforceos://", "exp+workforce-os://"]
    )

    @property
    def gmail_configured(self) -> bool:
        return bool(
            self.google_client_id
            and self.google_client_secret
            and self.google_redirect_uri
            and self.token_encryption_key
        )

    @property
    def jwt_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def jwks_url(self) -> str:
        return f"{self.jwt_issuer}/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
