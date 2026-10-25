"""CurseForge API client - only the requests the bot needs."""
import httpx

API_URL = "https://api.curseforge.com"
WOW_GAME_ID = 1
BATCH_SIZE = 1000  # max ids in one POST /v1/mods
SCAN_START_ID = 1_000_000  # an id known to exist; the search for the current maximum starts from it


class CurseForgeError(Exception):
    pass


class CurseForgeClient:
    def __init__(self, api_key: str, http: httpx.Client | None = None):
        self._headers = {"x-api-key": api_key, "Accept": "application/json"}
        self._http = http or httpx.Client(base_url=API_URL, timeout=30)

    def version_types(self) -> list[dict]:
        return self._request("GET", f"/v1/games/{WOW_GAME_ID}/version-types")

    def get_mods(self, mod_ids: list[int]) -> list[dict]:
        """Addons by id (any game); nonexistent ids are simply absent from the response."""
        mods: list[dict] = []
        for start in range(0, len(mod_ids), BATCH_SIZE):
            chunk = mod_ids[start : start + BATCH_SIZE]
            mods += self._request("POST", "/v1/mods", json={"modIds": chunk}, empty_on_404=True)
        return mods

    def find_max_id(self) -> int:
        """Current highest addon id: exponential search in BATCH_SIZE windows, then binary search."""
        lo = SCAN_START_ID
        if not self._window(lo):
            raise CurseForgeError(f"CurseForge returned no addons in the window starting at id {lo}")
        hi = lo * 2
        while self._window(hi):
            lo, hi = hi, hi * 2
        while hi - lo > BATCH_SIZE:
            mid = (lo + hi) // 2
            if self._window(mid):
                lo = mid
            else:
                hi = mid
        found = self.get_mods(list(range(lo, lo + 2 * BATCH_SIZE)))
        return max(m["id"] for m in found)

    def _window(self, start: int) -> list[dict]:
        return self.get_mods(list(range(start, start + BATCH_SIZE)))

    def _request(self, method: str, path: str, *, params: dict | None = None, json: dict | None = None,
                 empty_on_404: bool = False) -> list[dict]:
        try:
            response = self._http.request(method, path, params=params, json=json, headers=self._headers)
        except httpx.HTTPError as e:
            raise CurseForgeError(f"CurseForge is unreachable: {e}") from e
        if response.status_code == 404 and empty_on_404:
            return []  # none of the requested ids exist
        if response.status_code == 403:
            raise CurseForgeError("CurseForge responded 403: invalid or revoked API key")
        if response.status_code != 200:
            raise CurseForgeError(f"CurseForge responded {response.status_code}: {response.text[:200]}")
        try:
            data = response.json()["data"]
        except (ValueError, KeyError, TypeError) as e:
            raise CurseForgeError("CurseForge returned an invalid response") from e
        if not isinstance(data, list):
            raise CurseForgeError("CurseForge returned an invalid response")
        return data
