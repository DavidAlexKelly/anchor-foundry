"""API configuration. All values come from the environment (populated in the
deployed stack from CDK outputs and Secrets Manager - never hard-coded)."""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    # postgresql+psycopg://platform_app:...@host/platform — the RLS-subject role.
    # Deployed stacks don't set DATABASE_URL directly (the password lives in
    # Secrets Manager, resolved to its own env var, not embedded in a
    # pre-built URL) — see the assembly fallback below. Local dev/tests set
    # DATABASE_URL directly instead, so that path is unchanged.
    database_url: str = ""
    database_host: str = ""
    database_port: str = "5432"
    database_name: str = "platform"
    database_username: str = ""
    database_password: str = ""
    # Cognito verification inputs (spec §9 "JWT Validation").
    cognito_region: str = "eu-west-2"
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    # Overridable for tests; production derives from region + pool id.
    cognito_jwks_url: str = ""
    cognito_issuer: str = ""

    @model_validator(mode="after")
    def _assemble_database_url(self) -> "Settings":
        if not self.database_url:
            if not (self.database_host and self.database_username and self.database_password):
                raise ValueError(
                    "DATABASE_URL, or DATABASE_HOST/DATABASE_USERNAME/DATABASE_PASSWORD, must be set"
                )
            self.database_url = (
                f"postgresql+psycopg://{self.database_username}:"
                f"{quote(self.database_password, safe='')}"
                f"@{self.database_host}:{self.database_port}/{self.database_name}"
                f"?sslmode=require"
            )
        return self

    @property
    def issuer(self) -> str:
        if self.cognito_issuer:
            return self.cognito_issuer
        return f"https://cognito-idp.{self.cognito_region}.amazonaws.com/{self.cognito_user_pool_id}"

    @property
    def jwks_url(self) -> str:
        if self.cognito_jwks_url:
            return self.cognito_jwks_url
        return f"{self.issuer}/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
