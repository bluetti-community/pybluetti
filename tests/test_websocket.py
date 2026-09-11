"""Tests for websocket.py (StompClient), the async aiohttp websocket transport."""

import json
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import aiohttp
import pytest

from pybluetti.exceptions import ApplicationRuntimeException
from pybluetti.websocket import StompClient

GATEWAY_WS_URL = "wss://gw.bluettipower.com/api/edgeiotgw/ws-coordination"


class _FakeWSMessage:
    def __init__(self, msg_type, data=None):
        self.type = msg_type
        self.data = data


class _FakeWebSocket:
    """A minimal async-iterable double for aiohttp.ClientWebSocketResponse."""

    def __init__(self, messages=None):
        self._messages = list(messages or [])
        self.sent = []
        self.closed = False
        self.close_called = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def send_str(self, data):
        self.sent.append(data)

    async def close(self):
        self.closed = True
        self.close_called = True
        return True

    def exception(self):
        return RuntimeError("boom")


class _FakeSession:
    def __init__(self, ws):
        self._ws = ws
        self.calls = []

    async def ws_connect(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._ws


def _client(ws=None, handler=None):
    on_auth_expired = MagicMock()
    session = _FakeSession(ws)
    client = StompClient(
        session, GATEWAY_WS_URL, "token", handler=handler, on_auth_expired=on_auth_expired
    )
    # Most tests exercise internal methods (_run, _handle_frame, ...)
    # directly rather than through connect(), so simulate an already-open
    # connection the same way the ported test suite always has.
    client._ws = ws
    return client, session, on_auth_expired


# --- StompClient.__get_host -------------------------------------------------

@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("wss://gw.bluettipower.com/api/foo", "gw.bluettipower.com"),
        ("wss://gw.bluettipower.com:443/api/foo", "gw.bluettipower.com"),
        ("ws://local-gw:18888/api/foo", "local-gw"),
    ],
)
def test_get_host_strips_port_and_path(url, expected):
    assert StompClient._StompClient__get_host(url) == expected


# --- StompClient.__init__'s app_key/app_ver validation -----------------------

def test_init_raises_if_only_app_key_given():
    session = _FakeSession(None)
    with pytest.raises(ValueError, match="app_key and app_ver must be given together"):
        StompClient(session, GATEWAY_WS_URL, "token", app_key="key")


def test_init_raises_if_only_app_ver_given():
    session = _FakeSession(None)
    with pytest.raises(ValueError, match="app_key and app_ver must be given together"):
        StompClient(session, GATEWAY_WS_URL, "token", app_ver="1.3.0")


# --- StompClient.connect ------------------------------------------------------

async def test_connect_opens_socket_sends_connect_frame_and_starts_tasks():
    ws = _FakeWebSocket()
    client, session, _on_auth_expired = _client(ws)

    await client.connect()

    assert client.running is True
    assert session.calls[0][0] == GATEWAY_WS_URL + "/websocket"
    assert ws.sent[0].startswith("CONNECT\n")
    assert "Authorization: token" in ws.sent[0]
    assert client._receive_task is not None
    assert client._heartbeat_task is not None


async def test_connect_omits_client_identification_headers_by_default():
    ws = _FakeWebSocket()
    client, _session, _on_auth_expired = _client(ws)

    await client.connect()

    assert "x-app-key" not in ws.sent[0]
    assert "x-app-ver" not in ws.sent[0]
    assert "x-os" not in ws.sent[0]


async def test_connect_sends_client_identification_headers_when_given():
    ws = _FakeWebSocket()
    session = _FakeSession(ws)
    client = StompClient(
        session, GATEWAY_WS_URL, "token", app_key="the-key", app_ver="1.3.0"
    )
    client._ws = ws

    await client.connect()

    assert "x-os:open" in ws.sent[0]
    assert "x-app-key:the-key" in ws.sent[0]
    assert "x-app-ver:1.3.0" in ws.sent[0]


async def test_connect_cancels_a_stale_heartbeat_task_from_a_previous_connection():
    ws = _FakeWebSocket()
    client, _session, _on_auth_expired = _client(ws)
    stale_task = MagicMock()
    client._heartbeat_task = stale_task

    await client.connect()

    stale_task.cancel.assert_called_once()
    assert client._heartbeat_task is not stale_task

    await client.disconnect()  # tidy up the background tasks started above

    await client.disconnect()  # tidy up the background tasks started above


async def test_update_access_token_affects_the_next_connect():
    ws = _FakeWebSocket()
    client, _session, _on_auth_expired = _client(ws)

    client.update_access_token("refreshed-token")
    await client.connect()

    assert "Authorization: refreshed-token" in ws.sent[0]

    await client.disconnect()  # tidy up the background tasks started above


