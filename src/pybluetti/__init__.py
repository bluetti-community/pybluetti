"""
Async Python client for the BLUETTI cloud API.

Extracted from
https://github.com/bluetti-official/bluetti-home-assistant's
custom_components/bluetti/api/, the same way
https://github.com/pyenphase/pyenphase backs the enphase_envoy Home Assistant
integration. Fully async, including the websocket push-update transport
(`aiohttp`'s native websocket client, no dedicated threads). Wiring
bluetti-home-assistant to depend on this package is a separate follow-up.
"""

from .client import Bluetti
from .const import Method
from .exceptions import ApplicationRuntimeException, HttpStatusException
from .models import UserProduct
from .product_client import ProductClient
from .unify_response import UnifyResponse
from .websocket import StompClient

__version__ = "0.1.1"

__all__ = [
    "ApplicationRuntimeException",
    "Bluetti",
    "HttpStatusException",
    "Method",
    "ProductClient",
    "StompClient",
    "UnifyResponse",
    "UserProduct",
]
