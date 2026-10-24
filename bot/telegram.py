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

    def send_addon(self, caption: str, images: list[str], chat_id: int | str | None = None) -> None:
        """Альбом → фото логотипа → текст; следующий вариант — только если предыдущий не прошёл.

        По умолчанию — в канал из настроек; chat_id — в другой чат (ответ на /latest).
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

    def send_text(self, chat_id: int | str, text: str) -> None:
        self._call(
            "sendMessage",
            {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "link_preview_options": {"is_disabled": True}},
        )

    def get_updates(self, offset: int | None, timeout: int) -> list[dict]:
        """Long polling входящих сообщений: Telegram держит запрос до timeout секунд."""
        payload: dict = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            payload = {"offset": offset, **payload}
        return self._call("getUpdates", payload, read_timeout=timeout + 15)

    def set_my_commands(self, commands: list[tuple[str, str]]) -> None:
        """Меню команд в клиенте Telegram."""
        self._call("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in commands]})

    def _call(self, method: str, payload: dict, read_timeout: float | None = None) -> dict:
        for attempt in range(MAX_429_RETRIES + 1):
            try:
                kwargs = {} if read_timeout is None else {"timeout": httpx.Timeout(read_timeout, connect=10)}
                response = self._http.post(f"/bot{self._token}/{method}", json=payload, **kwargs)
            except httpx.HTTPError as e:
                # в тексте сетевых ошибок httpx нет URL, так что токен сюда не попадает
                raise TelegramError(f"{method}: Telegram недоступен: {e}") from e
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
                log.warning("Telegram просит подождать %s с", retry_after)
                self._sleep(retry_after)
                continue
            raise TelegramError(f"{method}: {response.status_code} {body.get('description') or response.text[:200]}")
        raise AssertionError("unreachable")