async def test_connect_failure_triggers_reconnect():
    class _FailingSession:
        async def ws_connect(self, url, **kwargs):
            msg = "boom"
            raise aiohttp.ClientConnectionError(msg)

    client = StompClient(_FailingSession(), GATEWAY_WS_URL, "token")
    client.reconnect = AsyncMock()

    await client.connect()

    client.reconnect.assert_awaited_once()


# --- StompClient.disconnect ---------------------------------------------------

async def test_disconnect_cancels_tasks_and_closes_socket():
    ws = _FakeWebSocket()
    client, _session, _on_auth_expired = _client(ws)
    await client.connect()

    await client.disconnect()

    assert client.running is False
    assert ws.close_called is True


async def test_disconnect_without_connecting_first_does_not_raise():
    client, _session, _on_auth_expired = _client()

    await client.disconnect()  # must not raise


# --- StompClient.reconnect ----------------------------------------------------

async def test_reconnect_when_running_backs_off_and_reconnects():
    client, _session, _on_auth_expired = _client()
    client.running = True
    client.reconnect_delay = 1
    client.max_reconnect_delay = 30
    client.connect = AsyncMock()

    with patch("pybluetti.websocket.asyncio.sleep", AsyncMock()) as mock_sleep:
        await client.reconnect()

    mock_sleep.assert_awaited_once_with(1)
    assert client.reconnect_delay == 2
    client.connect.assert_awaited_once()


async def test_reconnect_when_stopped_does_nothing():
    client, _session, _on_auth_expired = _client()
    client.running = False
    client.connect = AsyncMock()

    with patch("pybluetti.websocket.asyncio.sleep", AsyncMock()) as mock_sleep:
        await client.reconnect()

    mock_sleep.assert_not_awaited()
    client.connect.assert_not_awaited()


# --- StompClient._heartbeat_loop ----------------------------------------------

async def test_heartbeat_loop_sends_and_stops_when_running_false():
    ws = _FakeWebSocket()
    client, _session, _on_auth_expired = _client(ws)
    client.running = True

    async def _stop_after_sleep(_delay):
        client.running = False

    with patch("pybluetti.websocket.asyncio.sleep", _stop_after_sleep):
        await client._heartbeat_loop()

    assert ws.sent == ["\n"]


async def test_heartbeat_loop_breaks_when_ws_closed():
    ws = _FakeWebSocket()
    ws.closed = True
    client, _session, _on_auth_expired = _client(ws)
    client.running = True

    with patch("pybluetti.websocket.asyncio.sleep", AsyncMock()):
        await client._heartbeat_loop()

    assert ws.sent == []


async def test_heartbeat_loop_breaks_on_send_error():
    ws = _FakeWebSocket()

    async def _failing_send(_data):
        msg = "boom"
        raise RuntimeError(msg)

    ws.send_str = _failing_send
    client, _session, _on_auth_expired = _client(ws)
    client.running = True

    with patch("pybluetti.websocket.asyncio.sleep", AsyncMock()):
        await client._heartbeat_loop()  # must not raise


async def test_heartbeat_loop_without_websocket_does_nothing():
    client, _session, _on_auth_expired = _client()
    client.running = True
    client._ws = None

    with patch("pybluetti.websocket.asyncio.sleep", AsyncMock()):
        await client._heartbeat_loop()  # must not raise


# --- StompClient._run ----------------------------------------------------------

async def test_run_without_websocket_logs_and_returns():
    client, _session, _on_auth_expired = _client()
    client.reconnect = AsyncMock()

    await client._run()  # must not raise

    client.reconnect.assert_not_awaited()


async def test_run_dispatches_text_messages_to_handle_frame():
    raw = "MESSAGE\ndestination:/topic\n\nhello body\x00"
    ws = _FakeWebSocket([_FakeWSMessage(aiohttp.WSMsgType.TEXT, raw)])
    handler = MagicMock()
    client, _session, _on_auth_expired = _client(ws, handler)
    client.running = True

    await client._run()

    handler.assert_called_once_with("hello body")


async def test_run_breaks_on_error_message_type_and_reconnects_if_running():
    ws = _FakeWebSocket([_FakeWSMessage(aiohttp.WSMsgType.ERROR)])
    client, _session, _on_auth_expired = _client(ws)
    client.running = True
    client.reconnect = AsyncMock()

    await client._run()

    assert ws.close_called is True
    client.reconnect.assert_awaited_once()


async def test_run_breaks_on_close_message_type_and_skips_reconnect_when_stopped():
    ws = _FakeWebSocket([_FakeWSMessage(aiohttp.WSMsgType.CLOSE)])
    client, _session, _on_auth_expired = _client(ws)
    client.running = False
    client.reconnect = AsyncMock()

    await client._run()

    client.reconnect.assert_not_awaited()


