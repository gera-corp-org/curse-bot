# CurseForge → Telegram: бот новых аддонов WoW — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Python-бот, который раз в N минут берёт с CurseForge свежевышедшие аддоны WoW и публикует каждый новый в Telegram-канал альбомом картинок с подписью (название, автор, категории, версии Retail/Classic/Forever, описание, ссылка).

**Architecture:** Один синхронный процесс с циклом опроса. Чистые модули (`flavors`, `formatter`) без сети; сеть только в `curseforge` и `telegram` (оба принимают внедряемый `httpx.Client` для тестов через `httpx.MockTransport`); состояние — SQLite с id виденных аддонов; `main.Bot` склеивает всё и получает зависимости через конструктор.

**Tech Stack:** Python 3.12, `httpx`, `sqlite3` (stdlib), `pytest`, `uv` для окружения, Docker / docker compose для запуска.

**Spec:** `docs/superpowers/specs/2026-10-24-curseforge-telegram-bot-design.md`

## Global Constraints

- Python `>=3.12`; runtime-зависимость только `httpx>=0.27,<1`; dev — `pytest>=8`. Никаких Telegram-фреймворков.
- Запуск: `python -m bot`; тесты: `uv run pytest` из корня `/home/gera/curse_bot`.
- Идентификаторы и имена — на английском; докстринги, комментарии, тексты ошибок и логов — на русском (кроме строки `baseline: N addons` — дословно из спеки).
- Токен бота никогда не попадает в логи: логгер `httpx` поднят до `WARNING` (на `INFO` он пишет URL, а в URL Telegram — токен).
- Подпись Telegram: `parse_mode=HTML`, не длиннее `1024` (в UTF-16 code units), все поля из API экранируются `html.escape`; при переполнении обрезается только `summary`.
- Аддон помечается виденным только после успешной отправки (или если он отфильтрован `FLAVORS`).
- `FLAVORS` допускает только `retail`, `classic`, `forever`; пусто = все.
- Каждый коммит заканчивается строкой `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Известные значения API (не выдумывать другие)

- База `https://api.curseforge.com`, заголовок `x-api-key`. WoW `gameId=1`.
- Поиск: `GET /v1/mods/search?gameId=1&sortField=11&sortOrder=desc&pageSize=50` (`11` = ReleasedDate, `50` — максимум API). `classId` не передаётся.
- Типы версий: `GET /v1/games/1/version-types` → `data: [{id, gameId, name, slug, ...}]`.
- ID типов: Retail 517; Classic: Era 67408, TBC 73246, Wrath 73713, Titan 81212, Cata 77522, MoP 79434; Forever 88568.
- Ответы CurseForge: `{"data": ...}`. Поля мода: `id`, `name`, `summary`, `links.websiteUrl`, `authors[].name`, `categories[].name`, `logo.url`, `screenshots[].url`, `dateReleased`, `classId`, `latestFilesIndexes[].gameVersionTypeId`.
- Telegram: `POST https://api.telegram.org/bot<TOKEN>/<method>`, ответ `{"ok": true, "result": ...}` или `{"ok": false, "error_code", "description", "parameters": {"retry_after"}}`.

## Файлы

```
pyproject.toml, uv.lock          — проект и зависимости (Task 1)
bot/__init__.py                  — пустой (Task 1)
bot/flavors.py                   — типы версий → группы/метки, фильтр (Task 1)
bot/config.py                    — Config из окружения (Task 2)
bot/formatter.py                 — подпись и картинки (Task 3)
bot/storage.py                   — SQLite виденных id (Task 4)
bot/curseforge.py                — клиент CurseForge (Task 5)
scripts/probe.py                 — живая проверка API (Task 6)
bot/telegram.py                  — клиент Telegram (Task 7)
bot/main.py, bot/__main__.py     — Bot, цикл, CLI (Task 8)
Dockerfile, docker-compose.yml, .env.example, README.md — запуск (Task 9)
tests/test_<module>.py           — тесты каждого модуля
```

---

### Task 1: Каркас проекта и `flavors`

**Files:**
- Create: `pyproject.toml`, `bot/__init__.py`, `bot/flavors.py`
- Test: `tests/test_flavors.py`

**Interfaces:**
- Consumes: —
- Produces:
  - константы `RETAIL = "retail"`, `CLASSIC = "classic"`, `FOREVER = "forever"`, `GROUPS: frozenset[str]`
  - `@dataclass(frozen=True) class Flavor: group: str | None; label: str`
  - `KNOWN_TYPES: dict[int, Flavor]`
  - `build_flavor_map(version_types: list[dict]) -> dict[int, Flavor]`
  - `mod_flavors(mod: dict, flavor_map: dict[int, Flavor]) -> list[Flavor]`
  - `passes_filter(flavors: list[Flavor], wanted: frozenset[str]) -> bool`
  - `format_flavors(flavors: list[Flavor]) -> str`

- [ ] **Step 1: Создать `pyproject.toml` и пакет**

`pyproject.toml`:

```toml
[project]
name = "curse-bot"
version = "0.1.0"
description = "Уведомления о новых аддонах WoW с CurseForge в Telegram"
requires-python = ">=3.12"
dependencies = ["httpx>=0.27,<1"]

[dependency-groups]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

`bot/__init__.py` — пустой файл.

Run: `cd /home/gera/curse_bot && uv sync`
Expected: создан `.venv/` и `uv.lock`, установлены httpx и pytest.

- [ ] **Step 2: Написать падающие тесты**

`tests/test_flavors.py`:

```python
from bot.flavors import (
    CLASSIC,
    FOREVER,
    RETAIL,
    Flavor,
    build_flavor_map,
    format_flavors,
    mod_flavors,
    passes_filter,
)


def mod_with_types(*type_ids):
    return {"id": 1, "latestFilesIndexes": [{"gameVersionTypeId": t} for t in type_ids]}


def test_known_types_map_to_groups():
    fmap = build_flavor_map([])
    assert fmap[517] == Flavor(RETAIL, "Retail")
    assert fmap[67408] == Flavor(CLASSIC, "Era")
    assert fmap[79434] == Flavor(CLASSIC, "MoP")
    assert fmap[88568] == Flavor(FOREVER, "Forever")


def test_unknown_types_from_api_are_guessed_by_name():
    fmap = build_flavor_map([
        {"id": 517, "name": "WoW Retail", "slug": "wow_retail"},
        {"id": 90001, "name": "WoW Forever Hardcore", "slug": "wow-forever-hc"},
        {"id": 90002, "name": "Legion Classic", "slug": "wow-legion-classic"},
        {"id": 90003, "name": "Plunderstorm", "slug": "wow-plunderstorm"},
    ])
    assert fmap[517] == Flavor(RETAIL, "Retail")  # известные не переопределяются
    assert fmap[90001] == Flavor(FOREVER, "Forever")
    assert fmap[90002] == Flavor(CLASSIC, "Legion Classic")
    assert fmap[90003] == Flavor(None, "Plunderstorm")


