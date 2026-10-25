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
    """Fake Telegram: returns canned responses in order and records requests."""

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
    assert "unreachable" in str(info.value)
    assert "TOKEN" not in str(info.value)


def test_non_dict_json_body_is_telegram_error():
    def handler(request):
        return httpx.Response(500, json=[1, 2])

    with pytest.raises(TelegramError, match="500"):
        make_client(handler).send_addon("cap", [])


def test_send_addon_to_other_chat():
    rec = Recorder(OK)
    make_client(rec).send_addon("cap", [], chat_id=42)
    assert rec.calls == [("sendMessage", {"chat_id": 42, "text": "cap", "parse_mode": "HTML"})]


def test_send_text():
    rec = Recorder(OK)
    make_client(rec).send_text(42, "<b>hi</b>")
    assert rec.calls == [
        ("sendMessage", {"chat_id": 42, "text": "<b>hi</b>", "parse_mode": "HTML",
                         "link_preview_options": {"is_disabled": True}})
    ]


def test_get_updates_long_polls_messages_only():
    updates = [{"update_id": 7, "message": {"text": "/status"}}]
    rec = Recorder((200, {"ok": True, "result": updates}))
    assert make_client(rec).get_updates(offset=5, timeout=30) == updates
    assert rec.calls == [
        ("getUpdates", {"offset": 5, "timeout": 30, "allowed_updates": ["message", "callback_query"]})
    ]


def test_get_updates_without_offset():
    rec = Recorder((200, {"ok": True, "result": []}))
    make_client(rec).get_updates(offset=None, timeout=10)
    assert rec.calls == [("getUpdates", {"timeout": 10, "allowed_updates": ["message", "callback_query"]})]


def test_set_my_commands():
    rec = Recorder((200, {"ok": True, "result": True}))
    make_client(rec).set_my_commands([("status", "Status"), ("help", "Help")])
    assert rec.calls == [
        ("setMyCommands", {"commands": [{"command": "status", "description": "Status"},
                                        {"command": "help", "description": "Help"}]})
    ]


def test_send_text_with_buttons():
    rec = Recorder(OK)
    make_client(rec).send_text(42, "Choose", buttons=[("English", "lang:en"), ("Русский", "lang:ru")])
    payload = rec.calls[0][1]
    assert payload["reply_markup"] == {
        "inline_keyboard": [[{"text": "English", "callback_data": "lang:en"}, {"text": "Русский", "callback_data": "lang:ru"}]]
    }


def test_answer_callback_query():
    rec = Recorder((200, {"ok": True, "result": True}))
    make_client(rec).answer_callback_query("cb1")
    assert rec.calls == [("answerCallbackQuery", {"callback_query_id": "cb1"})]


def test_set_my_commands_for_a_language():
    rec = Recorder((200, {"ok": True, "result": True}))
    make_client(rec).set_my_commands([("help", "Справка")], language_code="ru")
    assert rec.calls == [
        ("setMyCommands", {"commands": [{"command": "help", "description": "Справка"}], "language_code": "ru"})
    ]
