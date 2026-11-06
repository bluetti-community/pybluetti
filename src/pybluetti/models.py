"""Response models for the BLUETTI cloud API."""

from typing import Any

from pydantic import BaseModel


class UserProduct(BaseModel):
    """A device/power station bound to a BLUETTI account."""

    sn: str
    stateList: list[dict[str, Any]]
    online: str
    model: str | None = None
    name: str | None = None
    isBindByCurUser: str | None = None
    supportNetwork: str | None = None
