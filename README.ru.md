# curse_bot

[English](README.md) | **Русский**

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

## Команды в Telegram

Бот отвечает в личных сообщениях только пользователям из `TELEGRAM_ADMIN_IDS`
(в чарте — `config.adminIds`). Остальным он не отвечает, а в лог пишет их id:
`message from a user who is not allowed, id=…`. Так можно узнать свой id. Ещё его
показывает `/help`, когда доступ уже есть.

| Команда | Что делает |
|---|---|
| `/status` | последний опрос, курсор id, сколько ждёт модерации, сколько отправлено в канал за 24 ч, фильтр версий |
| `/latest [N]` | N последних одобренных аддонов (по умолчанию 3, максимум 10) — в личку, не в канал |
| `/pending` | очередь модерации: до 20 аддонов, у каждого статус и сколько ждёт |
| `/flavors` | показать фильтр версий; `/flavors forever,retail` — задать, `all` — без фильтра, `reset` — как в настройках |
| `/lang` | язык ответов: `/lang en`, `/lang ru` или кнопки под `/lang` |
| `/help` | список команд и ваш id |

Бот отвечает на языке, выбранном через `/lang` (запоминается для каждого пользователя), а если
язык не выбран — на языке вашего клиента Telegram: русский для `ru`, иначе английский. Меню
команд зарегистрировано на обоих языках. Посты в канал и логи не переводятся.

Фильтр, заданный командой `/flavors`, хранится в базе и перекрывает `FLAVORS` из настроек.
Входящие сообщения бот забирает long polling'ом (`getUpdates`) между опросами
CurseForge. Поэтому с одним токеном бота может работать только один экземпляр.

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
`config.pollInterval`, `config.adminIds`, `persistence.*`).

Бот должен работать в одном экземпляре: два экземпляра (например, в кластере и в
`docker compose`) отправят каждый аддон дважды.

## Релизы

```bash
git tag v0.4.0 && git push origin v0.4.0
```

Тег запускает CI: тесты → образ `0.4.0` (amd64 + arm64) → чарт `0.4.0` в GHCR →
GitHub Release с автоматическими заметками. Чарт публикуется только после образа,
поэтому ArgoCD с `targetRevision: 0.*` не увидит версию без образа. Каждый пуш в
`master` собирает образ `latest` и `sha-<коммит>`.

## Безопасность

**Образ**:
- `gcr.io/distroless/python3-debian13:nonroot`: нет shell, пакетного менеджера и `pip`;
- процесс работает от uid 65532;
- код и зависимости принадлежат root и доступны только на чтение, байт-код скомпилирован заранее;
- писать можно только в `/data`;
- базовые образы закреплены по digest, GitHub Actions — по SHA; обновляет их Dependabot.

**CI**:
- hadolint проверяет Dockerfile;
- к образу прикладываются SBOM и provenance;
- аттестация Sigstore;
- Trivy отправляет отчёт в GitHub Security, а `CRITICAL` останавливает выпуск: без образа не выйдет и чарт.

Проверить происхождение образа:

```bash
gh attestation verify oci://ghcr.io/gera-corp-org/curse-bot:0.4.0 -o gera-corp-org
```

**Под** (чарт):
- проходит Pod Security `restricted`: `runAsNonRoot`, read-only корень, `drop: ALL`,
  `seccomp: RuntimeDefault`, без повышения привилегий;
- `/tmp` в памяти, лимиты памяти и `ephemeral-storage`;
- токен ServiceAccount монтируется только для vault-env;
- NetworkPolicy закрывает весь входящий трафик, исходящий разрешён только на DNS и TCP 443;
- liveness-проба перезапускает контейнер, если цикл опроса завис: смотрит на возраст `/tmp/heartbeat`;
- чарт отказывается рендериться с uid 0, без `runAsNonRoot` или без read-only корня.

В `docker compose` те же ограничения: `read_only`, `cap_drop: ALL`, `no-new-privileges`,
лимиты памяти и процессов, healthcheck по heartbeat.

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
