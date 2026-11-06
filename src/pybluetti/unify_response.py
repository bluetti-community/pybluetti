"""The envelope every BLUETTI cloud API response is wrapped in."""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class UnifyResponse(BaseModel, Generic[T]):
    """The Unify Server Response class."""

    msgId: str
    msgCode: int
    # The cloud's own text for msgCode - for 805 and 803 a different Chinese
    # sentence each, which is what tells two rejections apart in a log.
    # None when an answer does not carry it.
    message: str | None = None
    data: T | None = None

    def is_ok(self) -> bool:
        """Return true if the server response is success."""
        return self.msgCode == 0

    def has_data(self) -> bool:
        """Return true if the server response is success and has response data."""
        return self.is_ok() and self.data is not None
