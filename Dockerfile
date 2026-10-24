# syntax=docker/dockerfile:1

# ---------- зависимости ----------
# Ставятся на платформе сборщика: все зависимости — чистый Python, поэтому один и тот же
# набор подходит и amd64, и arm64, а финальная стадия не выполняет RUN и собирается
# под arm64 без эмуляции QEMU.
FROM --platform=$BUILDPLATFORM python:3.12-slim AS deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
# requirements.txt — экспорт uv.lock (`uv export --no-dev --no-emit-project`), с хешами.
COPY requirements.txt .
RUN pip install --require-hashes --no-deps --only-binary=:all: --target /deps -r requirements.txt \
 && rm -rf /deps/bin \
 && mkdir /data

# ---------- финальный образ ----------
FROM python:3.12-slim

ARG VERSION=dev
LABEL org.opencontainers.image.title="curse-bot" \
      org.opencontainers.image.description="Новые аддоны WoW с CurseForge в Telegram" \
      org.opencontainers.image.source="https://github.com/gera-corp-org/curse-bot" \
      org.opencontainers.image.version="${VERSION}"

# Код и зависимости принадлежат root и недоступны процессу на запись.
COPY --from=deps --chown=0:0 /deps /opt/deps
COPY --chown=0:0 bot /opt/app/bot
# Единственный каталог, куда процесс пишет: база SQLite.
COPY --from=deps --chown=65532:65532 --chmod=0700 /data /data

ENV PYTHONPATH=/opt/app:/opt/deps \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/bot.db

WORKDIR /opt/app
USER 65532:65532
VOLUME ["/data"]

# Команда без shell-обёртки: vault-secrets-webhook в кластере оборачивает её в vault-env.
ENTRYPOINT ["python", "-m", "bot"]