def test_mod_flavors_dedupes_and_orders():
    flavors = mod_flavors(mod_with_types(88568, 79434, 517, 67408, 517), build_flavor_map([]))
    assert flavors == [
        Flavor(RETAIL, "Retail"),
        Flavor(CLASSIC, "Era"),
        Flavor(CLASSIC, "MoP"),
        Flavor(FOREVER, "Forever"),
    ]


def test_mod_flavors_id_missing_from_map():
    assert mod_flavors(mod_with_types(12345), build_flavor_map([])) == [Flavor(None, "type 12345")]


def test_mod_flavors_without_files():
    assert mod_flavors({"id": 1}, build_flavor_map([])) == []


def test_format_flavors():
    flavors = mod_flavors(mod_with_types(517, 67408, 79434, 88568, 12345), build_flavor_map([]))
    assert format_flavors(flavors) == "Retail · Classic (Era, MoP) · Forever · type 12345"


def test_format_flavors_single_and_empty():
    assert format_flavors(mod_flavors(mod_with_types(88568), build_flavor_map([]))) == "Forever"
    assert format_flavors([]) == ""


def test_passes_filter():
    fmap = build_flavor_map([])
    retail_only = mod_flavors(mod_with_types(517), fmap)
    unknown_only = mod_flavors(mod_with_types(12345), fmap)
    assert passes_filter(retail_only, frozenset())
    assert passes_filter(retail_only, frozenset({RETAIL, FOREVER}))
    assert not passes_filter(retail_only, frozenset({CLASSIC}))
    assert passes_filter(unknown_only, frozenset())
    assert not passes_filter(unknown_only, frozenset({RETAIL}))
    assert not passes_filter([], frozenset({RETAIL}))
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `uv run pytest tests/test_flavors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.flavors'`.

- [ ] **Step 4: Реализовать `bot/flavors.py`**

```python
"""Версии WoW: gameVersionTypeId из CurseForge → группа (Retail/Classic/Forever) и метка."""
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

RETAIL = "retail"
CLASSIC = "classic"
FOREVER = "forever"
GROUPS = frozenset({RETAIL, CLASSIC, FOREVER})

_GROUP_ORDER = (RETAIL, CLASSIC, FOREVER)
_GROUP_TITLES = {RETAIL: "Retail", CLASSIC: "Classic", FOREVER: "Forever"}


@dataclass(frozen=True)
class Flavor:
    group: str | None  # None — тип не отнесён ни к одной группе
    label: str  # для Classic — короткое имя версии ("Era", "MoP")


# ID из https://api.curseforge.com/v1/games/1/version-types (сверено с instawow).
KNOWN_TYPES: dict[int, Flavor] = {
    517: Flavor(RETAIL, "Retail"),
    67408: Flavor(CLASSIC, "Era"),
    73246: Flavor(CLASSIC, "TBC"),
    73713: Flavor(CLASSIC, "Wrath"),
    81212: Flavor(CLASSIC, "Titan"),
    77522: Flavor(CLASSIC, "Cata"),
    79434: Flavor(CLASSIC, "MoP"),
    88568: Flavor(FOREVER, "Forever"),
}

_CLASSIC_ORDER = [f.label for f in KNOWN_TYPES.values() if f.group == CLASSIC]


def build_flavor_map(version_types: list[dict]) -> dict[int, Flavor]:
    """Встроенная таблица + типы из ответа API, которых в ней нет (распознаются по имени)."""
    result = dict(KNOWN_TYPES)
    for vt in version_types:
        type_id = vt["id"]
        if type_id in result:
            continue
        name = vt.get("name") or vt.get("slug") or f"type {type_id}"
        text = f"{name} {vt.get('slug', '')}".lower()
        if "forever" in text:
            flavor = Flavor(FOREVER, "Forever")
        elif "classic" in text:
            flavor = Flavor(CLASSIC, name)
        else:
            flavor = Flavor(None, name)
        log.warning("unknown version type %s (%s) → %s", type_id, name, flavor.group or "без группы")
        result[type_id] = flavor
    return result


def mod_flavors(mod: dict, flavor_map: dict[int, Flavor]) -> list[Flavor]:
    """Уникальные версии игры, под которые у аддона есть файлы, в порядке показа."""
    found: dict[Flavor, None] = {}
    for index in mod.get("latestFilesIndexes") or []:
        type_id = index.get("gameVersionTypeId")
        if type_id is None:
            continue
        found.setdefault(flavor_map.get(type_id, Flavor(None, f"type {type_id}")), None)
    return sorted(found, key=_sort_key)


def passes_filter(flavors: list[Flavor], wanted: frozenset[str]) -> bool:
    """Пустой фильтр пропускает всё; иначе нужна хотя бы одна группа из wanted."""
    return not wanted or any(f.group in wanted for f in flavors)


def format_flavors(flavors: list[Flavor]) -> str:
    """'Retail · Classic (Era, MoP) · Forever'; пустая строка, если версий нет."""
    parts = []
    for group in _GROUP_ORDER:
        labels = [f.label for f in flavors if f.group == group]
        if not labels:
            continue
        parts.append(f"Classic ({', '.join(labels)})" if group == CLASSIC else _GROUP_TITLES[group])
    parts += [f.label for f in flavors if f.group is None]
    return " · ".join(parts)


def _sort_key(flavor: Flavor) -> tuple[int, int, str]:
    group_rank = _GROUP_ORDER.index(flavor.group) if flavor.group in _GROUP_ORDER else len(_GROUP_ORDER)
    label_rank = _CLASSIC_ORDER.index(flavor.label) if flavor.label in _CLASSIC_ORDER else len(_CLASSIC_ORDER)
    return group_rank, label_rank, flavor.label
```

- [ ] **Step 5: Тесты проходят**

Run: `uv run pytest tests/test_flavors.py -v`
Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock bot/__init__.py bot/flavors.py tests/test_flavors.py
git commit -m "feat: project skeleton and WoW flavor mapping

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `config`

**Files:**
- Create: `bot/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `bot.flavors.GROUPS`
- Produces:
  - `class ConfigError(Exception)`
  - `@dataclass(frozen=True) class Config: curseforge_api_key: str; telegram_bot_token: str; telegram_chat_id: str; flavors: frozenset[str]; poll_interval: int; db_path: Path`
  - `load_config(env: Mapping[str, str] | None = None) -> Config` (по умолчанию `os.environ`)

- [ ] **Step 1: Написать падающие тесты**

`tests/test_config.py`:

```python
from pathlib import Path

import pytest

from bot.config import ConfigError, load_config

BASE = {"CURSEFORGE_API_KEY": "cf", "TELEGRAM_BOT_TOKEN": "tg", "TELEGRAM_CHAT_ID": "-100"}


def test_defaults():
    config = load_config(BASE)
    assert config.curseforge_api_key == "cf"
    assert config.telegram_bot_token == "tg"
    assert config.telegram_chat_id == "-100"
    assert config.flavors == frozenset()
    assert config.poll_interval == 600
    assert config.db_path == Path("data/bot.db")


