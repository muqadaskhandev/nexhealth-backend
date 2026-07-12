"""Application settings, loaded from environment / .env.

All configuration lives here so the rest of the app never reads os.environ
directly. Secrets (JWT signing key, OAuth client secrets, DB URL) are supplied
via environment variables and are never hard-coded.
"""
from __future__ import annotations

import ssl
from functools import lru_cache
from typing import Literal

import certifi
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OAuthProvider(BaseSettings):
    client_id: str = ""
    client_secret: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Runtime
    environment: Literal["development", "production"] = "development"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://nexhealth:nexhealth@localhost:5432/nexhealth"
    # Require TLS to the database. Leave false for a local Postgres (no SSL);
    # set true for managed Postgres (Supabase, AWS RDS) which mandate SSL.
    db_ssl: bool = False

    @property
    def db_connect_args(self) -> dict:
        """asyncpg connect args derived from settings (e.g. SSL)."""
        if not self.db_ssl:
            return {}
        # Local dev on some networks fails CA verification against Supabase's
        # pooler cert chain; relax verification only outside production.
        if self.debug and not self.is_production:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return {"ssl": ctx}
        ctx = ssl.create_default_context(cafile=certifi.where())
        return {"ssl": ctx}

    # JWT / sessions
    jwt_secret: str = "insecure-dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    password_reset_ttl_minutes: int = 30

    # Cookies
    cookie_domain: str | None = None
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # CORS + URLs. Stored as a raw comma-separated string to avoid the JSON
    # decoding pydantic-settings applies to list-typed env vars; exposed as a
    # parsed list via `cors_origins`.
    cors_origins_raw: str = Field(default="http://localhost:5173", alias="CORS_ORIGINS")
    frontend_url: str = "http://localhost:5173"
    backend_url: str = "http://localhost:8000"

    # OAuth providers
    google_client_id: str = ""
    google_client_secret: str = ""
    azure_tenant_id: str = "common"
    azure_client_id: str = ""
    azure_client_secret: str = ""
    okta_domain: str = ""
    okta_client_id: str = ""
    okta_client_secret: str = ""

    # Seed
    seed_admin_email: str = "admin@betterdental.com"
    seed_admin_password: str = "ChangeMe123!"
    seed_super_admin_email: str = "platform@nexhealth.dev"
    seed_super_admin_password: str = "ChangeMe123!"

    # AWS SES
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    ses_from_email: str = "noreply@example.com"
    ses_from_name: str = "NextHealth"
    # When false, emails are printed to the server log (local dev).
    ses_enabled: bool = False

    invite_ttl_hours: int = 72

    # EHR Synchronizer — encrypt credentials at rest (Fernet key, base64 url-safe 32 bytes).
    ehr_credentials_key: str = ""
    # Must be false in production — only real EHR APIs are called.
    ehr_sync_demo_mode: bool = False

    # Seed only platform accounts + empty practice shell. No Simpson/demo patients.
    seed_demo_data: bool = False

    # Open Dental — platform developer key (one per NextHealth); customer key is per clinic.
    open_dental_developer_key: str = ""
    open_dental_api_base_url: str = "https://api.opendental.com"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def validate_for_production(self) -> None:
        """Fail fast on insecure config when running in production."""
        problems: list[str] = []
        if self.jwt_secret in ("", "insecure-dev-secret-change-me", "CHANGE_ME_use_a_long_random_string"):
            problems.append("JWT_SECRET must be set to a strong random value")
        if len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must be at least 32 characters")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production (HTTPS only)")
        if self.cookie_samesite == "none" and not self.cookie_secure:
            problems.append("COOKIE_SAMESITE=none requires COOKIE_SECURE=true")
        if problems:
            raise RuntimeError(
                "Insecure production configuration:\n  - " + "\n  - ".join(problems)
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production:
        settings.validate_for_production()
    return settings


settings = get_settings()
