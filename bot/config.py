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
