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

Состояние (курсор и список ожидающих модерации) лежит в `./data/bot.db`. При самом первом
запуске бот только находит текущий последний ID проекта на CurseForge (`baseline` в логе)
и ничего не отправляет — уведомления пойдут о проектах, созданных после этого.

Проверка отправки (разово шлёт 2 последних аддона, базу не трогает):

```bash
docker compose run --rm bot python -m bot --send-latest 2
```

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
```
