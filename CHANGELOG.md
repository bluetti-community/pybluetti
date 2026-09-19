# 0.2.5

- Added `HttpStatusException` (an `ApplicationRuntimeException`), raised by `_request()` when the gateway answers with a non-2xx HTTP status instead of the plain base class: `status` and `reason` carry the HTTP status and reason phrase (`str(exc)` is e.g. `[504] HTTP 504 Gateway Timeout` instead of `[504] An unknown error has occurred.`), `data` the response body, and `is_transient` says whether one immediate retry is worth a try (502/503/504). `msgCode` is still the HTTP status, so every existing caller keeps working; a caller can now tell a gateway 504 from an API `msgCode` that happens to be 504. Prompted by bluetti-community/bluetti-home-assistant#53, a lone 504 on one poll of thirty failing the whole poll.

# 0.2.4

- `StompClient` accepts optional `app_key`/`app_ver` keyword arguments, sent as `x-app-key`/`x-app-ver` CONNECT headers (alongside a fixed `x-os:open`) - BLUETTI's cloud gateway does client identification/version gating on this connection (see 0.2.3's own `msgCode 600` fix), and BLUETTI's own official Home Assistant integration's client already sends exactly these three headers on every connection. Optional and independent of everything else here - a caller with nothing to identify itself with still gets exactly the previous behavior, not headers claiming an identity it doesn't have. Raises `ValueError` if only one of the two is given.

# 0.2.3

- `StompClient` now stops retrying (instead of reconnecting forever, every ~30s with backoff) once the cloud sends msgCode 400, 403, or 600 in an ERROR frame - these are confirmed (600, directly observed retried unsuccessfully for over a day against a real device) or strongly implied (400, 403, per BLUETTI's own official Home Assistant integration's client, which groups all three with a genuine token expiry - msgCode 805 - as needing the same "stop and don't retry" response) to never succeed on retry. Deliberately not folded into the existing `on_auth_expired` (805) path: none of these three necessarily mean the access token itself is the problem, so claiming that would be misleading - they still reach a caller via `on_error`, with the real message, same as any other non-805 code.

# 0.2.2

- `ApplicationRuntimeException`'s `msgCode` is now included in `str(exc)` itself (e.g. `[500] server error`), not just the separate `.msgCode` attribute - every existing caller that logs or displays this exception (notably `bluetti-home-assistant`'s own websocket-error Repair issue, which shows `str(err)` directly to the end user) now surfaces the code with no changes needed on its end. Prompted by a real user hitting an unrecognized code with no way to report which one it was short of digging through a raw STOMP frame dump (bluetti-community/bluetti-home-assistant#35). `.message` is unchanged - still the plain, code-free text.

# 0.2.1rc1 (pre-release)

- Fixed `_run()` leaving the abandoned connection open on every path except a token-expiry (msgCode 805): an `ApplicationRuntimeException`, a plain ERROR/CLOSE message, or an unexpected crash all left `close()` uncalled on the old connection. 0.2.0's heartbeat-task cancellation in `connect()` was only a partial fix - the still-open connection let a concurrently-running heartbeat send slip past its own is-it-closed check and fail against the transport before aiohttp itself noticed the remote side had already closed, reported as "Failed to send heartbeat: Cannot write to closing transport" repeating on every reconnect cycle in production (real-world confirmation: bluetti-official/bluetti-home-assistant#145). `_run()` now closes the connection itself as soon as it decides to abandon it, closing that race instead of just narrowing it.

# 0.2.0

- **Breaking**: `StompClient.__init__`'s `handler`, `on_auth_expired`, and the new `on_error` are now keyword-only (`session`/`url`/`access_token` stay positional). Update any call passing `handler` positionally to `handler=...`.
- Added `StompClient(on_error=...)`, invoked for any ERROR frame the cloud sends back other than a token-expiry (msgCode 805) - previously invisible to a caller beyond a bare `.exception()` log line inside `_run()`'s own retry loop.
- Fixed `StompClient` leaking the previous connection's heartbeat task into every reconnect that follows a dropped or rejected connection - `connect()` now cancels it first, instead of the task quietly failing its next send against the closing transport.
- `StompClient` no longer re-logs a full traceback on every retry of a persistently repeated `ApplicationRuntimeException` - only the first occurrence and any occurrence with a different message log at full severity; repeats log at debug.

# 0.1.1

- Adopted `mypy --strict` across the whole package (wired into CI via `scripts/typecheck`), fulfilling the "strict-typing" requirement of Home Assistant's Platinum integration quality scale. Along the way, fixed a real type-unsoundness bug: `Bluetti` was declared `Generic[T]` at the class level but never actually parametrized per instance - `_request()` now returns `UnifyResponse[Any] | str`, with `ProductClient`'s public methods restoring a precise type via `typing.cast` at the boundary where `pydantic.TypeAdapter` already validated it at runtime.
- Moved to the `bluetti-community` GitHub organization (was `pybluetti`); no change to the PyPI package name or install command.

# 0.1.0

- Replaced `StompClient`'s blocking `websocket-client` transport (a dedicated daemon thread plus a second dedicated heartbeat thread) with `aiohttp`'s native async websocket client (`ClientSession.ws_connect`). `connect()`/`disconnect()`/`reconnect()` are now coroutines; the receive loop and heartbeat run as `asyncio.Task`s instead of threads. `StompListener` is folded into `StompClient` (no more callback registration to justify a separate object). STOMP protocol framing (`stomper`) and all frame-handling logic/log messages are unchanged. `websocket-client` dropped from dependencies.
- Migrated the BLUETTI cloud API client from `bluetti-home-assistant`'s `custom_components/bluetti/api/` (plus `model/product.py` and `application_exception.py`): `Bluetti`/`ProductClient` (HTTP), `StompClient`/`StompListener` (websocket push updates), `UserProduct`, `UnifyResponse`, `ApplicationRuntimeException`. Decoupled from Home Assistant - server URLs and an `on_auth_expired` callback are now plain constructor arguments instead of a `hass` object. The websocket transport itself (`websocket-client` on a dedicated thread) is unchanged in this step.
- Initial repository scaffold: packaging (`pyproject.toml`, `hatchling`), test/lint scripts, CI, MIT license.
