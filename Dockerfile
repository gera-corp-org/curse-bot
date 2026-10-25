# syntax=docker/dockerfile:1

# ---------- dependencies and bytecode ----------
# This stage runs on the build platform: every dependency is pure Python, so one set fits
# both amd64 and arm64, and the final stage runs no RUN and builds for arm64 without QEMU
# emulation. Base images are pinned by digest; Dependabot keeps them current.
FROM --platform=$BUILDPLATFORM python:3.13-slim-trixie@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962 AS deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
# requirements.txt is an export of uv.lock (`uv export --no-dev --no-emit-project --no-header`), with hashes.
COPY requirements.txt .
RUN pip install --require-hashes --no-deps --only-binary=:all: --target /deps -r requirements.txt \
 && rm -rf /deps/bin
COPY bot /app/bot
# Bytecode is compiled ahead of time: the container root is read-only, so .pyc files cannot
# be written there. unchecked-hash: do not compare against source mtimes, which COPY may change.
RUN python -m compileall -q -j 0 --invalidation-mode unchecked-hash /deps /app \
 && mkdir /data

# ---------- final image ----------
# distroless: no shell, package manager, pip or other tools; user nonroot (65532).
FROM gcr.io/distroless/python3-debian13:nonroot@sha256:64e54c4b1200da244d80181d98e86fc01d73c8101f107d5baf472152d8e119a2

ARG VERSION=dev
LABEL org.opencontainers.image.title="curse-bot" \
      org.opencontainers.image.description="New WoW addons from CurseForge posted to Telegram" \
      org.opencontainers.image.source="https://github.com/gera-corp-org/curse-bot" \
      org.opencontainers.image.version="${VERSION}"

# Code and dependencies are owned by root and not writable by the process.
COPY --from=deps --chown=0:0 --chmod=0755 /deps /opt/deps
COPY --from=deps --chown=0:0 --chmod=0755 /app /opt/app
# The only directory the process writes to: the SQLite database.
COPY --from=deps --chown=65532:65532 --chmod=0700 /data /data

# PYTHONSAFEPATH: the current directory is kept out of sys.path, so no module can be planted next to it.
ENV PYTHONPATH=/opt/app:/opt/deps \
    PYTHONSAFEPATH=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/bot.db

WORKDIR /opt/app
USER 65532:65532
VOLUME ["/data"]

# No shell wrapper: in the cluster vault-secrets-webhook wraps this command in vault-env.
ENTRYPOINT ["python3", "-m", "bot"]
