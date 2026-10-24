"""Клиент CurseForge API — только запросы, нужные боту."""
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

    def latest_released(self) -> list[dict]:
        """Последние вышедшие аддоны WoW, от новых к старым."""
        return self._get(
            "/v1/mods/search",
            {"gameId": WOW_GAME_ID, "sortField": SORT_RELEASED_DATE, "sortOrder": "desc", "pageSize": PAGE_SIZE},
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
        return response.json()["data"]
