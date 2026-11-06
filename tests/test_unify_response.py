"""Tests for unify_response.py."""

from pybluetti.unify_response import UnifyResponse


def test_is_ok_true_when_msg_code_zero() -> None:
    response = UnifyResponse[dict](msgId="1", msgCode=0, data={})
    assert response.is_ok() is True


def test_is_ok_false_when_msg_code_nonzero() -> None:
    response = UnifyResponse[dict](msgId="1", msgCode=1)
    assert response.is_ok() is False


def test_has_data_true_when_ok_and_data_present() -> None:
    response = UnifyResponse[dict](msgId="1", msgCode=0, data={"a": 1})
    assert response.has_data() is True


def test_has_data_false_when_data_missing() -> None:
    response = UnifyResponse[dict](msgId="1", msgCode=0, data=None)
    assert response.has_data() is False


def test_has_data_false_when_not_ok() -> None:
    response = UnifyResponse[dict](msgId="1", msgCode=1, data={"a": 1})
    assert response.has_data() is False


def test_message_keeps_the_clouds_own_text() -> None:
    # A rejected token, as the gateway answers it (HTTP 200, the verdict in
    # the body), verbatim: the sentence ends in a fullwidth exclamation mark.
    cloud_text = "无效的访问令牌\uff01"
    response = UnifyResponse[dict].model_validate(
        {"msgId": "1", "msgCode": 803, "message": cloud_text, "data": None}
    )
    assert response.message == cloud_text


def test_message_is_none_when_the_answer_has_none() -> None:
    response = UnifyResponse[dict](msgId="1", msgCode=0, data={})
    assert response.message is None
