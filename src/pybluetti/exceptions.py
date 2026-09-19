"""Exceptions raised by the pybluetti client."""

from typing import Any


class ApplicationRuntimeException(Exception):
    """Raised when a BLUETTI cloud API call fails."""

    message: str = "An unknown error has occurred."
    msgCode: int
    data: dict[str, Any] | str | None = None

    def __init__(
        self, msgCode: int, data: dict[str, Any] | str | None = None, errMessage: str | None = None
    ) -> None:
        self.msgCode = msgCode
        self.data = data

        if errMessage is not None:
            self.message = errMessage

        # msgCode is folded into str(self) (not just kept as the separate
        # .msgCode attribute) because it's the one piece of information
        # every existing caller that logs or displays this exception
        # already shows without any changes on their end - notably
        # bluetti-home-assistant's own websocket-error Repair issue, which
        # surfaces str(err) directly to the end user (see that repo's
        # __init__.py, ISSUE_ID_WEBSOCKET_ERROR). Without it, a real user
        # hitting an unrecognized error code had no way to report which one
        # they got short of enabling debug logging and finding the raw STOMP
        # frame themselves (see bluetti-community/bluetti-home-assistant#35,
        # where exactly that happened - the code was never surfaced anywhere
        # a person actually looks by default). .message stays the plain,
        # code-free text for any caller that only wants that.
        super().__init__(f"[{msgCode}] {self.message}")


class HttpStatusException(ApplicationRuntimeException):
    """
    Raised when the BLUETTI gateway answers with a non-2xx HTTP status.

    The API's own failures come back as HTTP 200 with a non-zero ``msgCode``
    in the body; this one is the layer below that - the gateway itself
    (502/503/504 from a proxy, 401 from the edge) - and ``msgCode`` is the
    HTTP status code, which is what every caller matched on before this
    class existed (still an ApplicationRuntimeException, so nothing
    changes for them). ``status`` says the same thing under its real name,
    ``reason`` is the HTTP reason phrase, ``data`` the response body. A
    caller that wants to retry a transient gateway error - a lone 504 on
    one poll of thirty (bluetti-community/bluetti-home-assistant#53) - can
    now tell it apart from an API ``msgCode`` that happens to be 504.
    """

    status: int
    reason: str

    def __init__(self, status: int, reason: str, data: dict[str, Any] | str | None = None) -> None:
        self.status = status
        self.reason = reason
        super().__init__(msgCode=status, data=data, errMessage=f"HTTP {status} {reason}".rstrip())

    @property
    def is_transient(self) -> bool:
        """Whether one immediate retry is worth a try (a proxy/gateway hiccup)."""
        return self.status in (502, 503, 504)
