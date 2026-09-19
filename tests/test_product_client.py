"""Tests for the Bluetti base API client (client.py) via ProductClient."""

from unittest.mock import MagicMock

import pytest

from pybluetti.exceptions import ApplicationRuntimeException, HttpStatusException
from pybluetti.product_client import ProductClient

GATEWAY_URL = "https://gw.bluettipower.com"


class _FakeResponse:
    def __init__(self, status=200, content_type="application/json", json_data=None, text_data=""):
        self.status = status
        self.reason = {200: "OK", 401: "Unauthorized", 504: "Gateway Timeout"}.get(status)
        self.ok = 200 <= status < 400
        self.content_type = content_type
        self.url = "https://gw.bluettipower.com/fake"
        self._json_data = json_data
        self._text_data = text_data

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text_data


class _FakeRequestContextManager:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return _FakeRequestContextManager(self._response)


def _client(session) -> tuple[ProductClient, MagicMock]:
    on_auth_expired = MagicMock()
    return ProductClient(session, GATEWAY_URL, "test-token", on_auth_expired), on_auth_expired


async def test_get_user_products_success():
    response = _FakeResponse(json_data={"msgId": "1", "msgCode": 0, "data": []})
    session = _FakeSession(response)
    client, _on_auth_expired = _client(session)

    result = await client.get_user_products()

    assert result.is_ok()
    assert result.data == []
    # GET requests must not send a body.
    _method, _url, kwargs = session.calls[0]
    assert kwargs["json"] is None


async def test_update_access_token_affects_subsequent_requests():
    response = _FakeResponse(json_data={"msgId": "1", "msgCode": 0, "data": []})
    session = _FakeSession(response)
    client, _on_auth_expired = _client(session)

    client.update_access_token("refreshed-token")
    await client.get_user_products()

    _method, _url, kwargs = session.calls[0]
    assert kwargs["headers"]["Authorization"] == "refreshed-token"


async def test_get_device_status_strips_none_params():
    response = _FakeResponse(json_data={"msgId": "1", "msgCode": 0, "data": []})
    session = _FakeSession(response)
    client, _on_auth_expired = _client(session)

    await client.get_device_status(sns=None)

    _method, _url, kwargs = session.calls[0]
    assert kwargs["params"] == {}


async def test_control_device_strips_none_body_values():
    response = _FakeResponse(json_data={"msgId": "1", "msgCode": 0, "data": {}})
    session = _FakeSession(response)
    client, _on_auth_expired = _client(session)

    await client.control_device({"sn": "SN1", "fnCode": "AC", "fnValue": "1", "extra": None})

    _method, _url, kwargs = session.calls[0]
    assert kwargs["json"] == {"sn": "SN1", "fnCode": "AC", "fnValue": "1"}
    assert kwargs["headers"]["Content-Type"] == "application/json"


async def test_request_invokes_on_auth_expired_callback_on_805():
    response = _FakeResponse(json_data={"msgId": "1", "msgCode": 805, "data": None})
    session = _FakeSession(response)
    client, on_auth_expired = _client(session)

    await client.get_user_products()

    on_auth_expired.assert_called_once_with()


async def test_request_on_805_without_callback_does_not_raise():
    """on_auth_expired is optional - a consumer that doesn't need it must not crash."""
    response = _FakeResponse(json_data={"msgId": "1", "msgCode": 805, "data": None})
    session = _FakeSession(response)
    client = ProductClient(session, GATEWAY_URL, "test-token")

    await client.get_user_products()  # must not raise


async def test_request_raises_on_non_ok_status():
    response = _FakeResponse(status=401, text_data="unauthorized")
    session = _FakeSession(response)
    client, _on_auth_expired = _client(session)

    with pytest.raises(ApplicationRuntimeException) as exc_info:
        await client.get_user_products()

    assert exc_info.value.msgCode == 401
    assert exc_info.value.data == "unauthorized"


async def test_request_raises_http_status_exception_with_status_and_reason():
    # A gateway timeout is the HTTP layer, not the API: the exception says
    # so, and says it is transient (bluetti-community/bluetti-home-assistant#53).
    response = _FakeResponse(status=504, text_data="An unknown error has occurred.")
    session = _FakeSession(response)
    client, _on_auth_expired = _client(session)

    with pytest.raises(HttpStatusException) as exc_info:
        await client.get_user_products()

    assert exc_info.value.status == 504
    assert exc_info.value.reason == "Gateway Timeout"
    assert exc_info.value.is_transient
    assert str(exc_info.value) == "[504] HTTP 504 Gateway Timeout"


async def test_request_returns_raw_text_for_non_json_response():
    response = _FakeResponse(content_type="text/plain", text_data="plain response")
    session = _FakeSession(response)
    client, _on_auth_expired = _client(session)

    result = await client.get_user_products()

    assert result == "plain response"


async def test_bind_devices_posts_payload():
    response = _FakeResponse(json_data={"msgId": "1", "msgCode": 0, "data": {}})
    session = _FakeSession(response)
    client, _on_auth_expired = _client(session)

    await client.bind_devices({"bindSnList": ["SN1"]})

    _method, url, kwargs = session.calls[0]
    assert url.endswith("/api/bluiotdata/ha/v1/bindDevices")
    assert kwargs["json"] == {"bindSnList": ["SN1"]}
