import httpx
import pytest

from bot.curseforge import API_URL, CurseForgeClient, CurseForgeError


def client_with(handler):
    http = httpx.Client(base_url=API_URL, transport=httpx.MockTransport(handler))
    return CurseForgeClient("secret", http=http)


def test_latest_released_request():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": 1}], "pagination": {}})

    assert client_with(handler).latest_released() == [{"id": 1}]
    request = requests[0]
    assert request.url.path == "/v1/mods/search"
    assert dict(request.url.params) == {"gameId": "1", "sortField": "11", "sortOrder": "desc", "pageSize": "50"}
    assert request.headers["x-api-key"] == "secret"


def test_version_types_request():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": 517, "name": "WoW Retail"}]})

    assert client_with(handler).version_types() == [{"id": 517, "name": "WoW Retail"}]
    assert requests[0].url.path == "/v1/games/1/version-types"


def test_403_explains_key():
    client = client_with(lambda request: httpx.Response(403))
    with pytest.raises(CurseForgeError, match="API-ключ"):
        client.latest_released()


def test_server_error():
    client = client_with(lambda request: httpx.Response(503, text="Service Unavailable"))
    with pytest.raises(CurseForgeError, match="503"):
        client.latest_released()


def test_network_error():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(CurseForgeError, match="недоступен"):
        client_with(handler).latest_released()
