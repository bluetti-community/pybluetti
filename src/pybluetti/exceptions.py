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
