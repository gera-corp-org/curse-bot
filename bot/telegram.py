"""Sending notifications via the Telegram Bot API."""
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

    def send_addon(self, caption: str, images: list[str], chat_id: int | str | None = None) -> None:
        """Album -> logo photo -> text; the next option is tried only if the previous one failed.

        By default to the channel from settings; chat_id sends to another chat (reply to /latest).
        """
        chat = self._chat_id if chat_id is None else chat_id
        attempts: list[tuple[str, dict]] = []
        if len(images) >= 2:
            media = [{"type": "photo", "media": url} for url in images]
            media[0].update(caption=caption, parse_mode="HTML")
            attempts.append(("sendMediaGroup", {"chat_id": chat, "media": media}))
        if images:
            attempts.append(("sendPhoto", {"chat_id": chat, "photo": images[0], "caption": caption, "parse_mode": "HTML"}))
        attempts.append(("sendMessage", {"chat_id": chat, "text": caption, "parse_mode": "HTML"}))

        error = None
        for method, payload in attempts:
            try:
                self._call(method, payload)
                return
            except TelegramError as e:
                log.warning("%s", e)
                error = e
        raise error

    def send_text(self, chat_id: int | str, text: str, buttons: list[tuple[str, str]] | None = None) -> None:
        """A text message; buttons are (label, callback data) pairs shown in one row under it."""
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "link_preview_options": {"is_disabled": True}}
        if buttons:
            payload["reply_markup"] = {
                "inline_keyboard": [[{"text": label, "callback_data": data} for label, data in buttons]]
            }
        self._call("sendMessage", payload)

    def answer_callback_query(self, callback_query_id: str) -> None:
        """Confirm a button press, so the client stops showing a spinner on it."""
        self._call("answerCallbackQuery", {"callback_query_id": callback_query_id})

    def get_updates(self, offset: int | None, timeout: int) -> list[dict]:
        """Long polling for incoming messages: Telegram holds the request for up to timeout seconds."""
        payload: dict = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload = {"offset": offset, **payload}
        return self._call("getUpdates", payload, read_timeout=timeout + 15)

    def set_my_commands(self, commands: list[tuple[str, str]], language_code: str | None = None) -> None:
        """Command menu in the Telegram client; language_code — for clients in that language."""
        payload: dict = {"commands": [{"command": c, "description": d} for c, d in commands]}
        if language_code:
            payload["language_code"] = language_code
        self._call("setMyCommands", payload)

    def _call(self, method: str, payload: dict, read_timeout: float | None = None) -> dict:
        for attempt in range(MAX_429_RETRIES + 1):
            try:
                kwargs = {} if read_timeout is None else {"timeout": httpx.Timeout(read_timeout, connect=10)}
                response = self._http.post(f"/bot{self._token}/{method}", json=payload, **kwargs)
            except httpx.HTTPError as e:
                # httpx network error text has no URL, so the token does not leak here
                raise TelegramError(f"{method}: Telegram is unreachable: {e}") from e
            try:
                body = response.json()
            except ValueError:
                body = {}
            if not isinstance(body, dict):
                body = {}
            if body.get("ok"):
                return body["result"]
            retry_after = (body.get("parameters") or {}).get("retry_after")
            if response.status_code == 429 and retry_after and attempt < MAX_429_RETRIES:
                log.warning("Telegram asks to wait %s s", retry_after)
                self._sleep(retry_after)
                continue
            raise TelegramError(f"{method}: {response.status_code} {body.get('description') or response.text[:200]}")
        raise AssertionError("unreachable")
