"""Client for the BLUETTI product/device endpoints."""

import logging
from typing import Any, cast

from .client import Bluetti
from .const import Method
from .models import UserProduct
from .unify_response import UnifyResponse

__LOGGER__ = logging.getLogger(__name__)


class ProductClient(Bluetti):
    """Class describing for the BLUETTI products."""

    @property
    def logger(self) -> logging.Logger:
        """Get the api client logger."""
        return __LOGGER__

    async def get_user_products(self) -> UnifyResponse[list[UserProduct]]:
        """Get the devices/power stations bound to the account."""
        result = await self._request(
            list[UserProduct],
            Method.GET,
            "/api/bluiotdata/ha/v1/devices",
        )
        return cast("UnifyResponse[list[UserProduct]]", result)

    async def get_user_products_v2(self) -> UnifyResponse[list[UserProduct]]:
        """
        Get the devices bound to the account from the v2 route.

        This is the route BLUETTI's own integration lists devices from. Each
        device can carry ``supportNetwork``: anything but ``"1"`` means no
        cloud control.
        """
        result = await self._request(
            list[UserProduct],
            Method.GET,
            "/api/bluiotdata/ha/v2/devices",
        )
        return cast("UnifyResponse[list[UserProduct]]", result)

    async def get_device_status(self, sns: str | None = None) -> UnifyResponse[list[UserProduct]]:
        """Poll device state."""
        result = await self._request(
            list[UserProduct],
            Method.GET,
            "/api/bluiotdata/ha/v1/deviceStates",
            params={"sns": sns},
        )
        return cast("UnifyResponse[list[UserProduct]]", result)

    async def control_device(self, payload: dict[str, Any] | None = None) -> UnifyResponse[dict[str, Any]] | str:
        """Send a control command to a device."""
        result = await self._request(
            dict,
            method=Method.POST,
            path="/api/bluiotdata/ha/v1/fulfillment",
            body=payload,
        )
        return cast("UnifyResponse[dict[str, Any]] | str", result)

    async def bind_devices(self, payload: dict[str, Any] | None = None) -> UnifyResponse[dict[str, Any]] | str:
        """Bind devices to the account."""
        result = await self._request(
            dict,
            method=Method.POST,
            path="/api/bluiotdata/ha/v1/bindDevices",
            body=payload,
        )
        return cast("UnifyResponse[dict[str, Any]] | str", result)
