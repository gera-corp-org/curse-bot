import logging
from datetime import timedelta

import pytest

from bot.commands import MENU, OFFSET_KEY, Commands
from bot.curseforge import CurseForgeError
from bot.flavors import CLASSIC, FOREVER, RETAIL
from bot.storage import Storage
from bot.telegram import TelegramError
from tests.fakes import NOW, Clock, FakeCurseForge, FakeTelegram, make_bot, mod, new

ADMIN = 111
STRANGER = 999


def message(text, user=ADMIN, chat_type="private", update_id=1):
    return {
        "update_id": update_id,
        "message": {
            "message_id": 5,
            "from": {"id": user, "username": "someone"},
            "chat": {"id": user, "type": chat_type},
            "text": text,
        },
    }


class Monotonic:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def setup(*mods, cursor=None, wanted=frozenset(), updates=None, curseforge=None):
    curseforge = curseforge or FakeCurseForge(*mods)
    storage = Storage(":memory:")
    if mods or cursor is not None:
        storage.set_meta("next_id", str(cursor if cursor is not None else max(curseforge.mods) + 1))
    clock = Clock()
    monotonic = Monotonic()
    telegram = FakeTelegram(updates=updates, on_poll=monotonic.advance)
    bot = make_bot(curseforge, telegram=telegram, storage=storage, wanted=wanted, clock=clock)
    commands = Commands(
        bot, telegram, storage, frozenset({ADMIN}), now=clock, monotonic=monotonic, sleep=monotonic.advance
    )
    return commands, telegram, storage, clock


def reply(telegram):
    assert telegram.texts, "бот ничего не ответил"
    chat_id, text = telegram.texts[-1]
    assert chat_id == ADMIN
    return text


# --- доступ ---


def test_stranger_is_ignored_and_logged_once(caplog):
    commands, telegram, _, _ = setup(mod(1))
    with caplog.at_level(logging.INFO):
        commands.handle(message("/status", user=STRANGER))
        commands.handle(message("/status", user=STRANGER))
    assert telegram.texts == []
    hits = [r for r in caplog.records if str(STRANGER) in r.getMessage()]
    assert len(hits) == 1
    assert "TELEGRAM_ADMIN_IDS" in hits[0].getMessage()


def test_group_chats_are_ignored_even_for_admin():
    commands, telegram, _, _ = setup(mod(1))
    commands.handle(message("/status", chat_type="group"))
    assert telegram.texts == []


def test_non_message_updates_are_ignored():
    commands, telegram, _, _ = setup(mod(1))
    commands.handle({"update_id": 3, "edited_message": {}})
    commands.handle({"update_id": 4})
    assert telegram.texts == []


# --- /help, неизвестное ---


@pytest.mark.parametrize("text", ["/help", "/start", "привет"])
def test_help_lists_commands(text):
    commands, telegram, _, _ = setup(mod(1))
    commands.handle(message(text))
    answer = reply(telegram)
    for command, _ in MENU:
        assert f"/{command}" in answer


def test_unknown_command():
    commands, telegram, _, _ = setup(mod(1))
    commands.handle(message("/frobnicate"))
    assert "/frobnicate" in reply(telegram)
    assert "/help" in reply(telegram)


def test_command_with_bot_username_suffix():
    commands, telegram, _, _ = setup(mod(1))
    commands.handle(message("/status@curse_bot"))
    assert "Следующий id" in reply(telegram)


# --- /status ---


def test_status_before_first_cycle():
    commands, telegram, _, _ = setup()
    commands.handle(message("/status"))
    answer = reply(telegram)
    assert "ещё не было" in answer
    assert "Ждут модерации: 0" in answer


def test_status_after_cycles():
    commands, telegram, storage, clock = setup(mod(1), wanted=frozenset({FOREVER}))
    commands._bot.run_once()
    storage.add_pending([7, 8], NOW)
    storage.record_sent(5, NOW - timedelta(hours=1))
    storage.record_sent(6, NOW - timedelta(hours=30))
    clock.value = NOW + timedelta(minutes=3)
    commands.handle(message("/status"))
    answer = reply(telegram)
    assert "3 мин назад" in answer
    assert "Следующий id: 2" in answer
    assert "Ждут модерации: 2" in answer
    assert "В канал за 24 ч: 1" in answer
    assert "Forever" in answer and "из настроек" in answer


# --- /pending ---


def test_pending_lists_mods_with_status_and_age():
    named = new(5)
    named["name"] = "Soul <Fragment>"
    named["links"] = {"websiteUrl": "https://www.curseforge.com/wow/addons/soul"}
    commands, telegram, storage, clock = setup(mod(1), named, mod(6, files=False))
    storage.add_pending([5, 6, 9], NOW - timedelta(hours=3))
    commands.handle(message("/pending"))
    answer = reply(telegram)
    assert "Ждут модерации: 3" in answer
    assert '<a href="https://www.curseforge.com/wow/addons/soul">Soul &lt;Fragment&gt;</a>' in answer
    assert "на модерации" in answer
    assert "одобрен, ждёт файлов" in answer
    assert "id 9" in answer and "нет в API" in answer
    assert "3 ч" in answer


