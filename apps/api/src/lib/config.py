"""API configuration. All values come from the environment (populated in the
deployed stack from CDK outputs and Secrets Manager — never hard-coded)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    # postgresql+psycopg://platform_app:...@host/platform — the RLS-subject role.
    database_url: str
    # Cognito verification inputs (spec §9 "JWT Validation").
    cognito_region: str = "eu-west-2"
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    # Overridable for tests; production derives from region + pool id.
    cognito_jwks_url: str = ""
    cognito_issuer: str = ""

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
    return Settings()  # type: ignore[call-arg]  # env-populated
