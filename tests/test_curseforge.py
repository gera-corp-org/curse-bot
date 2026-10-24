import httpx
import pytest

import json

from bot.curseforge import API_URL, BATCH_SIZE, CurseForgeClient, CurseForgeError


def client_with(handler):
    http = httpx.Client(base_url=API_URL, transport=httpx.MockTransport(handler))
    return CurseForgeClient("secret", http=http)


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
        client.version_types()


def test_server_error():
    client = client_with(lambda request: httpx.Response(503, text="Service Unavailable"))
    with pytest.raises(CurseForgeError, match="503"):
        client.version_types()


def test_network_error():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(CurseForgeError, match="недоступен"):
        client_with(handler).version_types()


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="<html>"),
    httpx.Response(200, json={"oops": 1}),
])
def test_malformed_response(response):
    with pytest.raises(CurseForgeError, match="некорректный"):
        client_with(lambda request: response).version_types()


@pytest.mark.parametrize("body", [{"data": None}, {"data": {}}])
def test_non_list_data_is_error(body):
    with pytest.raises(CurseForgeError, match="некорректный"):
        client_with(lambda request: httpx.Response(200, json=body)).version_types()


def get_mods_handler(existing, requests=None):
    """Фейковый API: отдаёт только существующие id, а если их нет совсем — 404."""
    def handler(request):
        if requests is not None:
            requests.append(request)
        ids = json.loads(request.content)["modIds"]
        found = [{"id": i} for i in ids if i in existing]
        if not found:
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json={"data": found})
    return handler


def test_get_mods_request():
    requests = []
    mods = client_with(get_mods_handler({1, 3}, requests)).get_mods([1, 2, 3])
    assert mods == [{"id": 1}, {"id": 3}]
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/v1/mods"
    assert json.loads(request.content) == {"modIds": [1, 2, 3]}
    assert request.headers["x-api-key"] == "secret"


def test_get_mods_chunks_by_batch_size():
    requests = []
    ids = list(range(1, 2501))
    mods = client_with(get_mods_handler(set(ids), requests)).get_mods(ids)
    assert [len(json.loads(r.content)["modIds"]) for r in requests] == [BATCH_SIZE, BATCH_SIZE, 500]
    assert [m["id"] for m in mods] == ids


def test_get_mods_404_is_empty():
    assert client_with(get_mods_handler(set())).get_mods([5, 6]) == []


def test_get_mods_empty_input_makes_no_request():
    requests = []
    assert client_with(get_mods_handler({1}, requests)).get_mods([]) == []
    assert requests == []


def test_get_mods_403_explains_key():
    with pytest.raises(CurseForgeError, match="API-ключ"):
        client_with(lambda request: httpx.Response(403)).get_mods([1])


def test_get_mods_server_error():
    with pytest.raises(CurseForgeError, match="503"):
        client_with(lambda request: httpx.Response(503, text="x")).get_mods([1])


def test_get_mods_network_error():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(CurseForgeError, match="недоступен"):
        client_with(handler).get_mods([1])


def test_get_mods_malformed_response():
    with pytest.raises(CurseForgeError, match="некорректный"):
        client_with(lambda request: httpx.Response(200, json={"data": {}})).get_mods([1])


@pytest.mark.parametrize("top", [1_000_500, 1_763_684, 1_999_999, 2_000_000, 2_300_123])
def test_find_max_id_with_gaps(top):
    existing = {i for i in range(1, top + 1) if i % 6 != 0}  # ~17% дыр
    existing.add(top)
    assert client_with(get_mods_handler(existing)).find_max_id() == top


def test_find_max_id_fails_when_start_window_empty():
    with pytest.raises(CurseForgeError):
        client_with(get_mods_handler({5})).find_max_id()
