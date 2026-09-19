"""Base BLUETTI cloud API client."""

import logging
from abc import abstractmethod
from collections.abc import Callable
from json import dumps
from typing import Any

import aiohttp
from pydantic import TypeAdapter

from .const import Method
from .exceptions import HttpStatusException
from .unify_response import UnifyResponse


class Bluetti:
    """Base class describing interactions with the BLUETTI cloud service."""

    _accessToken: str | None = None
    _httpSession: aiohttp.ClientSession
    _gateway_url: str
    _on_auth_expired: Callable[[], None] | None

    @property
    @abstractmethod
    def logger(self) -> logging.Logger:
        """The subclass's logger."""

    def __init__(
        self,
        httpSession: aiohttp.ClientSession,
        gateway_url: str,
        accessToken: str | None = None,
        on_auth_expired: Callable[[], None] | None = None,
    ) -> None:
        """
        Initialize the client.

        - httpSession: the aiohttp session to issue requests on.
        - gateway_url: the BLUETTI cloud gateway base URL (region-specific).
        - accessToken: the OAuth2 access token to authenticate requests with.
        - on_auth_expired: called when the cloud reports the access token as
          expired (msgCode 805), so the caller can react (e.g. trigger a
          refresh or re-authentication flow).
        """
        self._httpSession = httpSession
        self._gateway_url = gateway_url
        self._accessToken = accessToken
        self._on_auth_expired = on_auth_expired

    def update_access_token(self, access_token: str) -> None:
        """
        Swap in a freshly refreshed access token for future requests.

        The token is captured at construction and used as-is on every
        request; a caller that proactively refreshes an OAuth2 token before
        it expires needs a way to hand the new one to an already-constructed
        client without tearing it down and losing its state.
        """
        self._accessToken = access_token

    async def _request(
        self,
        responseType: Any,
        method: Method,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> UnifyResponse[Any] | str:
        """
        Send a request to the server.

        Returns UnifyResponse[Any] since responseType is a runtime value (fed
        straight into pydantic's TypeAdapter, not a static type parameter) -
        callers restore a precise type at the boundary with typing.cast,
        matching what responseType actually validated.

        - responseType: the type of response data, without the UnifyResponse wrapper.
        - method: the HTTP method.
        """
        # when the method is 'GET', the request body must be null.
        if method == Method.GET:
            body = None

        headers = {
            "Authorization": f"{self._accessToken}",
        }

        # Remove None values from params and json
        if params:
            params = {k: v for k, v in params.items() if v is not None}
            self.logger.debug("======> Client request parameters: %s", params)
        if body:
            body = {k: v for k, v in body.items() if v is not None}
            self.logger.debug("======> Client request body: %s", dumps(body))
            headers["Content-Type"] = "application/json"

        async with self._httpSession.request(
            method,
            f"{self._gateway_url}{path}",
            headers=headers,
            json=body,
            params=params,
        ) as response:
            self.logger.debug("<====== Server response status %s from %s", response.status, response.url)
            self.logger.debug("<====== Server response type is: %s", response.content_type)

            if not response.ok:
                raise HttpStatusException(
                    response.status, response.reason or "", data=await response.text()
                )

            if response.content_type.lower().startswith("application/json"):
                data = await response.json()  # read response body to JSON
                unify_response = TypeAdapter(UnifyResponse[responseType]).validate_python(data)
                if data.get("msgCode") == 805 and self._on_auth_expired is not None:
                    self._on_auth_expired()
                    self.logger.info("token have expired")
                return unify_response
            return await response.text()
