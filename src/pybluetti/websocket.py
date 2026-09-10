"""STOMP-over-websocket client for BLUETTI's real-time device push updates."""

import asyncio
import json
import logging
import warnings
from collections.abc import Callable

import aiohttp

# stomper's stompbuffer module has an invalid regex escape sequence that
# raises a SyntaxWarning on import (fixed in no released version as of
# 0.4.3); silence it here so it isn't misattributed to this package.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", SyntaxWarning)
    import stomper

from .exceptions import ApplicationRuntimeException

__LOGGER__ = logging.getLogger(__name__)

# ERROR frame msgCodes that mean this connection can never succeed as-is -
# retrying it is pointless, not just unlikely. 600 ("Upgrade required, and
# then reconfigure the BLUETTI integration") is directly confirmed against
# a real device: retried every ~30s for over a day with the identical
# rejection every time (bluetti-community/bluetti-home-assistant#35). 400
# and 403 aren't yet directly observed here, but BLUETTI's own official
# client (bluetti-official/bluetti-home-assistant's api/websocket.py)
# groups all three with 805 (a genuinely expired token) as needing the same
# response - stop and don't retry. They're kept out of on_auth_expired's
# 805 path below deliberately: unlike 805, none of these three necessarily
# mean the access token itself is the problem (600's own real cause is
# still unconfirmed - see the issue above), so claiming that would be
# actively misleading. They still reach a caller via on_error, same as any
# other non-805 code - this only stops the pointless retry loop.
_TERMINAL_ERROR_CODES = frozenset({400, 403, 600})