def test_custom_values():
    config = load_config({**BASE, "FLAVORS": " Retail, forever ,", "POLL_INTERVAL": "120", "DB_PATH": "/srv/bot.db"})
    assert config.flavors == frozenset({"retail", "forever"})
    assert config.poll_interval == 120
    assert config.db_path == Path("/srv/bot.db")


@pytest.mark.parametrize("name", ["CURSEFORGE_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
def test_missing_required(name):
    env = {k: v for k, v in BASE.items() if k != name}
    with pytest.raises(ConfigError, match=name):
        load_config(env)


def test_blank_required_counts_as_missing():
    with pytest.raises(ConfigError, match="TELEGRAM_CHAT_ID"):
        load_config({**BASE, "TELEGRAM_CHAT_ID": "  "})


def test_unknown_flavor():
    with pytest.raises(ConfigError, match="wotlk"):
        load_config({**BASE, "FLAVORS": "retail,wotlk"})


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_bad_poll_interval(value):
    with pytest.raises(ConfigError, match="POLL_INTERVAL"):
        load_config({**BASE, "POLL_INTERVAL": value})
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.config'`.

- [ ] **Step 3: Реализовать `bot/config.py`**

```python
"""Настройки бота из переменных окружения."""
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from bot.flavors import GROUPS

REQUIRED = ("CURSEFORGE_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    curseforge_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    flavors: frozenset[str]  # пусто — сообщать обо всех версиях
    poll_interval: int
    db_path: Path


def load_config(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env

    missing = [name for name in REQUIRED if not env.get(name, "").strip()]
    if missing:
        raise ConfigError(f"Не заданы обязательные переменные: {', '.join(missing)}")

    flavors = frozenset(f.strip().lower() for f in env.get("FLAVORS", "").split(",") if f.strip())
    unknown = flavors - GROUPS
    if unknown:
        raise ConfigError(
            f"Неизвестные значения FLAVORS: {', '.join(sorted(unknown))}; допустимо: retail, classic, forever"
        )

    try:
        poll_interval = int(env.get("POLL_INTERVAL", "600"))
    except ValueError:
        poll_interval = 0
    if poll_interval <= 0:
        raise ConfigError("POLL_INTERVAL должен быть положительным целым числом секунд")

    return Config(
        curseforge_api_key=env["CURSEFORGE_API_KEY"].strip(),
        telegram_bot_token=env["TELEGRAM_BOT_TOKEN"].strip(),
        telegram_chat_id=env["TELEGRAM_CHAT_ID"].strip(),
        flavors=flavors,
        poll_interval=poll_interval,
        db_path=Path(env.get("DB_PATH", "data/bot.db")),
    )
```

- [ ] **Step 4: Тесты проходят**

Run: `uv run pytest tests/test_config.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add bot/config.py tests/test_config.py
git commit -m "feat: load bot settings from environment

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `formatter`

**Files:**
- Create: `bot/formatter.py`
- Test: `tests/test_formatter.py`

**Interfaces:**
- Consumes: `bot.flavors.Flavor`, `bot.flavors.format_flavors`
- Produces:
  - `CAPTION_LIMIT = 1024`, `MAX_IMAGES = 4`
  - `tg_len(text: str) -> int` — длина в UTF-16 code units
  - `pick_images(mod: dict) -> list[str]`
  - `build_caption(mod: dict, flavors: list[Flavor]) -> str`

- [ ] **Step 1: Написать падающие тесты**

`tests/test_formatter.py`:

```python
from bot.flavors import build_flavor_map, mod_flavors
from bot.formatter import CAPTION_LIMIT, build_caption, pick_images, tg_len

LOGO = "https://media.forgecdn.net/logo.png"
SHOTS = [f"https://media.forgecdn.net/s{i}.png" for i in range(1, 6)]
URL = "https://www.curseforge.com/wow/addons/mistweaver-teachings-bar"


def make_mod(**overrides):
    mod = {
        "id": 42,
        "name": "Mistweaver Teachings Bar",
        "summary": "Tracks Teachings of the Monastery.",
        "links": {"websiteUrl": URL},
        "authors": [{"name": "Alice"}, {"name": "Bob"}],
        "categories": [{"name": "Monk"}, {"name": "Combat"}],
        "logo": {"url": LOGO},
        "screenshots": [{"url": u} for u in SHOTS],
        "latestFilesIndexes": [
            {"gameVersionTypeId": 517},
            {"gameVersionTypeId": 67408},
            {"gameVersionTypeId": 88568},
        ],
    }
    mod.update(overrides)
    return mod


def caption_of(mod):
    return build_caption(mod, mod_flavors(mod, build_flavor_map([])))


def test_caption_layout():
    assert caption_of(make_mod()) == (
        "🆕 <b>Mistweaver Teachings Bar</b>\n"
        "👤 Alice, Bob · 📂 Monk, Combat\n"
        "🎮 Retail · Classic (Era) · Forever\n"
        "\n"
        "Tracks Teachings of the Monastery.\n"
        "\n"
        f"🔗 {URL}"
    )


def test_caption_escapes_html():
    caption = caption_of(make_mod(name="<Cool> & Co", summary="a < b", authors=[{"name": "R&D"}]))
    assert "<b>&lt;Cool&gt; &amp; Co</b>" in caption
    assert "a &lt; b" in caption
    assert "R&amp;D" in caption


def test_caption_skips_empty_parts():
    mod = make_mod(authors=[], categories=[], summary="  ", latestFilesIndexes=[], links={})
    assert caption_of(mod) == "🆕 <b>Mistweaver Teachings Bar</b>"


def test_long_summary_truncated_to_limit():
    caption = caption_of(make_mod(summary="&" * 3000))
    assert tg_len(caption) <= CAPTION_LIMIT
    assert "&amp;…" in caption  # обрезано по исходному тексту, сущность целая
    assert caption.startswith("🆕 <b>Mistweaver Teachings Bar</b>\n")
    assert caption.endswith(f"🔗 {URL}")


def test_tg_len_counts_utf16():
    assert tg_len("abc") == 3
    assert tg_len("🆕") == 2


def test_pick_images_logo_plus_three_screenshots():
    assert pick_images(make_mod()) == [LOGO, *SHOTS[:3]]


def test_pick_images_without_screenshots():
    assert pick_images(make_mod(screenshots=[])) == [LOGO]


def test_pick_images_without_logo():
    assert pick_images(make_mod(logo=None)) == SHOTS[:4]


def test_pick_images_dedupes_logo():
    assert pick_images(make_mod(screenshots=[{"url": LOGO}, {"url": SHOTS[0]}])) == [LOGO, SHOTS[0]]


def test_pick_images_nothing():
    assert pick_images(make_mod(logo=None, screenshots=None)) == []
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `uv run pytest tests/test_formatter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.formatter'`.

- [ ] **Step 3: Реализовать `bot/formatter.py`**

```python
"""Подпись к уведомлению о новом аддоне и выбор картинок."""
from html import escape

from bot.flavors import Flavor, format_flavors

CAPTION_LIMIT = 1024  # лимит подписи к фото в Telegram
MAX_IMAGES = 4  # логотип + до 3 скриншотов


def tg_len(text: str) -> int:
    """Длина так, как её считает Telegram: в UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def pick_images(mod: dict) -> list[str]:
    """Логотип и первые скриншоты, без повторов, не больше MAX_IMAGES."""
    urls: list[str] = []
    logo = (mod.get("logo") or {}).get("url")
    if logo:
        urls.append(logo)
    for shot in mod.get("screenshots") or []:
        if len(urls) == MAX_IMAGES:
            break
        url = shot.get("url")
        if url and url not in urls:
            urls.append(url)
    return urls


def build_caption(mod: dict, flavors: list[Flavor]) -> str:
    head = [f"🆕 <b>{escape(mod.get('name', ''))}</b>"]
    meta = []
    authors = ", ".join(a["name"] for a in mod.get("authors") or [])
    if authors:
        meta.append(f"👤 {escape(authors)}")
    categories = ", ".join(c["name"] for c in mod.get("categories") or [])
    if categories:
        meta.append(f"📂 {escape(categories)}")
    if meta:
        head.append(" · ".join(meta))
    versions = format_flavors(flavors)
    if versions:
        head.append(f"🎮 {escape(versions)}")

    url = (mod.get("links") or {}).get("websiteUrl")
    tail = f"🔗 {escape(url)}" if url else ""
    return _fit("\n".join(head), (mod.get("summary") or "").strip(), tail)


def _render(head: str, summary: str, tail: str) -> str:
    return "\n\n".join(part for part in (head, escape(summary), tail) if part)


def _cut(summary: str, keep: int) -> str:
    return summary[:keep].rstrip() + "…" if keep else ""


def _fit(head: str, summary: str, tail: str) -> str:
    """Собрать подпись; если не влезает в лимит — обрезать только summary."""
    text = _render(head, summary, tail)
    if tg_len(text) <= CAPTION_LIMIT:
        return text
    # двоичный поиск самого длинного начала summary, которое ещё влезает
    lo, hi = 0, len(summary)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if tg_len(_render(head, _cut(summary, mid), tail)) <= CAPTION_LIMIT:
            lo = mid
        else:
            hi = mid - 1
    return _render(head, _cut(summary, lo), tail)
```

- [ ] **Step 4: Тесты проходят**

Run: `uv run pytest tests/test_formatter.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add bot/formatter.py tests/test_formatter.py
git commit -m "feat: build Telegram caption and pick addon images

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `storage`

**Files:**
- Create: `bot/storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes: —
- Produces: `class Storage(path: str | Path)` с методами `is_empty() -> bool`, `filter_unseen(mod_ids: list[int]) -> list[int]` (порядок сохраняется), `mark_seen(mod_ids: Iterable[int]) -> None`, `close() -> None`. `":memory:"` — БД в памяти для тестов.

- [ ] **Step 1: Написать падающие тесты**

`tests/test_storage.py`:

```python
from bot.storage import Storage


def test_new_storage_is_empty():
    assert Storage(":memory:").is_empty()


def test_mark_and_filter():
    storage = Storage(":memory:")
    storage.mark_seen([1, 2])
    assert not storage.is_empty()
    assert storage.filter_unseen([3, 1, 4, 2]) == [3, 4]


def test_filter_empty_list():
    assert Storage(":memory:").filter_unseen([]) == []


def test_mark_seen_twice_is_ok():
    storage = Storage(":memory:")
    storage.mark_seen([1])
    storage.mark_seen([1])
    assert storage.filter_unseen([1]) == []


def test_persists_between_instances(tmp_path):
    path = tmp_path / "sub" / "bot.db"
    storage = Storage(path)
    storage.mark_seen([7])
    storage.close()
    assert Storage(path).filter_unseen([7, 8]) == [8]
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `uv run pytest tests/test_storage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.storage'`.

- [ ] **Step 3: Реализовать `bot/storage.py`**

```python
"""SQLite-хранилище id аддонов, которые бот уже видел."""
import sqlite3
from collections.abc import Iterable
from pathlib import Path


class Storage:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS seen ("
            " mod_id INTEGER PRIMARY KEY,"
            " seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        self._db.commit()

    def is_empty(self) -> bool:
        return self._db.execute("SELECT 1 FROM seen LIMIT 1").fetchone() is None

    def filter_unseen(self, mod_ids: list[int]) -> list[int]:
        """Те из mod_ids, которых ещё нет в базе, в исходном порядке."""
        if not mod_ids:
            return []
        placeholders = ",".join("?" * len(mod_ids))
        rows = self._db.execute(f"SELECT mod_id FROM seen WHERE mod_id IN ({placeholders})", mod_ids)
        seen = {row[0] for row in rows}
        return [mod_id for mod_id in mod_ids if mod_id not in seen]

    def mark_seen(self, mod_ids: Iterable[int]) -> None:
        self._db.executemany("INSERT OR IGNORE INTO seen (mod_id) VALUES (?)", ((i,) for i in mod_ids))
        self._db.commit()

    def close(self) -> None:
        self._db.close()
```

- [ ] **Step 4: Тесты проходят**

Run: `uv run pytest tests/test_storage.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add bot/storage.py tests/test_storage.py
git commit -m "feat: SQLite storage of seen addon ids

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Клиент CurseForge

**Files:**
- Create: `bot/curseforge.py`
- Test: `tests/test_curseforge.py`

**Interfaces:**
- Consumes: —
- Produces:
  - `API_URL = "https://api.curseforge.com"`, `WOW_GAME_ID = 1`, `SORT_RELEASED_DATE = 11`, `PAGE_SIZE = 50`
  - `class CurseForgeError(Exception)`
  - `class CurseForgeClient(api_key: str, http: httpx.Client | None = None)` с методами `latest_released() -> list[dict]` (от новых к старым) и `version_types() -> list[dict]`. Любая сетевая ошибка и любой не-200 ответ → `CurseForgeError`.

- [ ] **Step 1: Написать падающие тесты**

`tests/test_curseforge.py`:

```python
import httpx
import pytest

from bot.curseforge import API_URL, CurseForgeClient, CurseForgeError


def client_with(handler):
    http = httpx.Client(base_url=API_URL, transport=httpx.MockTransport(handler))
    return CurseForgeClient("secret", http=http)


def test_latest_released_request():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": 1}], "pagination": {}})

    assert client_with(handler).latest_released() == [{"id": 1}]
    request = requests[0]
    assert request.url.path == "/v1/mods/search"
    assert dict(request.url.params) == {"gameId": "1", "sortField": "11", "sortOrder": "desc", "pageSize": "50"}
    assert request.headers["x-api-key"] == "secret"


def test_version_types_request():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": 517, "name": "WoW Retail"}]})

    assert client_with(handler).version_types() == [{"id": 517, "name": "WoW Retail"}]
    assert requests[0].url.path == "/v1/games/1/version-types"


def test_403_explains_key():
    client = client_with(lambda request: httpx.Response(403))
    with pytest.raises(CurseForgeError, match="API-ключ"):
        client.latest_released()


def test_server_error():
    client = client_with(lambda request: httpx.Response(503, text="Service Unavailable"))
    with pytest.raises(CurseForgeError, match="503"):
        client.latest_released()


def test_network_error():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(CurseForgeError, match="недоступен"):
        client_with(handler).latest_released()
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `uv run pytest tests/test_curseforge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.curseforge'`.

- [ ] **Step 3: Реализовать `bot/curseforge.py`**

```python
"""Клиент CurseForge API — только запросы, нужные боту."""
import httpx

API_URL = "https://api.curseforge.com"
WOW_GAME_ID = 1
SORT_RELEASED_DATE = 11  # ModsSearchSortField.ReleasedDate
PAGE_SIZE = 50  # максимум, который отдаёт API


class CurseForgeError(Exception):
    pass


class CurseForgeClient:
    def __init__(self, api_key: str, http: httpx.Client | None = None):
        self._headers = {"x-api-key": api_key, "Accept": "application/json"}
        self._http = http or httpx.Client(base_url=API_URL, timeout=30)

    def latest_released(self) -> list[dict]:
        """Последние вышедшие аддоны WoW, от новых к старым."""
        return self._get(
            "/v1/mods/search",
            {"gameId": WOW_GAME_ID, "sortField": SORT_RELEASED_DATE, "sortOrder": "desc", "pageSize": PAGE_SIZE},
        )

    def version_types(self) -> list[dict]:
        return self._get(f"/v1/games/{WOW_GAME_ID}/version-types")

    def _get(self, path: str, params: dict | None = None):
        try:
            response = self._http.get(path, params=params, headers=self._headers)
        except httpx.HTTPError as e:
            raise CurseForgeError(f"CurseForge недоступен: {e}") from e
        if response.status_code == 403:
            raise CurseForgeError("CurseForge ответил 403: неверный или отозванный API-ключ")
        if response.status_code != 200:
            raise CurseForgeError(f"CurseForge ответил {response.status_code}: {response.text[:200]}")
        return response.json()["data"]
```

- [ ] **Step 4: Тесты проходят**

Run: `uv run pytest tests/test_curseforge.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add bot/curseforge.py tests/test_curseforge.py
git commit -m "feat: CurseForge API client

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Живая проверка CurseForge API (checkpoint, нужен ключ)

Проверяет три предположения из спеки на реальном API. Без ключа задача не выполняется: **остановиться и попросить пользователя положить `CURSEFORGE_API_KEY` в `/home/gera/curse_bot/.env`** (файл в `.gitignore`). Ключ не печатать и не коммитить.

**Files:**
- Create: `scripts/probe.py`

**Interfaces:**
- Consumes: `CurseForgeClient`, `KNOWN_TYPES`, `build_flavor_map`, `mod_flavors`, `format_flavors`
- Produces: отчёт в stdout; код не используется другими задачами.

- [ ] **Step 1: Написать `scripts/probe.py`**

```python
"""Живая проверка CurseForge API для бота. Запуск из корня проекта:

    uv run --env-file .env python -m scripts.probe
"""
import os
from collections import Counter
from datetime import datetime

from bot.curseforge import CurseForgeClient
from bot.flavors import KNOWN_TYPES, build_flavor_map, format_flavors, mod_flavors

FOREVER_ID = 88568


def main() -> None:
    curseforge = CurseForgeClient(os.environ["CURSEFORGE_API_KEY"])

    types = curseforge.version_types()
    by_id = {t["id"]: t for t in types}
    print(f"== Типы версий: {len(types)} в API")
    for type_id, flavor in KNOWN_TYPES.items():
        t = by_id.get(type_id)
        found = "НЕТ В API" if t is None else f"{t.get('name')!r} slug={t.get('slug')!r}"
        print(f"  {type_id:>6} {flavor.group:<8} {flavor.label:<8} → {found}")

    flavor_map = build_flavor_map(types)
    print("== Типы из API, которых нет во встроенной таблице:")
    for t in types:
        if t["id"] not in KNOWN_TYPES:
            f = flavor_map[t["id"]]
            print(f"  {t['id']:>6} {t.get('name')!r} slug={t.get('slug')!r} → group={f.group} label={f.label!r}")

    mods = curseforge.latest_released()
    dates = [datetime.fromisoformat(m["dateReleased"]) for m in mods]
    print(f"== Поиск: {len(mods)} аддонов; по dateReleased убыв.: {dates == sorted(dates, reverse=True)}")
    if dates:
        print(f"   от {dates[-1]} до {dates[0]} (запас при опросе раз в 10 мин)")
    print(f"== classId в выдаче: {dict(Counter(m.get('classId') for m in mods))}")
    with_forever = sum(
        1 for m in mods if any(i.get("gameVersionTypeId") == FOREVER_ID for i in m.get("latestFilesIndexes") or [])
    )
    print(f"== Аддонов с файлами под Forever ({FOREVER_ID}): {with_forever}")
    print("== Первые 5:")
    for m in mods[:5]:
        print(
            f"  {m['id']} {m['name']!r} {m['dateReleased']} [{format_flavors(mod_flavors(m, flavor_map))}]"
            f" logo={bool(m.get('logo'))} screenshots={len(m.get('screenshots') or [])}"
        )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Запустить**

Run: `cd /home/gera/curse_bot && uv run --env-file .env python -m scripts.probe`

- [ ] **Step 3: Разобрать отчёт и принять решение**

Продолжать, только если всё так:
1. Строка `88568 forever Forever → ...` — имя или slug содержит «forever».
2. `по dateReleased убыв.: True`.
3. В `classId в выдаче` ровно одно значение.

Если пункт 1, 2 или 3 не выполнен — **остановиться и показать отчёт пользователю**: это меняет дизайн (вариант B из спеки, другой ID Forever, нужен `classId`).

Если среди «типов, которых нет во встроенной таблице» есть живые версии WoW, которые попали не в ту группу (например, Classic-версия без слова «classic» в имени), — добавить их ID в `KNOWN_TYPES` в `bot/flavors.py` и проверку в `test_known_types_map_to_groups`, затем `uv run pytest -v` (всё зелёное).

- [ ] **Step 4: Commit**

```bash
git add scripts/probe.py
# и bot/flavors.py tests/test_flavors.py, если меняли
git commit -m "chore: live CurseForge API probe script

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Клиент Telegram

**Files:**
- Create: `bot/telegram.py`
- Test: `tests/test_telegram.py`

**Interfaces:**
- Consumes: —
- Produces:
  - `API_URL = "https://api.telegram.org"`, `MAX_429_RETRIES = 3`
  - `class TelegramError(Exception)`
  - `class TelegramClient(token: str, chat_id: str, http: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep)` с методом `send_addon(caption: str, images: list[str]) -> None`: ≥2 картинки → `sendMediaGroup`, иначе/при ошибке → `sendPhoto` с `images[0]`, иначе/при ошибке → `sendMessage`. Если не прошёл ни один — `TelegramError` последнего. 429 с `retry_after` → `sleep(retry_after)` и повтор, до 3 повторов на метод.

- [ ] **Step 1: Написать падающие тесты**

`tests/test_telegram.py`:

```python
import json

import httpx
import pytest

from bot.telegram import API_URL, TelegramClient, TelegramError

OK = (200, {"ok": True, "result": {}})
IMAGES = ["https://img/logo.png", "https://img/s1.png", "https://img/s2.png"]


def fail(code=400, description="Bad Request", **parameters):
    body = {"ok": False, "error_code": code, "description": description}
    if parameters:
        body["parameters"] = parameters
    return code, body


class Recorder:
    """Фейковый Telegram: отдаёт заготовленные ответы по очереди и запоминает запросы."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.paths = []
        self.calls = []

    def __call__(self, request):
        self.paths.append(request.url.path)
        self.calls.append((request.url.path.rsplit("/", 1)[-1], json.loads(request.content)))
        status, body = self.responses.pop(0)
        return httpx.Response(status, json=body)

    @property
    def methods(self):
        return [method for method, _ in self.calls]


def make_client(handler, sleeps=None):
    http = httpx.Client(base_url=API_URL, transport=httpx.MockTransport(handler))
    sleep = sleeps.append if sleeps is not None else (lambda seconds: None)
    return TelegramClient("TOKEN", "-100", http=http, sleep=sleep)


def test_album_with_caption_on_first_photo():
    rec = Recorder(OK)
    make_client(rec).send_addon("cap", IMAGES)
    assert rec.paths == ["/botTOKEN/sendMediaGroup"]
    payload = rec.calls[0][1]
    assert payload["chat_id"] == "-100"
    assert payload["media"] == [
        {"type": "photo", "media": IMAGES[0], "caption": "cap", "parse_mode": "HTML"},
        {"type": "photo", "media": IMAGES[1]},
        {"type": "photo", "media": IMAGES[2]},
    ]


def test_single_image_uses_send_photo():
    rec = Recorder(OK)
    make_client(rec).send_addon("cap", IMAGES[:1])
    assert rec.calls == [
        ("sendPhoto", {"chat_id": "-100", "photo": IMAGES[0], "caption": "cap", "parse_mode": "HTML"})
    ]


def test_no_images_uses_send_message():
    rec = Recorder(OK)
    make_client(rec).send_addon("cap", [])
    assert rec.calls == [("sendMessage", {"chat_id": "-100", "text": "cap", "parse_mode": "HTML"})]


def test_album_failure_falls_back_to_photo_then_text():
    rec = Recorder(fail(description="WEBPAGE_MEDIA_EMPTY"), fail(description="wrong file"), OK)
    make_client(rec).send_addon("cap", IMAGES)
    assert rec.methods == ["sendMediaGroup", "sendPhoto", "sendMessage"]
    assert rec.calls[1][1]["photo"] == IMAGES[0]


def test_everything_fails_raises_last_error():
    rec = Recorder(*[fail(description="chat not found")] * 3)
    with pytest.raises(TelegramError, match="chat not found"):
        make_client(rec).send_addon("cap", IMAGES)


def test_429_waits_and_retries():
    sleeps = []
    rec = Recorder(fail(429, "Too Many Requests", retry_after=7), OK)
    make_client(rec, sleeps).send_addon("cap", [])
    assert sleeps == [7]
    assert rec.methods == ["sendMessage", "sendMessage"]


def test_429_gives_up_after_retries():
    sleeps = []
    rec = Recorder(*[fail(429, "Too Many Requests", retry_after=1)] * 4)
    with pytest.raises(TelegramError, match="429"):
        make_client(rec, sleeps).send_addon("cap", [])
    assert sleeps == [1, 1, 1]


def test_network_error_does_not_leak_token():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(TelegramError) as info:
        make_client(handler).send_addon("cap", [])
    assert "недоступен" in str(info.value)
    assert "TOKEN" not in str(info.value)
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `uv run pytest tests/test_telegram.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.telegram'`.

- [ ] **Step 3: Реализовать `bot/telegram.py`**

```python
"""Отправка уведомлений через Telegram Bot API."""
import logging
import time
from collections.abc import Callable

import httpx

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org"
MAX_429_RETRIES = 3


class TelegramError(Exception):
    pass


class TelegramClient:
    def __init__(
        self,
        token: str,
        chat_id: str,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._token = token
        self._chat_id = chat_id
        self._http = http or httpx.Client(base_url=API_URL, timeout=60)
        self._sleep = sleep

    def send_addon(self, caption: str, images: list[str]) -> None:
        """Альбом → фото логотипа → текст; следующий вариант — только если предыдущий не прошёл."""
        attempts: list[tuple[str, dict]] = []
        if len(images) >= 2:
            media = [{"type": "photo", "media": url} for url in images]
            media[0].update(caption=caption, parse_mode="HTML")
            attempts.append(("sendMediaGroup", {"chat_id": self._chat_id, "media": media}))
        if images:
            attempts.append(
                ("sendPhoto", {"chat_id": self._chat_id, "photo": images[0], "caption": caption, "parse_mode": "HTML"})
            )
        attempts.append(("sendMessage", {"chat_id": self._chat_id, "text": caption, "parse_mode": "HTML"}))

        error = None
        for method, payload in attempts:
            try:
                self._call(method, payload)
                return
            except TelegramError as e:
                log.warning("%s", e)
                error = e
        raise error

    def _call(self, method: str, payload: dict) -> dict:
        for attempt in range(MAX_429_RETRIES + 1):
            try:
                response = self._http.post(f"/bot{self._token}/{method}", json=payload)
            except httpx.HTTPError as e:
                # в тексте сетевых ошибок httpx нет URL, так что токен сюда не попадает
                raise TelegramError(f"{method}: Telegram недоступен: {e}") from e
            try:
                body = response.json()
            except ValueError:
                body = {}
            if body.get("ok"):
                return body["result"]
            retry_after = (body.get("parameters") or {}).get("retry_after")
            if response.status_code == 429 and retry_after and attempt < MAX_429_RETRIES:
                log.warning("Telegram просит подождать %s с", retry_after)
                self._sleep(retry_after)
                continue
            raise TelegramError(f"{method}: {response.status_code} {body.get('description') or response.text[:200]}")
        raise AssertionError("unreachable")
```

- [ ] **Step 4: Тесты проходят**

Run: `uv run pytest tests/test_telegram.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add bot/telegram.py tests/test_telegram.py
git commit -m "feat: Telegram client with album/photo/text fallback

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Цикл бота и CLI

**Files:**
- Create: `bot/main.py`, `bot/__main__.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `load_config`, `ConfigError`, `CurseForgeClient`, `CurseForgeError`, `TelegramClient`, `TelegramError`, `Storage`, `build_flavor_map`, `mod_flavors`, `passes_filter`, `format_flavors`, `build_caption`, `pick_images`
- Produces:
  - `SEND_PAUSE = 3`
  - `class Bot(curseforge, telegram, storage: Storage, flavor_map: dict[int, Flavor], wanted: frozenset[str], sleep=time.sleep)` с методами `run_once()`, `run_forever(interval: int)`, `send_latest(count: int)`. `curseforge` — любой объект с `latest_released() -> list[dict]`; `telegram` — любой объект с `send_addon(caption, images)`.
  - `main(argv: list[str] | None = None) -> int`; `python -m bot [--send-latest N]`

- [ ] **Step 1: Написать падающие тесты**

`tests/test_main.py`:

```python
import pytest

from bot.curseforge import CurseForgeError
from bot.flavors import CLASSIC, FOREVER, build_flavor_map
from bot.main import SEND_PAUSE, Bot
from bot.storage import Storage
from bot.telegram import TelegramError


def mod(mod_id, *type_ids):
    return {
        "id": mod_id,
        "name": f"Addon {mod_id}",
        "summary": "",
        "links": {},
        "authors": [],
        "categories": [],
        "logo": {"url": f"https://img/{mod_id}.png"},
        "screenshots": [],
        "latestFilesIndexes": [{"gameVersionTypeId": t} for t in (type_ids or (517,))],
    }


class FakeCurseForge:
    def __init__(self, *pages):
        self.pages = list(pages)

    def latest_released(self):
        return self.pages.pop(0)


class FakeTelegram:
    def __init__(self, fail_times=0):
        self.sent = []
        self.fail_times = fail_times

    def send_addon(self, caption, images):
        if self.fail_times:
            self.fail_times -= 1
            raise TelegramError("sendPhoto: 400 chat not found")
        self.sent.append((caption, images))

    @property
    def names(self):
        return [caption.split("</b>")[0].removeprefix("🆕 <b>") for caption, _ in self.sent]


def make_bot(curseforge, telegram, storage=None, wanted=frozenset(), sleep=lambda seconds: None):
    return Bot(curseforge, telegram, storage or Storage(":memory:"), build_flavor_map([]), wanted, sleep=sleep)


def test_first_run_is_baseline():
    telegram = FakeTelegram()
    bot = make_bot(FakeCurseForge([mod(2), mod(1)], [mod(2), mod(1)]), telegram)
    bot.run_once()
    bot.run_once()
    assert telegram.sent == []


def test_new_addons_sent_oldest_first_with_pause():
    telegram = FakeTelegram()
    sleeps = []
    bot = make_bot(FakeCurseForge([mod(1)], [mod(4), mod(3), mod(2), mod(1)]), telegram, sleep=sleeps.append)
    bot.run_once()
    bot.run_once()
    assert telegram.names == ["Addon 2", "Addon 3", "Addon 4"]
    assert telegram.sent[0][1] == ["https://img/2.png"]
    assert sleeps == [SEND_PAUSE] * 3


def test_sent_addon_not_repeated():
    telegram = FakeTelegram()
    bot = make_bot(FakeCurseForge([mod(1)], [mod(2), mod(1)], [mod(2), mod(1)]), telegram)
    for _ in range(3):
        bot.run_once()
    assert telegram.names == ["Addon 2"]


def test_filtered_addon_marked_seen_without_sending():
    telegram = FakeTelegram()
    storage = Storage(":memory:")
    page = [mod(3, 88568), mod(2, 517)]
    bot = make_bot(FakeCurseForge([mod(1)], page, page), telegram, storage, wanted=frozenset({FOREVER}))
    for _ in range(3):
        bot.run_once()
    assert telegram.names == ["Addon 3"]
    assert storage.filter_unseen([2, 3]) == []


def test_failed_send_retried_next_cycle():
    telegram = FakeTelegram(fail_times=1)
    storage = Storage(":memory:")
    bot = make_bot(FakeCurseForge([mod(1)], [mod(2), mod(1)], [mod(2), mod(1)]), telegram, storage)
    bot.run_once()
    bot.run_once()
    assert telegram.names == []
    assert storage.filter_unseen([2]) == [2]
    bot.run_once()
    assert telegram.names == ["Addon 2"]


def test_send_latest_ignores_storage_and_filter():
    telegram = FakeTelegram()
    storage = Storage(":memory:")
    bot = make_bot(
        FakeCurseForge([mod(3, 88568), mod(2), mod(1)]), telegram, storage, wanted=frozenset({CLASSIC})
    )
    bot.send_latest(2)
    assert telegram.names == ["Addon 2", "Addon 3"]
    assert storage.is_empty()


def test_run_forever_survives_curseforge_errors():
    class Stop(Exception):
        pass

    calls = []

    class FlakyCurseForge:
        def latest_released(self):
            calls.append(1)
            if len(calls) == 1:
                raise CurseForgeError("CurseForge ответил 503")
            return [mod(1)]

    def sleep(seconds):
        assert seconds == 600
        if len(calls) >= 2:
            raise Stop

    storage = Storage(":memory:")
    bot = make_bot(FlakyCurseForge(), FakeTelegram(), storage, sleep=sleep)
    with pytest.raises(Stop):
        bot.run_forever(600)
    assert len(calls) == 2
    assert not storage.is_empty()
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `uv run pytest tests/test_main.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.main'`.

- [ ] **Step 3: Реализовать `bot/main.py`**

```python
"""Цикл опроса CurseForge и отправки новых аддонов WoW в Telegram."""
import argparse
import logging
import time
from collections.abc import Callable

from bot.config import ConfigError, load_config
from bot.curseforge import CurseForgeClient, CurseForgeError
from bot.flavors import Flavor, build_flavor_map, format_flavors, mod_flavors, passes_filter
from bot.formatter import build_caption, pick_images
from bot.storage import Storage
from bot.telegram import TelegramClient, TelegramError

log = logging.getLogger(__name__)

SEND_PAUSE = 3  # секунд между сообщениями, чтобы не упереться в лимиты Telegram


class Bot:
    def __init__(
        self,
        curseforge,
        telegram,
        storage: Storage,
        flavor_map: dict[int, Flavor],
        wanted: frozenset[str],
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._curseforge = curseforge
        self._telegram = telegram
        self._storage = storage
        self._flavor_map = flavor_map
        self._wanted = wanted
        self._sleep = sleep

    def run_forever(self, interval: int) -> None:
        while True:
            try:
                self.run_once()
            except CurseForgeError as e:
                log.error("%s", e)
            self._sleep(interval)

    def run_once(self) -> None:
        mods = self._curseforge.latest_released()
        if self._storage.is_empty():
            self._storage.mark_seen(m["id"] for m in mods)
            log.info("baseline: %d addons", len(mods))
            return

        unseen = set(self._storage.filter_unseen([m["id"] for m in mods]))
        for mod in reversed(mods):  # API отдаёт от новых к старым, а в канал — по порядку выхода
            if mod["id"] not in unseen:
                continue
            flavors = mod_flavors(mod, self._flavor_map)
            if not passes_filter(flavors, self._wanted):
                log.info("пропуск %s «%s»: версии [%s] не в FLAVORS", mod["id"], mod["name"], format_flavors(flavors))
                self._storage.mark_seen([mod["id"]])
                continue
            if self._send(mod, flavors):
                self._storage.mark_seen([mod["id"]])

    def send_latest(self, count: int) -> None:
        """Разово отправить count последних аддонов — без фильтра и без пометки в базе."""
        for mod in reversed(self._curseforge.latest_released()[:count]):
            self._send(mod, mod_flavors(mod, self._flavor_map))

    def _send(self, mod: dict, flavors: list[Flavor]) -> bool:
        try:
            self._telegram.send_addon(build_caption(mod, flavors), pick_images(mod))
        except TelegramError as e:
            log.error("не удалось отправить %s «%s»: %s", mod["id"], mod["name"], e)
            return False
        log.info("отправлен %s «%s»", mod["id"], mod["name"])
        self._sleep(SEND_PAUSE)
        return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m bot", description="Уведомления о новых аддонах WoW с CurseForge в Telegram"
    )
    parser.add_argument(
        "--send-latest", type=int, metavar="N", help="разово отправить N последних аддонов (проверка) и выйти"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx на уровне INFO пишет URL запросов, а в URL Telegram — токен бота
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        config = load_config()
    except ConfigError as e:
        log.error("%s", e)
        return 2

    curseforge = CurseForgeClient(config.curseforge_api_key)
    try:
        version_types = curseforge.version_types()
    except CurseForgeError as e:
        log.warning("типы версий не загружены (%s), использую встроенный список", e)
        version_types = []

    bot = Bot(
        curseforge,
        TelegramClient(config.telegram_bot_token, config.telegram_chat_id),
        Storage(config.db_path),
        build_flavor_map(version_types),
        config.flavors,
    )

    if args.send_latest:
        try:
            bot.send_latest(args.send_latest)
        except CurseForgeError as e:
            log.error("%s", e)
            return 1
        return 0

    log.info(
        "старт: опрос каждые %d с, FLAVORS=%s", config.poll_interval, ",".join(sorted(config.flavors)) or "все"
    )
    bot.run_forever(config.poll_interval)
    return 0
```

`bot/__main__.py`:

```python
from bot.main import main

raise SystemExit(main())
```

- [ ] **Step 4: Тесты проходят**

Run: `uv run pytest -v`
Expected: все тесты проекта зелёные (8 + 10 + 10 + 5 + 5 + 8 + 7 = 53 passed).

- [ ] **Step 5: Проверить ошибку конфигурации из CLI**

Run: `cd /home/gera/curse_bot && env -u CURSEFORGE_API_KEY -u TELEGRAM_BOT_TOKEN -u TELEGRAM_CHAT_ID uv run python -m bot; echo "exit=$?"`
Expected: строка `ERROR bot.main: Не заданы обязательные переменные: CURSEFORGE_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID` и `exit=2`.

Run: `uv run python -m bot --help`
Expected: справка с `--send-latest N`.

- [ ] **Step 6: Commit**

```bash
git add bot/main.py bot/__main__.py tests/test_main.py
git commit -m "feat: polling loop, baseline and CLI entry point

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Запуск: Docker, `.env.example`, README

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`
- Modify: `README.md` (сейчас пустой)

**Interfaces:**
- Consumes: `python -m bot`
- Produces: `docker compose up -d --build` запускает бота с `restart: unless-stopped` и базой в `./data`.

- [ ] **Step 1: `.env.example`**

```dotenv
# Ключ CurseForge API: https://console.curseforge.com
CURSEFORGE_API_KEY=
# Токен бота от @BotFather
TELEGRAM_BOT_TOKEN=
# Канал (@имя_канала или -100…) или чат; бот должен быть администратором канала
TELEGRAM_CHAT_ID=
# О каких версиях сообщать: retail, classic, forever через запятую; пусто — обо всех
FLAVORS=
# Секунд между проверками
POLL_INTERVAL=600
# Путь к базе (в Docker переопределяется на /app/data/bot.db)
DB_PATH=data/bot.db
```

- [ ] **Step 2: `Dockerfile`, `.dockerignore`, `docker-compose.yml`**

`Dockerfile`:

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# держать в соответствии с dependencies в pyproject.toml
RUN pip install --no-cache-dir "httpx>=0.27,<1"

COPY bot ./bot

CMD ["python", "-m", "bot"]
```

`.dockerignore`:

```
.env
.venv
data
tests
docs
.git
**/__pycache__
```

`docker-compose.yml`:

```yaml
services:
  bot:
    build: .
    env_file: .env
    environment:
      DB_PATH: /app/data/bot.db
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

- [ ] **Step 3: Проверить сборку образа**

Run: `cd /home/gera/curse_bot && docker compose build`
Expected: образ собран без ошибок. Если Docker-демон в WSL не запущен (`Cannot connect to the Docker daemon`), отметить это в отчёте и не считать провалом задачи.

- [ ] **Step 4: `README.md`**

````markdown
# curse_bot

Telegram-бот, который следит за новыми аддонами World of Warcraft на CurseForge и публикует
каждый в канал: альбом (логотип + скриншоты), название, автор, категории, версии игры
(Retail / Classic / Forever), краткое описание и ссылка.

## Подготовка

1. Ключ CurseForge API — https://console.curseforge.com.
2. Бот — у @BotFather, получить токен.
3. Добавить бота администратором канала (право публиковать сообщения).
4. `cp .env.example .env` и заполнить. `TELEGRAM_CHAT_ID` — `@имя_канала` или числовой id `-100…`.

`FLAVORS` — о каких версиях сообщать (`retail`, `classic`, `forever` через запятую; пусто — обо всех).
Аддон проходит фильтр, если у него есть файлы хотя бы под одну из этих версий на момент выхода.

## Запуск в Docker

```bash
docker compose up -d --build
docker compose logs -f
```

База виденных аддонов лежит в `./data/bot.db`. При самом первом запуске бот только запоминает
текущие 50 свежих аддонов (`baseline: 50 addons` в логе) и ничего не отправляет — уведомления
пойдут о тех, что выйдут после этого.

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
````

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore docker-compose.yml .env.example README.md
git commit -m "chore: Docker setup, env example and README

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Живая проверка отправки (checkpoint, нужен Telegram)

Сообщения уходят в реальный канал пользователя — **перед запуском спросить разрешения** и убедиться, что в `.env` заполнены `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID`.

- [ ] **Step 1: Отправить два последних аддона**

Run: `cd /home/gera/curse_bot && uv run --env-file .env python -m bot --send-latest 2`
Expected: в логе две строки `отправлен <id> «<name>»`, `exit 0`; в канале два сообщения с картинками и подписью. Попросить пользователя посмотреть на них в Telegram.

- [ ] **Step 2: Проверить baseline**

Run: `cd /home/gera/curse_bot && rm -f data/bot.db && timeout 20 uv run --env-file .env python -m bot; echo "exit=$?"`
Expected: в логе `старт: ...` и `baseline: 50 addons`, ничего не отправлено, `exit=124` (остановлено `timeout`).

- [ ] **Step 3: Запуск на постоянку — решение пользователя**

Предложить `docker compose up -d --build` (или systemd из README) и выполнить только после согласия.