async def test_run_catches_unexpected_exception_and_reconnects():
    class _BrokenWebSocket:
        def __init__(self):
            self.closed = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            msg = "boom"
            raise RuntimeError(msg)

        async def close(self):
            self.closed = True

    ws = _BrokenWebSocket()
    client, _session, _on_auth_expired = _client(ws)
    client.running = True
    client.reconnect = AsyncMock()

    await client._run()

    assert ws.closed is True

    client.reconnect.assert_awaited_once()


def _error_message(msg_code: int, message: str) -> _FakeWSMessage:
    payload = json.dumps({"msgCode": msg_code, "message": message}).replace(":", "\\c")
    raw = f"ERROR\nmessage:{payload}\n\n\x00"
    return _FakeWSMessage(aiohttp.WSMsgType.TEXT, raw)


async def test_run_catches_application_runtime_exception_logs_full_and_calls_on_error():
    ws = _FakeWebSocket([_error_message(500, "server error")])
    on_auth_expired = MagicMock()
    on_error = MagicMock()
    session = _FakeSession(ws)
    client = StompClient(
        session, GATEWAY_WS_URL, "token", on_auth_expired=on_auth_expired, on_error=on_error
    )
    client._ws = ws
    client.running = True
    client.reconnect = AsyncMock()

    with patch("pybluetti.websocket.__LOGGER__") as logger:
        await client._run()

    logger.exception.assert_called_once_with("BLUETTI WebSocket task crashed")
    debug_messages = [call.args[0] for call in logger.debug.call_args_list]
    assert "BLUETTI WebSocket task crashed (repeat): %s" not in debug_messages
    on_error.assert_called_once()
    assert on_error.call_args[0][0].msgCode == 500
    assert client._last_error_message == "[500] server error"
    # The real bug this guards against: _run() used to leave the abandoned
    # connection open on this exact path (only msgCode 805 closed it), so a
    # concurrently-running heartbeat task could still be mid-send against it
    # by the time it actually finished closing - "Cannot write to closing
    # transport", repeating on every retry cycle in production.
    assert ws.close_called is True
    client.reconnect.assert_awaited_once()


async def test_run_does_not_reconnect_after_a_terminal_error_code():
    ws = _FakeWebSocket([_error_message(600, "Upgrade required")])
    on_error = MagicMock()
    session = _FakeSession(ws)
    client = StompClient(session, GATEWAY_WS_URL, "token", on_error=on_error)
    client._ws = ws
    client.running = True
    client.reconnect = AsyncMock()

    await client._run()

    on_error.assert_called_once()
    assert on_error.call_args[0][0].msgCode == 600
    assert ws.close_called is True
    client.reconnect.assert_not_awaited()
    assert client.running is False


async def test_run_downgrades_repeated_identical_application_runtime_exception():
    ws = _FakeWebSocket([_error_message(500, "server error")])
    session = _FakeSession(ws)
    client = StompClient(session, GATEWAY_WS_URL, "token")
    client._ws = ws
    client.running = True
    client._last_error_message = "[500] server error"  # already logged once, on a previous retry
    client.reconnect = AsyncMock()

    with patch("pybluetti.websocket.__LOGGER__") as logger:
        await client._run()

    logger.exception.assert_not_called()
    logger.debug.assert_any_call("BLUETTI WebSocket task crashed (repeat): %s", ANY)
    client.reconnect.assert_awaited_once()


async def test_run_relogs_in_full_once_the_error_message_changes():
    ws = _FakeWebSocket([_error_message(500, "a different error")])
    session = _FakeSession(ws)
    client = StompClient(session, GATEWAY_WS_URL, "token")
    client._ws = ws
    client.running = True
    client._last_error_message = "[500] server error"
    client.reconnect = AsyncMock()

    with patch("pybluetti.websocket.__LOGGER__") as logger:
        await client._run()

    logger.exception.assert_called_once_with("BLUETTI WebSocket task crashed")
    assert client._last_error_message == "[500] a different error"


async def test_run_application_runtime_exception_without_on_error_does_not_raise():
    ws = _FakeWebSocket([_error_message(500, "server error")])
    session = _FakeSession(ws)
    client = StompClient(session, GATEWAY_WS_URL, "token")
    client._ws = ws
    client.running = True
    client.reconnect = AsyncMock()

    await client._run()  # must not raise even with on_error unset

    client.reconnect.assert_awaited_once()


# --- StompClient._handle_frame --------------------------------------------------

async def test_handle_frame_ignores_empty_and_heartbeat():
    client, _session, _on_auth_expired = _client()
    await client._handle_frame("")
    await client._handle_frame("\n")


