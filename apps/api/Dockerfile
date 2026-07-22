# Anchor API. Runs behind the ALB (CDK services construct); health check
# GET /api/health. Container runs as a non-root user; the image carries no
# secrets — DATABASE_URL and COGNITO_* arrive from ECS task definition
# secrets (Secrets Manager) at runtime.
FROM python:3.12-slim AS base

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
