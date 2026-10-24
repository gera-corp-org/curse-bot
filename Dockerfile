# syntax=docker/dockerfile:1

# ---------- зависимости и байт-код ----------
# Стадия идёт на платформе сборщика: все зависимости — чистый Python, поэтому один и тот же
# набор подходит и amd64, и arm64, а финальная стадия не выполняет RUN и собирается
# под arm64 без эмуляции QEMU. Базовые образы закреплены по digest; обновляет их Dependabot.
FROM --platform=$BUILDPLATFORM python:3.13-slim-trixie@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962 AS deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
# requirements.txt — экспорт uv.lock (`uv export --no-dev --no-emit-project --no-header`), с хешами.
COPY requirements.txt .
RUN pip install --require-hashes --no-deps --only-binary=:all: --target /deps -r requirements.txt \
 && rm -rf /deps/bin
COPY bot /app/bot
# Байт-код компилируется заранее: корень в контейнере только для чтения, записать .pyc
# там нельзя. unchecked-hash — не сверять с mtime исходников, который COPY может поменять.
RUN python -m compileall -q -j 0 --invalidation-mode unchecked-hash /deps /app \
 && mkdir /data

# ---------- финальный образ ----------
# distroless: нет shell, пакетного менеджера, pip и прочих утилит; пользователь nonroot (65532).
FROM gcr.io/distroless/python3-debian13:nonroot@sha256:64e54c4b1200da244d80181d98e86fc01d73c8101f107d5baf472152d8e119a2

ARG VERSION=dev
LABEL org.opencontainers.image.title="curse-bot" \
      org.opencontainers.image.description="Новые аддоны WoW с CurseForge в Telegram" \
      org.opencontainers.image.source="https://github.com/gera-corp-org/curse-bot" \
      org.opencontainers.image.version="${VERSION}"

# Код и зависимости принадлежат root и недоступны процессу на запись.
COPY --from=deps --chown=0:0 --chmod=0755 /deps /opt/deps
COPY --from=deps --chown=0:0 --chmod=0755 /app /opt/app
# Единственный каталог, куда процесс пишет: база SQLite.
COPY --from=deps --chown=65532:65532 --chmod=0700 /data /data

# PYTHONSAFEPATH: текущий каталог не попадает в sys.path — подложить модуль рядом нельзя.
ENV PYTHONPATH=/opt/app:/opt/deps \
    PYTHONSAFEPATH=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/bot.db

WORKDIR /opt/app
USER 65532:65532
VOLUME ["/data"]

# Команда без shell-обёртки: vault-secrets-webhook в кластере оборачивает её в vault-env.
ENTRYPOINT ["python3", "-m", "bot"]
