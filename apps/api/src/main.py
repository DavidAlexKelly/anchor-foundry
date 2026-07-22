"""API entrypoint (spec §7 apps/api). ALB health checks hit /api/health
(unauthenticated — it reveals nothing but liveness); every other route
requires a validated Cognito JWT via the auth middleware dependencies.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from fastapi.responses import JSONResponse
from starlette.requests import Request as StarletteRequest

from .lib.db import dispose_engine, get_engine
from .services.connectors import ConnectorConfigError
from .services.dataset_engine import DatasetEngineError
from .services.storage import StorageKeyError
from .routes import actions as action_routes
from .routes import auth as auth_routes
from .routes import connections as connection_routes
from .routes import datasets as dataset_routes
from .routes import models as model_routes
from .routes import objects as object_routes
from .routes import org as org_routes
from .routes import projects as project_routes
from .routes import workspaces as workspace_routes


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
    app.include_router(object_routes.router, prefix=prefix)
    app.include_router(object_routes.project_router, prefix=prefix)
    app.include_router(action_routes.router, prefix=prefix)
    app.include_router(action_routes.project_router, prefix=prefix)
    return app


app = create_app()
