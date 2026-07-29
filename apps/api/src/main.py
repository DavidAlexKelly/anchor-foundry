"""API entrypoint (spec §7 apps/api). ALB health checks hit /api/health
(unauthenticated - it reveals nothing but liveness); every other route
requires a validated Cognito JWT via the auth middleware dependencies.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from fastapi.responses import JSONResponse
from starlette.requests import Request as StarletteRequest

from .lib.config import get_settings
from .lib.db import dispose_engine, get_engine
from .services.connectors import ConnectorConfigError
from .services.dataset_engine import DatasetEngineError
from .services.datasets import SCHEMA_POLICY_SQLSTATE
from .services import instance_store
from .services.orgs import Boto3CognitoGateway
from .services.secrets import Boto3SecretsGateway
from .services.storage import S3StorageGateway, StorageKeyError
from .routes import actions as action_routes
from .routes import auth as auth_routes
from .routes import bootstrap as bootstrap_routes
from .routes import canvas as canvas_routes
from .routes import connections as connection_routes
from .routes import datasets as dataset_routes
from .routes import models as model_routes
from .routes import objects as object_routes
from .routes import org as org_routes
from .routes import projects as project_routes
from .routes import workspaces as workspace_routes


def _wire_production_gateways() -> None:
    """Swap in real AWS-backed gateways when running in a deployed stack.
    S3_DATA_BUCKET is only ever set there (services.ts's commonEnv); local
    dev and every test fixture never set it and keep the in-memory/local
    defaults each route module already falls back to - same signal-based
    selection as the worker's own gateway_from_env(). Found missing
    entirely during real deploy validation (STATUS.md §17): nothing had
    ever called these configure_* functions with a real gateway, so
    connection credentials only ever lived in process memory and invites
    never created real Cognito users on any deployed stack until now."""
    bucket = os.environ.get("S3_DATA_BUCKET")
    if not bucket:
        return
    region = os.environ.get("AWS_REGION", "")
    settings = get_settings()
    dataset_routes.configure_storage_gateway(S3StorageGateway(bucket, region))
    connection_routes.configure_secrets_gateway(Boto3SecretsGateway(region))
    org_routes.configure_cognito_gateway(
        Boto3CognitoGateway(settings.cognito_user_pool_id, region)
    )
    bootstrap_routes.configure_cognito_gateway(
        Boto3CognitoGateway(settings.cognito_user_pool_id, region)
    )
    # Roadmap Objects item 1: installs the OpenSearch instance store when the
    # deployment has one, leaving every other environment on the Postgres
    # fallback. gateway_from_env() returns None when OPENSEARCH_ENDPOINT /
    # OPENSEARCH_SECRET_ARN are unset, and configure_instance_store(None) is
    # exactly "keep using Postgres".
    instance_store.configure_instance_store(instance_store.gateway_from_env())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Platform API",
        docs_url=None,  # no public API explorer on a data platform (§10)
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    # Same-origin deployment (CloudFront → ALB → web+api); CORS is therefore
    # closed by default. Localhost origin allowed only for dev builds.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=False,  # bearer tokens, not cookies
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.get("/api/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok"}


    @app.exception_handler(ConnectorConfigError)
    async def connector_config_error(
        request: StarletteRequest, exc: ConnectorConfigError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(DatasetEngineError)
    async def dataset_engine_error(
        request: StarletteRequest, exc: DatasetEngineError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(StorageKeyError)
    async def storage_key_error(request: StarletteRequest, exc: StorageKeyError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(DBAPIError)
    async def database_constraint_error(
        request: StarletteRequest, exc: DBAPIError
    ) -> JSONResponse:
        """Migration 0023 enforces a dataset's schema policy in a trigger, so
        the refusal arrives here as a database error rather than from a
        service. It carries its own SQLSTATE precisely so it can be told
        apart from every other constraint on the table; anything else is a
        genuine server fault and is re-raised to the 500 handler unchanged."""
        original = getattr(exc, "orig", None)
        if getattr(original, "sqlstate", None) != SCHEMA_POLICY_SQLSTATE:
            raise exc
        diag = getattr(original, "diag", None)
        detail = getattr(diag, "message_primary", None) or str(original).splitlines()[0]
        hint = getattr(diag, "message_hint", None)
        return JSONResponse(
            status_code=422,
            content={"detail": detail if not hint else f"{detail} - {hint}"},
        )

    @app.exception_handler(ValueError)
    async def service_value_error(request: StarletteRequest, exc: ValueError) -> JSONResponse:
        # Service-layer input rejections (bad role names, XOR violations) are
        # client errors; the message is written to be user-safe.
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    prefix = "/api"
    app.include_router(auth_routes.router, prefix=prefix)
    app.include_router(org_routes.router, prefix=prefix)
    app.include_router(workspace_routes.router, prefix=prefix)
    app.include_router(project_routes.router, prefix=prefix)
    app.include_router(connection_routes.router, prefix=prefix)
    app.include_router(dataset_routes.router, prefix=prefix)
    app.include_router(model_routes.router, prefix=prefix)
    app.include_router(model_routes.project_router, prefix=prefix)
    app.include_router(object_routes.router, prefix=prefix)
    app.include_router(object_routes.project_router, prefix=prefix)
    app.include_router(action_routes.router, prefix=prefix)
    app.include_router(action_routes.project_router, prefix=prefix)
    app.include_router(canvas_routes.router, prefix=prefix)
    app.include_router(canvas_routes.published_router, prefix=prefix)
    app.include_router(bootstrap_routes.router, prefix=prefix)

    _wire_production_gateways()
    return app


app = create_app()
