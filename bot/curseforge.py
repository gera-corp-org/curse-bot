"""Клиент CurseForge API — только запросы, нужные боту."""
from datetime import UTC, datetime

import httpx

API_URL = "https://api.curseforge.com"
WOW_GAME_ID = 1
SORT_RELEASED_DATE = 11  # ModsSearchSortField.ReleasedDate
PAGE_SIZE = 50  # максимум, который отдаёт API


class CurseForgeError(Exception):
    pass


class CurseForgeClient:
    def __init__(self, api_key: str, http: httpx.Client | None = None):
        self._headers = {"x-api-key": api_key, "Accept": "application/json"}
        self._http = http or httpx.Client(base_url=API_URL, timeout=30)

    def latest_released(self, index: int = 0) -> list[dict]:
        """Аддоны WoW с недавним релизом (dateReleased — дата последнего файла), от новых к старым; index — смещение страницы."""
        return self._get(
            "/v1/mods/search",
            {"gameId": WOW_GAME_ID, "sortField": SORT_RELEASED_DATE, "sortOrder": "desc", "pageSize": PAGE_SIZE, "index": index},
        )

    def version_types(self) -> list[dict]:
        return self._get(f"/v1/games/{WOW_GAME_ID}/version-types")

    def _get(self, path: str, params: dict | None = None):
        try:
            response = self._http.get(path, params=params, headers=self._headers)
        except httpx.HTTPError as e:
            raise CurseForgeError(f"CurseForge недоступен: {e}") from e
        if response.status_code == 403:
            raise CurseForgeError("CurseForge ответил 403: неверный или отозванный API-ключ")
        if response.status_code != 200:
            raise CurseForgeError(f"CurseForge ответил {response.status_code}: {response.text[:200]}")
        try:
            data = response.json()["data"]
        except (ValueError, KeyError, TypeError) as e:
            raise CurseForgeError("CurseForge вернул некорректный ответ") from e
        if not isinstance(data, list):
            raise CurseForgeError("CurseForge вернул некорректный ответ")
        return data


def parse_date(value) -> datetime | None:
    """ISO-дата CurseForge ("...Z", в т.ч. 7 знаков доли секунды) → aware UTC; None, если не разобрать."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