async def test_handle_frame_error_805_stops_closes_and_invokes_callback():
    ws = _FakeWebSocket()
    client, _session, on_auth_expired = _client(ws)
    client.running = True
    client._heartbeat_task = MagicMock()
    payload = json.dumps({"msgCode": 805, "message": "expired"}).replace(":", "\\c")
    raw = f"ERROR\nmessage:{payload}\n\n\x00"

    await client._handle_frame(raw)

    assert client.running is False
    client._heartbeat_task.cancel.assert_called_once()
    assert ws.close_called is True
    on_auth_expired.assert_called_once_with()


async def test_handle_frame_error_805_without_callback_does_not_raise():
    ws = _FakeWebSocket()
    client, _session, _on_auth_expired = _client(ws)
    client.on_auth_expired = None
    payload = json.dumps({"msgCode": 805, "message": "expired"}).replace(":", "\\c")
    raw = f"ERROR\nmessage:{payload}\n\n\x00"

    await client._handle_frame(raw)  # must not raise


async def test_handle_frame_error_other_code_raises():
    client, _session, _on_auth_expired = _client()
    payload = json.dumps({"msgCode": 500, "message": "server error"}).replace(":", "\\c")
    raw = f"ERROR\nmessage:{payload}\n\n\x00"

    with pytest.raises(ApplicationRuntimeException) as exc_info:
        await client._handle_frame(raw)

    assert exc_info.value.msgCode == 500


async def test_handle_frame_error_other_code_does_not_stop_retrying():
    # A non-terminal, non-805 code (500) must not be mistaken for one of
    # the codes known to never succeed on retry - client.running is left
    # exactly as it was (True: a real, live connection still exists).
    client, _session, _on_auth_expired = _client()
    client.running = True
    payload = json.dumps({"msgCode": 500, "message": "server error"}).replace(":", "\\c")
    raw = f"ERROR\nmessage:{payload}\n\n\x00"

    with pytest.raises(ApplicationRuntimeException):
        await client._handle_frame(raw)

    assert client.running is True


@pytest.mark.parametrize("msg_code", [400, 403, 600])
async def test_handle_frame_error_terminal_code_stops_retrying_but_still_raises(msg_code):
    # 400/403/600: confirmed (600) or strongly implied (400, 403 - see
    # _TERMINAL_ERROR_CODES's own comment) to never succeed on retry.
    # Unlike 805, these still raise (on_error fires with the real message)
    # rather than calling on_auth_expired - none of the three necessarily
    # mean the token itself is the problem.
    client, _session, on_auth_expired = _client()
    client.running = True
    payload = json.dumps({"msgCode": msg_code, "message": "terminal"}).replace(":", "\\c")
    raw = f"ERROR\nmessage:{payload}\n\n\x00"

    with pytest.raises(ApplicationRuntimeException) as exc_info:
        await client._handle_frame(raw)

    assert exc_info.value.msgCode == msg_code
    assert client.running is False
    on_auth_expired.assert_not_called()


async def test_handle_frame_connected_without_websocket_logs_and_returns():
    client, _session, _on_auth_expired = _client()
    raw = "CONNECTED\nheart-beat:10000,10000\nuser-name:bob\n\n\x00"

    await client._handle_frame(raw)  # must not raise


async def test_handle_frame_connected_with_user_name_subscribes():
    ws = _FakeWebSocket()
    client, _session, _on_auth_expired = _client(ws)
    raw = "CONNECTED\nheart-beat:10000,10000\nuser-name:bob\n\n\x00"

    await client._handle_frame(raw)

    assert "/ws-subscribe/user/bob/notify" in ws.sent[0]


async def test_handle_frame_connected_resets_last_error_message():
    ws = _FakeWebSocket()
    client, _session, _on_auth_expired = _client(ws)
    client._last_error_message = "server error"
    raw = "CONNECTED\nheart-beat:10000,10000\nuser-name:bob\n\n\x00"

    await client._handle_frame(raw)

    assert client._last_error_message is None


async def test_handle_frame_connected_without_user_name_logs_and_returns():
    ws = _FakeWebSocket()
    client, _session, _on_auth_expired = _client(ws)
    raw = "CONNECTED\nheart-beat:10000,10000\n\n\x00"

    await client._handle_frame(raw)

    assert ws.sent == []


async def test_handle_frame_message_invokes_handler():
    handler = MagicMock()
    client, _session, _on_auth_expired = _client(handler=handler)
    raw = "MESSAGE\ndestination:/topic\n\nhello body\x00"

    await client._handle_frame(raw)

    handler.assert_called_once_with("hello body")


# --- StompClient._invoke_handler ------------------------------------------------

def test_invoke_handler_swallows_errors():
    handler = MagicMock(side_effect=RuntimeError("boom"))
    client, _session, _on_auth_expired = _client(handler=handler)

    client._invoke_handler("payload")  # must not raise


def test_invoke_handler_does_nothing_without_handler():
    client, _session, _on_auth_expired = _client()

    client._invoke_handler("payload")  # must not raise
