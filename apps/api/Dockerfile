# Anchor API. Runs behind the ALB (CDK services construct); health check
# GET /api/health. Container runs as a non-root user; the image carries no
# secrets - DATABASE_URL and COGNITO_* arrive from ECS task definition
# secrets (Secrets Manager) at runtime.
# Pinned explicitly: `docker build` with no --platform defaults to the
# *host's* architecture (e.g. arm64 on Apple Silicon), not Fargate's x86_64 -
# an arm64 image on an x86_64 task fails to start at all, before any
# application code runs (confirmed live: zero CloudWatch log output, ECS
# deployment circuit breaker tripped). Pinning here means every build is
# correct regardless of the machine or `docker build` flags used.
# The tag says what it is; the digest says which one (§818). Bump both together
# with scripts/pin-images.sh.
FROM --platform=linux/amd64 python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src ./src

RUN useradd --create-home --uid 10001 apprunner
USER apprunner

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status==200 else 1)"

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
