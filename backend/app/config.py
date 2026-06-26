from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, loaded from environment variables (or a .env file)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://ideabrd:ideabrd@localhost:5432/ideabrd"

    @field_validator("database_url")
    @classmethod
    def _ensure_async_driver(cls, v: str) -> str:
        """Accept CloudNativePG's plain libpq URI and force the asyncpg driver.

        CNPG's generated `uri` looks like ``postgresql://user:pass@host:5432/db``;
        SQLAlchemy's async engine needs the ``postgresql+asyncpg://`` scheme.
        """
        if v.startswith("postgresql+"):
            return v
        if v.startswith("postgresql://"):
            return "postgresql+asyncpg://" + v[len("postgresql://") :]
        if v.startswith("postgres://"):
            return "postgresql+asyncpg://" + v[len("postgres://") :]
        return v

    # Session cookie signing secret
    session_secret: str = "dev-insecure-session-secret-change-me"
    cookie_secure: bool = False

    # Google OIDC
    google_client_id: str = ""
    google_client_secret: str = ""
    oauth_redirect_url: str = "http://localhost:8000/api/auth/callback"
    google_metadata_url: str = (
        "https://accounts.google.com/.well-known/openid-configuration"
    )

    # Where to send the browser after a successful login (the SPA origin)
    frontend_url: str = "http://localhost:5173"

    # GitHub
    github_token: str = ""
    github_api_base: str = "https://api.github.com"

    @property
    def auth_enabled(self) -> bool:
        """True when Google OIDC is configured. When false, a dev login is used instead."""
        return bool(self.google_client_id and self.google_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
