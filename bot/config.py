"""Bot settings from environment variables."""
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from bot.flavors import GROUPS

REQUIRED = ("CURSEFORGE_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    curseforge_api_key: str = field(repr=False)
    telegram_bot_token: str = field(repr=False)
    telegram_chat_id: str
    flavors: frozenset[str]  # empty - report all versions
    poll_interval: int
    db_path: Path
    heartbeat_file: Path | None = None  # file for the liveness probe; None - do not write
    admin_ids: frozenset[int] = frozenset()  # who the bot answers commands for; empty - commands disabled


def load_config(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env

    missing = [name for name in REQUIRED if not env.get(name, "").strip()]
    if missing:
        raise ConfigError(f"Required variables are not set: {', '.join(missing)}")

    flavors = frozenset(f.strip().lower() for f in env.get("FLAVORS", "").split(",") if f.strip())
    unknown = flavors - GROUPS
    if unknown:
        raise ConfigError(
            f"Unknown FLAVORS values: {', '.join(sorted(unknown))}; allowed: retail, classic, forever"
        )

    try:
        poll_interval = int(env.get("POLL_INTERVAL", "").strip() or "600")
    except ValueError:
        poll_interval = 0
    if poll_interval <= 0:
        raise ConfigError("POLL_INTERVAL must be a positive integer number of seconds")

    try:
        admin_ids = frozenset(int(i) for i in env.get("TELEGRAM_ADMIN_IDS", "").split(",") if i.strip())
    except ValueError:
        raise ConfigError("TELEGRAM_ADMIN_IDS must be comma-separated numeric Telegram user ids") from None

    return Config(
        curseforge_api_key=env["CURSEFORGE_API_KEY"].strip(),
        telegram_bot_token=env["TELEGRAM_BOT_TOKEN"].strip(),
        telegram_chat_id=env["TELEGRAM_CHAT_ID"].strip(),
        flavors=flavors,
        poll_interval=poll_interval,
        db_path=Path(env.get("DB_PATH", "").strip() or "data/bot.db"),
        heartbeat_file=Path(heartbeat) if (heartbeat := env.get("HEARTBEAT_FILE", "").strip()) else None,
        admin_ids=admin_ids,
    )
