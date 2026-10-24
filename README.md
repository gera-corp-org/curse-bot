# curse_bot

Telegram-бот, который следит за новыми аддонами World of Warcraft на CurseForge и публикует
каждый в канал: альбом (логотип + скриншоты), название, автор, категории, версии игры
(Retail / Classic / Forever), краткое описание и ссылка.

## Подготовка

1. Ключ CurseForge API — https://console.curseforge.com.
2. Бот — у @BotFather, получить токен.
3. Добавить бота администратором канала (право публиковать сообщения).
4. `cp .env.example .env` и заполнить. `TELEGRAM_CHAT_ID` — `@имя_канала` или числовой id `-100…`.
   Ключ CurseForge содержит `$` — возьмите его в **одинарные** кавычки
   (`CURSEFORGE_API_KEY='$2a$10$…'`), иначе `uv` и `docker compose` испортят значение
   подстановкой переменных и CurseForge ответит 403.

`FLAVORS` — о каких версиях сообщать (`retail`, `classic`, `forever` через запятую; пусто — обо всех).
Аддон проходит фильтр, если у него есть файлы хотя бы под одну из этих версий на момент одобрения.

Как бот находит новые аддоны: поиск CurseForge для обычных ключей закрыт, поэтому бот
просматривает новые ID проектов (они растут по порядку), берёт проекты WoW и объявляет
каждый, когда модераторы CurseForge его одобрят. Сейчас это ~200 аддонов в сутки —
сузить поток можно через `FLAVORS`.

## Запуск в Docker

```bash
docker compose up -d --build
docker compose logs -f
```

Состояние (курсор и список ожидающих модерации) лежит в томе `botdata` (`/data/bot.db`
в контейнере). При самом первом
запуске бот только находит текущий последний ID проекта на CurseForge (`baseline` в логе)
и ничего не отправляет — уведомления пойдут о проектах, созданных после этого.

Проверка отправки (разово шлёт 2 последних аддона, базу не трогает):

```bash
docker compose run --rm bot --send-latest 2
```

## Kubernetes (Helm)

Образ `ghcr.io/gera-corp-org/curse-bot` и чарт `oci://ghcr.io/gera-corp-org/charts/curse-bot`
публикуются из CI. Секреты по умолчанию берутся из Vault через bank-vaults
vault-secrets-webhook (в Kubernetes Secret они не попадают):

```bash
vault kv put secret/curse-bot \
  CURSEFORGE_API_KEY='$2a$10$…' TELEGRAM_BOT_TOKEN='…' TELEGRAM_CHAT_ID='…'
helm install curse-bot oci://ghcr.io/gera-corp-org/charts/curse-bot -n curse-bot --create-namespace
```

Без Vault — готовый Secret с теми же тремя ключами:
`--set vault.enabled=false --set existingSecret=<имя>`. Остальные настройки — в
[`charts/curse-bot/values.yaml`](charts/curse-bot/values.yaml) (`config.flavors`,
`config.pollInterval`, `persistence.*`).

Бот должен работать в одном экземпляре: два экземпляра (например, в кластере и в
`docker compose`) отправят каждый аддон дважды.

## Релизы

```bash
git tag v0.2.0 && git push origin v0.2.0
```

Тег запускает CI: тесты → образ `0.2.0` (amd64 + arm64) → чарт `0.2.0` в GHCR →
GitHub Release с автоматическими заметками. Чарт публикуется только после образа,
поэтому ArgoCD с `targetRevision: 0.*` не увидит версию без образа. Каждый пуш в
`master` собирает образ `latest` и `sha-<коммит>`.

## Запуск без Docker

```bash
uv sync
uv run --env-file .env python -m bot
```

Пример юнита systemd (`/etc/systemd/system/curse-bot.service`), путь и пользователя подставить свои:

```ini
[Unit]
Description=CurseForge WoW addons -> Telegram
After=network-online.target
Wants=network-online.target

[Service]
User=gera
WorkingDirectory=/home/gera/curse_bot
ExecStart=/home/gera/.local/bin/uv run --env-file .env python -m bot
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

## Разработка

```bash
uv run pytest
uv run --env-file .env python -m scripts.probe   # живая проверка CurseForge API
# после изменения зависимостей — обновить requirements.txt для образа (CI это проверяет):
uv export --no-dev --no-emit-project --no-header --format requirements-txt -o requirements.txt
```