def test_pending_empty():
    commands, telegram, _, _ = setup(mod(1))
    commands.handle(message("/pending"))
    assert "пуста" in reply(telegram)


def test_pending_truncated_to_limit():
    mods = [new(i) for i in range(10, 40)]
    commands, telegram, storage, _ = setup(mod(1), *mods)
    storage.add_pending(range(10, 40), NOW)
    commands.handle(message("/pending"))
    answer = reply(telegram)
    assert answer.count("•") == 20
    assert "и ещё 10" in answer


def test_pending_reports_curseforge_errors():
    class Broken(FakeCurseForge):
        def get_mods(self, ids):
            raise CurseForgeError("CurseForge недоступен: boom")

    commands, telegram, storage, _ = setup(cursor=5, curseforge=Broken())
    storage.add_pending([7], NOW)
    commands.handle(message("/pending"))
    assert "недоступен" in reply(telegram)


# --- /latest ---


def test_latest_sends_addons_to_admin_chat_not_channel():
    commands, telegram, _, _ = setup(mod(1), new(2), mod(3), mod(4, game=432), mod(5))
    commands.handle(message("/latest 2"))
    assert telegram.sent == []
    assert [(chat, caption.split("</b>")[0]) for chat, caption, _ in telegram.private] == [
        (ADMIN, "🆕 <b>Addon 3"),
        (ADMIN, "🆕 <b>Addon 5"),
    ]


def test_latest_defaults_to_three():
    commands, telegram, _, _ = setup(*[mod(i) for i in range(1, 8)])
    commands.handle(message("/latest"))
    assert len(telegram.private) == 3


@pytest.mark.parametrize("arg", ["0", "11", "abc", "-1"])
def test_latest_rejects_bad_count(arg):
    commands, telegram, _, _ = setup(mod(1))
    commands.handle(message(f"/latest {arg}"))
    assert telegram.private == []
    assert "1 до 10" in reply(telegram)


def test_latest_reports_send_failure():
    commands, telegram, _, _ = setup(mod(1))
    telegram.fail_times = 1
    commands.handle(message("/latest 1"))
    assert "не удалось" in reply(telegram).lower()


# --- /flavors ---


def test_flavors_shows_current():
    commands, telegram, _, _ = setup(mod(1), wanted=frozenset({RETAIL}))
    commands.handle(message("/flavors"))
    answer = reply(telegram)
    assert "Retail" in answer and "из настроек" in answer


def test_flavors_set_all_and_reset():
    commands, telegram, _, _ = setup(mod(1), wanted=frozenset({RETAIL}))
    bot = commands._bot

    commands.handle(message("/flavors forever, classic"))
    assert bot.wanted() == frozenset({FOREVER, CLASSIC})
    assert "задан командой" in reply(telegram)

    commands.handle(message("/flavors all"))
    assert bot.wanted() == frozenset()
    assert "все" in reply(telegram)

    commands.handle(message("/flavors reset"))
    assert bot.wanted() == frozenset({RETAIL}) and not bot.wanted_overridden()
    assert "из настроек" in reply(telegram)


def test_flavors_rejects_unknown():
    commands, telegram, _, _ = setup(mod(1), wanted=frozenset({RETAIL}))
    commands.handle(message("/flavors wotlk"))
    assert commands._bot.wanted() == frozenset({RETAIL})
    assert "wotlk" in reply(telegram)


# --- ожидание и long polling ---


def test_wait_polls_until_deadline_and_handles_updates():
    commands, telegram, storage, _ = setup(mod(1), updates=[[message("/help", update_id=41)], []])
    commands.wait(45)
    assert telegram.polls == [(None, 30), (42, 15)]
    assert storage.get_meta(OFFSET_KEY) == "42"
    assert telegram.texts  # /help обработан


def test_wait_resumes_from_stored_offset():
    commands, telegram, storage, _ = setup(mod(1))
    storage.set_meta(OFFSET_KEY, "100")
    commands.wait(10)
    assert telegram.polls == [(100, 10)]


def test_wait_survives_telegram_errors():
    commands, telegram, _, _ = setup(mod(1), updates=[TelegramError("getUpdates: 502 Bad Gateway"), []])
    commands.wait(40)  # ошибка → пауза 10 с → ещё один опрос на оставшиеся 30 с
    assert len(telegram.polls) == 2


def test_failing_command_is_logged_and_not_retried(caplog):
    commands, telegram, storage, _ = setup(mod(1), updates=[[message("/status", update_id=7)]])

    def boom(_update):
        raise RuntimeError("сломалось")

    commands.handle = boom
    with caplog.at_level(logging.ERROR):
        commands.wait(30)
    assert storage.get_meta(OFFSET_KEY) == "8"
    assert any("команд" in r.getMessage() for r in caplog.records)


def test_register_menu_sets_commands_and_tolerates_errors():
    commands, telegram, _, _ = setup(mod(1))
    commands.register_menu()
    assert telegram.menu == MENU

    def broken(_commands):
        raise TelegramError("setMyCommands: 400")

    telegram.set_my_commands = broken
    commands.register_menu()  # не падает
