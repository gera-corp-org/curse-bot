"""Texts of the bot's private-chat replies in English and Russian.

Only what the bot says to people is translated; channel posts consist of CurseForge data,
and logs stay in English.
"""

LANGUAGES = ("en", "ru")
DEFAULT = "en"
LANGUAGE_NAMES = {"en": "English", "ru": "Русский"}

COMMANDS = ("status", "latest", "pending", "flavors", "lang", "help")

TEXTS: dict[str, dict[str, str]] = {
    # command menu in the Telegram client
    "menu.status": {
        "en": "Status: last poll, queue, sent in the last 24 h",
        "ru": "Состояние: последний опрос, очередь, отправлено за сутки",
    },
    "menu.latest": {"en": "Latest approved addons (/latest 5)", "ru": "Последние одобренные аддоны (/latest 5)"},
    "menu.pending": {"en": "Addons awaiting moderation", "ru": "Аддоны, ждущие модерации"},
    "menu.flavors": {
        "en": "Version filter: /flavors forever,retail | all | reset",
        "ru": "Фильтр версий: /flavors forever,retail | all | reset",
    },
    "menu.lang": {"en": "Reply language: /lang en | ru", "ru": "Язык ответов: /lang en | ru"},
    "menu.help": {"en": "List of commands", "ru": "Список команд"},
    # /help and unknown input
    "help.title": {
        "en": "<b>curse-bot</b> — new WoW addons from CurseForge",
        "ru": "<b>curse-bot</b> — новые аддоны WoW с CurseForge",
    },
    "help.your_id": {"en": "Your id: <code>{user_id}</code>", "ru": "Ваш id: <code>{user_id}</code>"},
    "unknown_command": {
        "en": "Unknown command /{command}. See /help for the list of commands",
        "ru": "Не знаю команду /{command}. Список команд — /help",
    },
    "curseforge_error": {"en": "Could not query CurseForge: {error}", "ru": "Не удалось спросить CurseForge: {error}"},
    # /status
    "status.last_poll": {"en": "Last poll: {when}", "ru": "Последний опрос: {when}"},
    "status.never": {"en": "never", "ru": "ещё не было"},
    "status.ago": {"en": "{at} UTC, {ago} ago", "ru": "{at} UTC, {ago} назад"},
    "status.next_id": {"en": "Next id: {cursor}", "ru": "Следующий id: {cursor}"},
    "status.pending": {"en": "Awaiting moderation: {count}", "ru": "Ждут модерации: {count}"},
    "status.sent": {"en": "Sent to channel in 24 h: {count}", "ru": "В канал за 24 ч: {count}"},
    "versions": {"en": "Versions: {state}", "ru": "Версии: {state}"},
    # /pending
    "pending.empty": {"en": "The waiting queue is empty.", "ru": "Очередь ожидания пуста."},
    "pending.title": {"en": "<b>Awaiting moderation: {count}</b>", "ru": "<b>Ждут модерации: {count}</b>"},
    "pending.item": {"en": "• {title} — {status}, waiting {waited}", "ru": "• {title} — {status}, ждёт {waited}"},
    "pending.missing": {
        "en": "• id {mod_id} — not in API, waiting {waited}",
        "ru": "• id {mod_id} — нет в API, ждёт {waited}",
    },
    "pending.more": {"en": "…and {count} more", "ru": "…и ещё {count}"},
    "mod_status.1": {"en": "in moderation", "ru": "на модерации"},
    "mod_status.2": {"en": "needs changes", "ru": "нужны правки"},
    "mod_status.3": {"en": "under review", "ru": "на проверке"},
    "mod_status.4": {"en": "approved, waiting for files", "ru": "одобрен, ждёт файлов"},
    "mod_status.6": {"en": "changes made", "ru": "правки внесены"},
    "mod_status.10": {"en": "under review", "ru": "на проверке"},
    "mod_status.other": {"en": "status {status}", "ru": "статус {status}"},
    # /latest
    "latest.bad_count": {"en": "Give a number from 1 to {max}: /latest 5", "ru": "Укажите число от 1 до {max}: /latest 5"},
    "latest.none": {
        "en": "Found no approved WoW addons among the latest ids.",
        "ru": "Не нашёл одобренных аддонов WoW среди последних id.",
    },
    "latest.send_failed": {"en": "Could not send '{name}': {error}", "ru": "Не удалось отправить «{name}»: {error}"},
    # /flavors
    "flavors.usage": {
        "en": "Set: /flavors forever,retail · no filter: /flavors all · as in settings: /flavors reset",
        "ru": "Задать: /flavors forever,retail · без фильтра: /flavors all · как в настройках: /flavors reset",
    },
    "flavors.unknown": {
        "en": "Unknown versions: {names}. Allowed: retail, classic, forever.",
        "ru": "Неизвестные версии: {names}. Можно: retail, classic, forever.",
    },
    "flavors.all": {"en": "all", "ru": "все"},
    "flavors.overridden": {"en": "set by /flavors", "ru": "задан командой /flavors"},
    "flavors.from_settings": {"en": "from settings", "ru": "из настроек"},
    # /lang
    "lang.current": {"en": "Language: {name}", "ru": "Язык: {name}"},
    "lang.choose": {"en": "Choose the reply language:", "ru": "Выберите язык ответов:"},
    "lang.unknown": {"en": "Unknown language {code}. Available: en, ru", "ru": "Не знаю язык {code}. Есть: en, ru"},
    # durations
    "ago.min": {"en": "{n} min", "ru": "{n} мин"},
    "ago.h": {"en": "{n} h", "ru": "{n} ч"},
    "ago.d": {"en": "{n} d", "ru": "{n} дн"},
}


def t(lang: str, key: str, **params) -> str:
    """The text for key in lang (DEFAULT if lang is unknown), with params substituted."""
    variants = TEXTS[key]
    return variants.get(lang, variants[DEFAULT]).format(**params)


def pick(language_code: str | None) -> str:
    """Reply language from the Telegram client's language_code: ru… → ru, anything else → en."""
    return "ru" if (language_code or "").lower().startswith("ru") else DEFAULT


def menu(lang: str) -> list[tuple[str, str]]:
    """(command, description) pairs for setMyCommands and /help."""
    return [(command, t(lang, f"menu.{command}")) for command in COMMANDS]
