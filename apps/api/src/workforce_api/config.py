import json
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    # Web app addresses allowed to call the API: JSON list or comma-separated. Left empty on
    # Render, the API guesses its sibling web app (workforce-api -> workforce-web).
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_origins(cls, v):
        if isinstance(v, str):
            v = v.strip()
            items = json.loads(v) if v.startswith("[") else v.split(",")
            return [str(x).strip().rstrip("/") for x in items if str(x).strip()]
        return v

    # Connected accounts (Gmail). All optional: without them, "Connect Gmail" explains
    # that the server isn't set up yet.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    # Must match the redirect URI registered in Google Cloud, e.g.
    # https://workforce-api.onrender.com/connections/google/callback
    google_redirect_uri: str | None = None
    # Other sign-in providers. One callback URL serves them all:
    #   https://<your-api>/connections/oauth/callback
    oauth_redirect_uri: str | None = None
    slack_client_id: str | None = None
    slack_client_secret: str | None = None
    # Set up / upgrade the database automatically on start (supabase/migrations).
    auto_migrate: bool = False
    migrations_dir: str | None = None
    # Render sets this for web services (https://<name>.onrender.com).
    render_external_url: str | None = None

    # This API's own public address, e.g. https://workforce-api.onrender.com
    # (Telegram sends messages for the "chat from Telegram" feature here).
    public_api_url: str | None = None
    # Chat assistant (Claude). Without a key, chat explains it isn't set up yet.
    anthropic_api_key: str | None = None
    chat_model: str = "claude-opus-5-5"
    chat_effort: str = "low"  # quick replies; real work goes to the workforce
    # Safety net until billing exists: max chat spend per workspace per day.
    chat_daily_budget_usd: float = 3.0
    chat_messages_per_minute: int = 20
    # base64 of 32 random bytes; the worker needs the same value.
    token_encryption_key: str | None = None
    # Where the OAuth callback may send the owner back to, besides cors_origins.
    # The phone app's own scheme, plus the one Expo development builds use.
    app_redirect_schemes: list[str] = Field(
        default_factory=lambda: ["workforceos://", "exp+workforce-os://"]
    )

    @model_validator(mode="after")
    def _derive_urls(self) -> "Settings":
        """Fewer things to type when deploying: work out our own address and callbacks."""
        if not self.public_api_url and self.render_external_url:
            self.public_api_url = self.render_external_url
        if not self.cors_origins:
            api = (self.render_external_url or "").rstrip("/")
            self.cors_origins = (
                [api.replace("workforce-api", "workforce-web")]
                if "workforce-api" in api
                else ["http://localhost:3000"]
            )
        base = (self.public_api_url or "").rstrip("/")
        if base and not self.google_redirect_uri and self.google_client_id:
            self.google_redirect_uri = f"{base}/connections/google/callback"
        if base and not self.oauth_redirect_uri:
            self.oauth_redirect_uri = f"{base}/connections/oauth/callback"
        return self

    def oauth_client(self, prefix: str) -> tuple[str, str, str] | None:
        """(client_id, client_secret, redirect_uri) for a provider, if set up."""
        cid = getattr(self, f"{prefix.lower()}_client_id", None)
        secret = getattr(self, f"{prefix.lower()}_client_secret", None)
        redirect = (self.google_redirect_uri if prefix == "GOOGLE" else None) or (
            self.oauth_redirect_uri
        )
        if cid and secret and redirect and self.token_encryption_key:
            return cid, secret, redirect
        return None

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
