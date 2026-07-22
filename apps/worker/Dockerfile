# Anchor worker. Dagster daemon + code location in one container for the
# single-tenant deployment size this platform targets (spec §6); split into
# separate daemon/webserver/code-location services when scale demands it.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DAGSTER_HOME=/opt/dagster/home

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src ./src
ENV PYTHONPATH=/app/src

RUN mkdir -p /opt/dagster/home && \
    printf 'telemetry:\n  enabled: false\n' > /opt/dagster/home/dagster.yaml && \
    useradd --create-home --uid 10001 apprunner && \
    chown -R apprunner /opt/dagster
USER apprunner

CMD ["dagster", "dev", "-m", "anchor_worker.definitions", "--host", "0.0.0.0", "--port", "3030"]
