"""API entrypoint (spec §7 apps/api). ALB health checks hit /api/health
(unauthenticated - it reveals nothing but liveness); every other route
requires a validated Cognito JWT via the auth middleware dependencies.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import psycopg
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from fastapi.responses import JSONResponse
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES, GZipMiddleware
from starlette.requests import Request as StarletteRequest

from .lib.body_limit import BodyLimit
from .lib.security_headers import SecurityHeaders
from .lib.config import get_settings
from .lib.db import HEALTH_DEADLINE_S, dispose_engine, get_engine, get_health_engine
from .lib import long_work
from .lib.errors import BreakingChangeError
from .lib import duck, observability
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
from .routes import client_errors as client_error_routes
from .routes import kiosk as kiosk_routes
from .routes import series_analyses as series_analysis_routes
from .routes import code as code_routes
from .routes import connections as connection_routes
from .routes import datasets as dataset_routes
from .routes import models as model_routes
from .routes import notifications as notification_routes
from .routes import exports as export_routes
from .routes import functions as function_routes
from .routes import webhooks as webhook_routes
from .routes import objects as object_routes
from .routes import org as org_routes
from .routes import projects as project_routes
from .routes import repositories as repository_routes
from .routes import resources as resource_routes
from .routes import tags as tag_routes
from .routes import listeners as listener_routes
from .routes import oidc as oidc_routes
from .routes import oauth as oauth_routes
from .routes import workspaces as workspace_routes

#: Postgres's `query_canceled`, which `statement_timeout` raises (§833).
QUERY_CANCELED_SQLSTATE = "57014"
#: unique_violation, serialization_failure, deadlock_detected (§862).
CONCURRENT_CHANGE_SQLSTATES = frozenset({"23505", "40001", "40P01"})
#: admin_shutdown, crash_shutdown, cannot_connect_now: the database stopping
#: or starting, as a failover or a maintenance window does (§951).
DATABASE_RESTARTING_SQLSTATES = frozenset({"57P01", "57P02", "57P03"})

#: **Not `anchor.error`** (§951), whose every line is the unhandled-error
#: alarm, there for faults in the code. A database that is restarting or a
#: pool with no connection free is neither; the 5xx-rate alarm is the one for
#: it lasting.
unavailable_log = logging.getLogger("anchor.unavailable")
UNAVAILABLE_DETAIL = "the database is briefly unavailable - try again in a moment"


def database_unavailable(exc: DBAPIError) -> bool:
    """A database the API cannot use right now, rather than a statement it
    got wrong: restarting, or the connection gone before the server said
    anything (no SQLSTATE at all)."""
    original = getattr(exc, "orig", None)
    sqlstate = getattr(original, "sqlstate", None)
    if sqlstate in DATABASE_RESTARTING_SQLSTATES or (sqlstate or "").startswith("08"):
        return True
    # Any OperationalError, its subclasses included: a connect that timed out
    # is psycopg's ConnectionTimeout (§958), which matching the class by name
    # missed.
    return exc.connection_invalidated or (
        sqlstate is None and isinstance(original, psycopg.OperationalError))


def _unavailable(reason: str, detail: str = UNAVAILABLE_DETAIL,
                 what: str = "database") -> JSONResponse:
    unavailable_log.warning(f"{what} unavailable", extra={"fields": {"reason": reason}})
    return JSONResponse(status_code=503, content={"detail": detail},
                        headers={"Retry-After": "5"})


#: What a request that needed the object search service says when it did not
#: answer (§978).
SEARCH_UNAVAILABLE_DETAIL = "object search is briefly unavailable - try again in a moment"

try:  # the OpenSearch client is optional: a stack without a domain never imports it
    from opensearchpy.exceptions import ConnectionError as SearchUnreachable
except ImportError:  # pragma: no cover
    SearchUnreachable = None

#: What a request that needed AWS - the data bucket, Secrets Manager,
#: Cognito - says when it did not answer in time (§979).
AWS_UNAVAILABLE_DETAIL = ("a service the platform stores its data with is briefly unavailable - "
                          "try again in a moment")

try:  # boto3 is not installed in every development environment
    from botocore.exceptions import ConnectionError as AwsUnreachable
    from botocore.exceptions import ReadTimeoutError as AwsTimedOut
except ImportError:  # pragma: no cover
    AwsUnreachable = AwsTimedOut = None


#: Set by the ECS agent in every task (it names the task metadata endpoint), and
#: by nothing in development or tests.
ECS_MARKER = "ECS_CONTAINER_METADATA_URI_V4"


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
        # **Not on ECS, though** (§844). There, a missing bucket means the task
        # definition lost its variables, and carrying on would serve requests
        # with connection secrets held in this process's memory - which a
        # second API task (§841) does not share - and files written to the
        # task's own disk. Refusing to start is the failure an operator sees;
        # the other is the one a customer finds.
        if os.environ.get(ECS_MARKER):
            raise RuntimeError(
                "running on ECS without S3_DATA_BUCKET: refusing to start on the "
                "in-memory secrets and local-disk storage meant for development"
            )
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
    # A sync that outlasted its request (§967) gets the time the task has.
    await long_work.settle()
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
        # Stays False now that a session cookie exists, and matters more for
        # it: the browser session is same-origin (CloudFront in production,
        # Next's /api rewrite in dev), so no legitimate caller needs a
        # credentialed cross-origin request - and refusing them is what makes
        # the X-Anchor-Session header a real CSRF barrier rather than a
        # convention (middleware/auth.py).
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Every request body bounded before anything reads it (§832). Inside the
    # observability middleware below, so a refusal still has a request id and
    # an access line.
    app.add_middleware(BodyLimit)
    # And every response, a refusal from the one above included, says not to
    # sniff it, not to frame it elsewhere, and how much of a referrer to send
    # (§836).
    app.add_middleware(SecurityHeaders)
    # Compressed on the way out (§919). CloudFront compresses only what it may
    # cache, and nothing the API answers is cacheable, so every preview, graph
    # and object set crossed the internet as plain JSON - several times the
    # bytes, on a person's connection, every time. Level 6 is gzip's own
    # default and most of 9's saving for a fraction of its time; parquet is
    # compressed already and left alone.
    app.add_middleware(
        GZipMiddleware,
        minimum_size=1024,
        compresslevel=6,
        exclude_content_types=(*DEFAULT_EXCLUDED_CONTENT_TYPES, "application/vnd.apache.parquet"),
    )

    # Request ids, access lines, metrics and the unhandled-error record (§802).
    # After CORS, so it is the outer of the two and times the whole request.
    observability.install(app)

    @app.get("/api/health", include_in_schema=False)
    async def health() -> JSONResponse:
        # §956: on its own connection, so a pool every request is using does
        # not read as a broken task; within the load balancer's wait, so a
        # database that does not answer is a 503 rather than a timeout.
        try:
            async with asyncio.timeout(HEALTH_DEADLINE_S):
                async with get_health_engine().connect() as conn:
                    await conn.execute(text("SELECT 1"))
        except (TimeoutError, DBAPIError) as exc:
            unavailable_log.warning("health check could not reach the database",
                                    extra={"fields": {"reason": type(exc).__name__}})
            return JSONResponse(status_code=503, content={"status": "database unavailable"})
        return JSONResponse(content={"status": "ok"})


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

    @app.exception_handler(duck.Busy)
    async def duck_busy(request: StarletteRequest, exc: duck.Busy) -> JSONResponse:
        # §911: every DuckDB slot stayed taken past the wait. Busy, not
        # broken: a retry in a moment is the right answer, and says so.
        return JSONResponse(status_code=503, content={"detail": str(exc)},
                            headers={"Retry-After": "5"})

    @app.exception_handler(PoolTimeout)
    async def pool_exhausted(request: StarletteRequest, exc: PoolTimeout) -> JSONResponse:
        # §951: every pooled connection stayed taken for the pool's whole
        # wait. Busy, as `duck.Busy` is, not broken.
        return _unavailable("no pooled connection came free")

    if AwsUnreachable is not None:
        async def aws_unreachable(request: StarletteRequest, exc: Exception) -> JSONResponse:
            # §979: §970 holds the platform's AWS calls to seconds, so a stall
            # ends in botocore's connect or read timeout rather than minutes
            # later - and then reached the person as an unhandled 500. A
            # moment's absence, as the database's is (§951). An AWS refusal
            # (`ClientError`) is not this and is left to whoever asked.
            return _unavailable(type(exc).__name__, AWS_UNAVAILABLE_DETAIL, "aws")

        app.add_exception_handler(AwsUnreachable, aws_unreachable)
        app.add_exception_handler(AwsTimedOut, aws_unreachable)

    if SearchUnreachable is not None:
        @app.exception_handler(SearchUnreachable)
        async def search_unreachable(request: StarletteRequest, exc: Exception) -> JSONResponse:
            # §978: the search domain refused the connection, or took longer
            # than the client waits - a domain restarting, a blue/green change
            # of its nodes. A moment's absence, as a database failover is
            # (§951), rather than an unhandled error that pages somebody.
            # Its timeout included (`ConnectionTimeout` is one).
            return _unavailable(type(exc).__name__, SEARCH_UNAVAILABLE_DETAIL, "object search")

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
        if database_unavailable(exc):
            # §951: a failover or a restart. Not a fault in the code, and
            # what a retry in a moment is for.
            return _unavailable(str(original).strip().splitlines()[0] if str(original).strip()
                                else type(original).__name__)
        if getattr(original, "sqlstate", None) == QUERY_CANCELED_SQLSTATE:
            # `statement_timeout` (§833): the request asked for more than one
            # statement may take. Not a fault in the code, and not the
            # caller's input either, so neither a 500 nor a 4xx.
            seconds = get_settings().statement_timeout_ms / 1000
            return JSONResponse(
                status_code=503,
                content={"detail": f"the database stopped this request after {seconds:g} "
                                   "seconds - narrow what it asks for and try again"},
            )
        if getattr(original, "sqlstate", None) in CONCURRENT_CHANGE_SQLSTATES:
            # **Two requests changing one thing at once** (§862). A version
            # number both took, a name both chose, two writers locking in
            # opposite orders: the loser's statement fails, and the person
            # behind it was answered with an anonymous 500. Nothing is wrong
            # with the code or the input - the same request a moment later
            # succeeds - so it is a conflict, said as one.
            # A unique violation can also be a plain duplicate a service did
            # not check for, so its sentence covers both; the constraint name
            # says which.
            diag = getattr(original, "diag", None)
            constraint = getattr(diag, "constraint_name", None)
            what = ("this would duplicate something that already exists, possibly made "
                    "by another request at the same time"
                    if original.sqlstate == "23505"
                    else "this was changed by another request at the same time")
            return JSONResponse(status_code=409, content={"detail": (
                what + (f" ({constraint})" if constraint else "") + " - reload and try again")})
        if getattr(original, "sqlstate", None) != SCHEMA_POLICY_SQLSTATE:
            raise exc
        diag = getattr(original, "diag", None)
        detail = getattr(diag, "message_primary", None) or str(original).splitlines()[0]
        hint = getattr(diag, "message_hint", None)
        return JSONResponse(
            status_code=422,
            content={"detail": detail if not hint else f"{detail} - {hint}"},
        )

    @app.exception_handler(BreakingChangeError)
    async def breaking_change_error(
        request: StarletteRequest, exc: BreakingChangeError
    ) -> JSONResponse:
        """A 409 that carries its reasons as data (roadmap Objects item 5).

        `detail` stays a plain string, so every existing client that reads
        `detail` still gets a usable sentence; `impacts` is an additional
        top-level key holding the same information as a list, because a
        warning listing four affected consumers is a list in the UI and
        parsing it back out of prose would be absurd.
        """
        # jsonable_encoder, not the raw list: the impacts carry consumer UUIDs
        # straight off the row, which json.dumps refuses.
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder({"detail": exc.detail, "impacts": exc.impacts}),
        )

    @app.exception_handler(ValueError)
    async def service_value_error(request: StarletteRequest, exc: ValueError) -> JSONResponse:
        # Service-layer input rejections (bad role names, XOR violations) are
        # client errors; the message is written to be user-safe.
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    # The one prefix every router is included under, which the access log and
    # the metrics name routes by (`observability.route_template`, §837).
    prefix = observability.API_PREFIX
    app.include_router(auth_routes.router, prefix=prefix)
    app.include_router(client_error_routes.router, prefix=prefix)
    app.include_router(org_routes.router, prefix=prefix)
    app.include_router(workspace_routes.router, prefix=prefix)
    app.include_router(project_routes.router, prefix=prefix)
    app.include_router(resource_routes.router, prefix=prefix)
    app.include_router(resource_routes.resolve_router, prefix=prefix)
    app.include_router(resource_routes.search_router, prefix=prefix)
    app.include_router(resource_routes.favourites_router, prefix=prefix)
    app.include_router(tag_routes.router, prefix=prefix)
    app.include_router(tag_routes.resource_router, prefix=prefix)
    app.include_router(listener_routes.router, prefix=prefix)
    app.include_router(listener_routes.ingress_router, prefix=prefix)
    # §599: p.391's identity provider documents, public like the listener
    # ingress above.
    app.include_router(oidc_routes.router, prefix=prefix)
    app.include_router(oauth_routes.router, prefix=prefix)
    app.include_router(repository_routes.router, prefix=prefix)
    app.include_router(connection_routes.router, prefix=prefix)
    app.include_router(dataset_routes.router, prefix=prefix)
    app.include_router(model_routes.router, prefix=prefix)
    app.include_router(model_routes.project_router, prefix=prefix)
    app.include_router(object_routes.router, prefix=prefix)
    app.include_router(object_routes.project_router, prefix=prefix)
    app.include_router(series_analysis_routes.router, prefix=prefix)
    app.include_router(series_analysis_routes.workspace_router, prefix=prefix)
    app.include_router(action_routes.router, prefix=prefix)
    app.include_router(action_routes.project_router, prefix=prefix)
    app.include_router(canvas_routes.router, prefix=prefix)
    app.include_router(canvas_routes.published_router, prefix=prefix)
    app.include_router(kiosk_routes.org_router, prefix=prefix)
    app.include_router(kiosk_routes.module_router, prefix=prefix)
    app.include_router(kiosk_routes.session_router, prefix=prefix)
    app.include_router(code_routes.router, prefix=prefix)
    app.include_router(notification_routes.router, prefix=prefix)
    app.include_router(export_routes.router, prefix=prefix)
    app.include_router(function_routes.router, prefix=prefix)
    app.include_router(webhook_routes.router, prefix=prefix)
    app.include_router(webhook_routes.workspace_router, prefix=prefix)
    app.include_router(bootstrap_routes.router, prefix=prefix)

    _wire_production_gateways()
    return app


app = create_app()
