# Anchor control plane. Unlike the three service images, this one does NOT run
# in a customer's account - it runs in the vendor's, in front of the customer
# registry, and its job is the onboarding surface (ROADMAP section 7) plus the
# provisioning it drives.
#
# It needs more than the others at runtime: `cdk deploy` is a subprocess, so
# Node and the CDK CLI are in the image, and the repo's own `infra/cdk`
# directory has to be mounted or copied in (CDK_DIR). Building a customer
# stack from a container that cannot run CDK would be a control plane that can
# take an order and not fill it.
#
# Same platform pin, same reason, as the other three: `docker build` with no
# --platform defaults to the host's architecture, and an arm64 image on an
# x86_64 task fails before any application code runs. Pinning here means every
# build is correct whatever machine it was built on - but note the pin only
# fixes the *base* image; pass `--platform=linux/amd64` on the build command
# too (STATUS.md §20, tenth bug).
FROM --platform=linux/amd64 python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CDK_DIR=/app/infra/cdk

WORKDIR /app

# Node + the CDK CLI: the provisioner shells out to `cdk deploy`.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g aws-cdk@2 \
 && apt-get purge -y gnupg && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

COPY apps/control-plane/requirements.txt .
RUN pip install -r requirements.txt

COPY apps/control-plane/src ./src
# The CDK app itself, so `cdk deploy` has something to synthesise. Built from
# the repo root for this reason - the other three images build from their own
# directory because they need nothing outside it.
COPY infra/cdk ./infra/cdk
RUN cd infra/cdk && npm ci --omit=dev

RUN useradd --create-home --uid 10001 apprunner
USER apprunner

EXPOSE 8400
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8400/health', timeout=2).status==200 else 1)"

CMD ["python", "-m", "src.cli", "serve", "--host", "0.0.0.0", "--port", "8400"]
