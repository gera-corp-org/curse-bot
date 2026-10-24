from datetime import UTC, datetime

import httpx
import pytest

from bot.curseforge import API_URL, CurseForgeClient, CurseForgeError, parse_date


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
    assert dict(request.url.params) == {"gameId": "1", "sortField": "11", "sortOrder": "desc", "pageSize": "50", "index": "0"}
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


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="<html>"),
    httpx.Response(200, json={"oops": 1}),
])
def test_malformed_response(response):
    with pytest.raises(CurseForgeError, match="некорректный"):
        client_with(lambda request: response).latest_released()


def test_latest_released_passes_index():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": []})

    client_with(handler).latest_released(100)
    assert requests[0].url.params["index"] == "100"


@pytest.mark.parametrize("body", [{"data": None}, {"data": {}}])
def test_non_list_data_is_error(body):
    with pytest.raises(CurseForgeError, match="некорректный"):
        client_with(lambda request: httpx.Response(200, json=body)).latest_released()


@pytest.mark.parametrize("value, expected", [
    ("2026-10-24T12:34:56.123Z", datetime(2026, 10, 24, 12, 34, 56, 123000, tzinfo=UTC)),
    ("2026-10-24T12:34:56Z", datetime(2026, 10, 24, 12, 34, 56, tzinfo=UTC)),
    ("2019-06-11T09:31:28.1234567Z", datetime(2019, 6, 11, 9, 31, 28, 123456, tzinfo=UTC)),
    ("2026-10-24T12:34:56", datetime(2026, 10, 24, 12, 34, 56, tzinfo=UTC)),
])
def test_parse_date(value, expected):
    assert parse_date(value) == expected


@pytest.mark.parametrize("value", [None, "", "вчера", 123, {}])
def test_parse_date_bad_values(value):
    assert parse_date(value) is None