class StompClient:
    """A STOMP client connected to the BLUETTI cloud's push-update websocket."""

    def __init__(  # noqa: PLR0913 -- three optional, independently-set callbacks, all keyword-only; bundling them into one object would just move the same information one level down without simplifying a caller that only wants one of them
        self,
        session: aiohttp.ClientSession,
        url: str,
        access_token: str,
        *,
        handler: Callable[[str], None] | None = None,
        on_auth_expired: Callable[[], None] | None = None,
        on_error: Callable[[ApplicationRuntimeException], None] | None = None,
    ) -> None:
        """
        Initialize the client.

        - session: the aiohttp session to open the websocket connection on.
        - url: the websocket base URL (region-specific).
        - access_token: the OAuth2 access token to authenticate the connection with.
        - handler: called with each MESSAGE frame's body.
        - on_auth_expired: called when the cloud reports the access token as
          expired (msgCode 805), so the caller can react.
        - on_error: called with any other ERROR frame the cloud sends back
          (a msgCode other than 805). The client keeps retrying with
          backoff for most of these - some are transient - except a known
          set (see _TERMINAL_ERROR_CODES) it stops retrying for, since
          those are confirmed (or, per BLUETTI's own official client,
          strongly implied) to never succeed on retry either. Either way,
          nothing else surfaces a persistent one distinctly from a
          run-of-the-mill connection drop, so a caller that wants to react
          (log once, show the user something actionable) has no other hook
          for it.
        """
        self._session = session
        self.__url = url + "/websocket"
        self.__headers = {
            "Host": self.__get_host(url),
            "Authorization": access_token,
        }
        self.__handler = handler
        self.on_auth_expired = on_auth_expired
        self.on_error = on_error
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self.running = False

        self._receive_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self.heartbeat_interval = 10
        # The most recent ApplicationRuntimeException message _run() logged
        # at full severity, cleared once a CONNECTED frame proves the
        # connection actually recovered - lets a persistently repeated error
        # log its full traceback once, not on every retry forever.
        self._last_error_message: str | None = None

        self.reconnect_delay = 1  # initial reconnect delay (seconds)
        self.max_reconnect_delay = 30  # max reconnect delay (seconds)

    def update_access_token(self, access_token: str) -> None:
        """
        Swap in a freshly refreshed access token for future (re)connects.

        The current connection, if any, keeps running on the token it
        already authenticated with - this only takes effect the next time
        connect() runs (a caller-initiated reconnect, or the automatic one
        after a disconnect), the same lazy update pybluetti.Bluetti's
        REST clients get from their own update_access_token.
        """
        self.__headers["Authorization"] = access_token

    @staticmethod
    def __get_host(connection_url: str) -> str:
        host = connection_url.split("//")[1]
        index = host.find("/")
        host = host[0:index]

        if host.find(":") > -1:
            host = host.split(":")[0]
        return host

    async def connect(self) -> None:
        """Connect to the ws server and start the background receive/heartbeat tasks."""
        __LOGGER__.info("Start to connect the BLUETTI WebSocket Server.")
        self.running = True

        # A reconnect (whether from a dropped connection or a rejected one)
        # leaves the previous heartbeat task still scheduled on the old,
        # now-stale websocket - only the msgCode-805 path cancels it before
        # getting here. Left running, it wakes up on its own next interval,
        # fails to write to the closing transport, and logs a confusing
        # "Failed to send heartbeat" line that has nothing to do with
        # whatever actually triggered this reconnect.
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()

        try:
            self._ws = await self._session.ws_connect(self.__url, headers=self.__headers)

            connect_frame = (
                "CONNECT\n"
                "accept-version:1.0,1.1,2.0\n"
                "Host:" + self.__headers["Host"] + "\n"
                "Authorization: " + self.__headers["Authorization"] + "\n"
                "heart-beat:10000,10000\n"
                "\n\x00\n"
            )
            await self._ws.send_str(connect_frame)
        except Exception:
            # Same resilience as a run-time disconnect: log and retry with
            # backoff rather than letting a connection failure go silent.
            __LOGGER__.exception("Failed to connect to the BLUETTI WebSocket Server")
            await self.reconnect()
            return

        __LOGGER__.info("Connect the BLUETTI WebSocket Server successfully.")

        self._receive_task = asyncio.ensure_future(self._run())
        self._heartbeat_task = asyncio.ensure_future(self._heartbeat_loop())

    async def disconnect(self) -> None:
        """Stop reconnecting, cancel background tasks, and close the connection."""
        self.running = False
        tasks = [t for t in (self._receive_task, self._heartbeat_task) if t is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._ws is not None:
            await self._ws.close()

    async def reconnect(self) -> None:
        """Reconnect with exponential backoff, if still running."""
        __LOGGER__.info("Websocket reconnect")
        if self.running:
            await asyncio.sleep(self.reconnect_delay)
            self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)
            await self.connect()
        else:
            __LOGGER__.info("Websocket have stop do not reconnect")

    async def _heartbeat_loop(self) -> None:
        r"""Send a STOMP heartbeat ("\n") on the configured interval."""
        while self.running:
            await asyncio.sleep(self.heartbeat_interval)
            if self._ws is None or self._ws.closed:
                break
            try:
                await self._ws.send_str("\n")
                __LOGGER__.debug("Sent STOMP heartbeat")
            except Exception as e:
                __LOGGER__.error("Failed to send heartbeat: %s", e)
                break

    async def _run(self) -> None:
        """Receive and handle STOMP frames until the connection closes."""
        ws = self._ws
        if ws is None:
            __LOGGER__.error("BLUETTI WebSocket task started without an open connection")
            return

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_frame(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    __LOGGER__.error("The BLUETTI WebSocket raised an error: %s", ws.exception())
                    break
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                    __LOGGER__.debug("WebSocket connection closed: %s", msg)
                    break
        except ApplicationRuntimeException as err:
            self._handle_application_runtime_exception(err)
        except Exception:
            __LOGGER__.exception("BLUETTI WebSocket task crashed")

        # Only the msgCode-805 path (handled inline above, not via this
        # except block) closes ws itself. Every other way out of the loop
        # above - an ERROR/CLOSE message, a raised ApplicationRuntimeException,
        # or an unexpected crash - leaves it open from our own side. The
        # heartbeat task's own is-it-closed check races against however long
        # aiohttp takes to notice the remote already closed its end, so it
        # can still slip through and fail the write instead of cleanly
        # breaking - closing it decisively here, as soon as we've decided to
        # abandon this connection, is what actually closes that window
        # (connect()'s heartbeat-task cancellation below is the remaining,
        # much narrower backstop: mid-send at this exact instant).
        if not ws.closed:
            await ws.close()

        if self.running:
            await self.reconnect()

    def _handle_application_runtime_exception(self, err: ApplicationRuntimeException) -> None:
        """
        Log a real STOMP ERROR frame from the cloud and notify on_error.

        Still retried the same as any other drop by the caller in _run()
        (some of these are transient), but a persistent one would otherwise
        re-log the same full traceback on every retry forever - once the
        message repeats, that's not new information.
        """
        if str(err) == self._last_error_message:
            __LOGGER__.debug("BLUETTI WebSocket task crashed (repeat): %s", err)
        else:
            __LOGGER__.exception("BLUETTI WebSocket task crashed")
            self._last_error_message = str(err)
        if self.on_error is not None:
            self.on_error(err)

    async def _handle_frame(self, message: str) -> None:
        """Parse and handle one incoming STOMP frame."""
        __LOGGER__.debug("Received the BLUETTI websocket message:\n %s", message)

        if not message or message == "\n":
            __LOGGER__.debug("Received heartbeat from server")
            return

        frame = stomper.Frame()
        frame.unpack(message)

        if frame.cmd == "ERROR":
            await self._handle_error_frame(frame)
        elif frame.cmd == "CONNECTED":
            await self._handle_connected_frame(frame)
        elif frame.cmd == "MESSAGE":
            self._invoke_handler(frame.body)

    async def _handle_error_frame(self, frame: stomper.Frame) -> None:
        error = frame.headers["message"].replace("\\c", ":")
        error = json.loads(error)
        if error["msgCode"] == 805:
            # Stop everything without cancelling our own currently-running
            # task (this runs inside _run()'s receive loop): flip the
            # running flag and close the socket so the loop exits on its
            # own next iteration, then stop the (separate) heartbeat task.
            self.running = False
            if self._heartbeat_task is not None:
                self._heartbeat_task.cancel()
            if self._ws is not None:
                await self._ws.close()
            if self.on_auth_expired is not None:
                self.on_auth_expired()
            __LOGGER__.info("token have expired stop ws connect")
        else:
            if error["msgCode"] in _TERMINAL_ERROR_CODES:
                # Same "stop, don't retry" outcome as 805 above, reached
                # the same way _run() already stops retrying on any other
                # exit from its receive loop: setting running False here,
                # before raising, means the "if self.running: reconnect()"
                # check it does afterwards is already False by the time it
                # runs. Deliberately not the 805 branch above - on_error
                # (below, via the raise) still fires with the real message,
                # instead of on_auth_expired's specifically-token-expired
                # framing, which wouldn't be accurate here (see
                # _TERMINAL_ERROR_CODES's own comment).
                self.running = False
            raise ApplicationRuntimeException(msgCode=error["msgCode"], errMessage=error["message"])

    async def _handle_connected_frame(self, frame: stomper.Frame) -> None:
        ws = self._ws
        if ws is None:
            __LOGGER__.error("Received a CONNECTED frame without an open connection, cannot subscribe")
            return

        # A real connection again - if the same ERROR frame recurs later,
        # that's new information worth a full traceback again, not a
        # continuation of whatever was failing before.
        self._last_error_message = None

        heartbeat = frame.headers.get("heart-beat", "0,0")
        server_send, server_receive = map(int, heartbeat.split(","))
        __LOGGER__.info(
            "Server heartbeat configuration: send=%s, receive=%s",
            server_send, server_receive,
        )

        user_name = frame.headers.get("user-name")
        if not user_name:
            __LOGGER__.error("CONNECTED frame missing 'user-name' header, cannot subscribe")
            return
        destination = f"/ws-subscribe/user/{user_name}/notify"
        sub = stomper.subscribe(destination, "clientUniqueId", ack="auto")
        await ws.send_str(sub)

    def _invoke_handler(self, body: str) -> None:
        if not self.__handler:
            return
        try:
            self.__handler(body)
        except Exception as e:
            __LOGGER__.error("error from callback %s: %s", self.__handler, e)
