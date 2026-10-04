# Anchor worker. Dagster daemon + code location in one container for the
# single-tenant deployment size this platform targets (spec §6); split into
# separate daemon/webserver/code-location services when scale demands it.
# Pinned explicitly: `docker build` with no --platform defaults to the
# *host's* architecture (e.g. arm64 on Apple Silicon), not Fargate's x86_64 -
# an arm64 image on an x86_64 task fails to start at all, before any
# application code runs (confirmed live: zero CloudWatch log output, ECS
# deployment circuit breaker tripped). Pinning here means every build is
# correct regardless of the machine or `docker build` flags used.
FROM --platform=linux/amd64 python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DAGSTER_HOME=/opt/dagster/home

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src ./src
ENV PYTHONPATH=/app/src

# The instance's storage settings (§883): see the file.
COPY dagster.yaml /opt/dagster/home/dagster.yaml
RUN useradd --create-home --uid 10001 apprunner && \
    chown -R apprunner /opt/dagster
USER apprunner

# The daemon alone (§883): it is what fires schedules and launches runs.
# `dagster dev` also started a web UI on 3030 that no load balancer or port
# mapping reached, and Dagster documents it as for local development.
CMD ["dagster-daemon", "run", "-m", "anchor_worker.definitions"]
