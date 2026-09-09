"""Tests for exceptions.py."""

from pybluetti.exceptions import ApplicationRuntimeException


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
