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


def test_non_dict_json_body_is_telegram_error():
    def handler(request):
        return httpx.Response(500, json=[1, 2])

    with pytest.raises(TelegramError, match="500"):
        make_client(handler).send_addon("cap", [])
