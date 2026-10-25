from string import Formatter

import pytest

from bot.i18n import DEFAULT, LANGUAGE_NAMES, LANGUAGES, TEXTS, menu, pick, t


def placeholders(text):
    return {name for _, name, _, _ in Formatter().parse(text) if name}


@pytest.mark.parametrize("key", sorted(TEXTS))
def test_every_text_has_all_languages_with_the_same_placeholders(key):
    variants = TEXTS[key]
    assert set(variants) == set(LANGUAGES)
    expected = placeholders(variants[DEFAULT])
    for lang in LANGUAGES:
        assert placeholders(variants[lang]) == expected, lang


def test_t_formats_and_falls_back_to_default():
    assert t("ru", "ago.min", n=3) == "3 мин"
    assert t("en", "ago.min", n=3) == "3 min"
    assert t("de", "ago.min", n=3) == "3 min"


@pytest.mark.parametrize(
    "code, expected", [("ru", "ru"), ("ru-RU", "ru"), ("RU", "ru"), ("en", "en"), ("de", "en"), (None, "en"), ("", "en")]
)
def test_pick_from_telegram_language_code(code, expected):
    assert pick(code) == expected


def test_menu_has_the_same_commands_in_every_language():
    commands = [command for command, _ in menu(DEFAULT)]
    assert "lang" in commands
    for lang in LANGUAGES:
        assert [command for command, _ in menu(lang)] == commands
        assert all(description for _, description in menu(lang))


def test_language_names():
    assert LANGUAGE_NAMES == {"en": "English", "ru": "Русский"}
