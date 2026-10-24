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
