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

    def send_addon(self, caption: str, images: list[str]) -> None:
        """Альбом → фото логотипа → текст; следующий вариант — только если предыдущий не прошёл."""
        attempts: list[tuple[str, dict]] = []
        if len(images) >= 2:
            media = [{"type": "photo", "media": url} for url in images]
            media[0].update(caption=caption, parse_mode="HTML")
            attempts.append(("sendMediaGroup", {"chat_id": self._chat_id, "media": media}))
        if images:
            attempts.append(
                ("sendPhoto", {"chat_id": self._chat_id, "photo": images[0], "caption": caption, "parse_mode": "HTML"})
            )
        attempts.append(("sendMessage", {"chat_id": self._chat_id, "text": caption, "parse_mode": "HTML"}))

        error = None
        for method, payload in attempts:
            try:
                self._call(method, payload)
                return
            except TelegramError as e:
                log.warning("%s", e)
                error = e
        raise error

    def _call(self, method: str, payload: dict) -> dict:
        for attempt in range(MAX_429_RETRIES + 1):
            try:
                response = self._http.post(f"/bot{self._token}/{method}", json=payload)
            except httpx.HTTPError as e:
                # в тексте сетевых ошибок httpx нет URL, так что токен сюда не попадает
                raise TelegramError(f"{method}: Telegram недоступен: {e}") from e
            try:
                body = response.json()
            except ValueError:
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
