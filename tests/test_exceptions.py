"""Tests for exceptions.py."""

from pybluetti.exceptions import ApplicationRuntimeException, HttpStatusException


def test_str_includes_msg_code_and_custom_message() -> None:
    # The msgCode must be visible in str(exc) itself, not just the .msgCode
    # attribute - see this file's own docstring in exceptions.py for why
    # (bluetti-community/bluetti-home-assistant#35: a real user had no way
    # to report which error code they got, since nothing that logs or
    # displays this exception showed it).
    err = ApplicationRuntimeException(msgCode=1234, errMessage="Upgrade required.")

    assert str(err) == "[1234] Upgrade required."
    assert err.message == "Upgrade required."
    assert err.msgCode == 1234


def test_str_includes_msg_code_with_default_message() -> None:
    err = ApplicationRuntimeException(msgCode=500)

    assert str(err) == "[500] An unknown error has occurred."


def test_data_is_stored_unchanged() -> None:
    err = ApplicationRuntimeException(msgCode=401, data="unauthorized")

    assert err.data == "unauthorized"


def test_http_status_exception_is_an_application_runtime_exception() -> None:
    # Every caller that matched on ApplicationRuntimeException / msgCode
    # before this class existed keeps working unchanged.
    err = HttpStatusException(504, "Gateway Timeout", data="<html>...</html>")

    assert isinstance(err, ApplicationRuntimeException)
    assert err.msgCode == 504
    assert err.status == 504
    assert err.reason == "Gateway Timeout"
    assert err.data == "<html>...</html>"
    assert str(err) == "[504] HTTP 504 Gateway Timeout"


def test_http_status_exception_without_a_reason_phrase() -> None:
    err = HttpStatusException(502, "")

    assert str(err) == "[502] HTTP 502"


def test_transient_gateway_statuses() -> None:
    # A lone 502/503/504 on one poll of thirty is a proxy hiccup worth one
    # immediate retry (bluetti-community/bluetti-home-assistant#53); a
    # 401 or 404 is not.
    assert HttpStatusException(502, "Bad Gateway").is_transient
    assert HttpStatusException(503, "Service Unavailable").is_transient
    assert HttpStatusException(504, "Gateway Timeout").is_transient
    assert not HttpStatusException(401, "Unauthorized").is_transient
    assert not HttpStatusException(404, "Not Found").is_transient
