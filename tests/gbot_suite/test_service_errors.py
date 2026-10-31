import json

from gbot.service.errors import Refusal, refusal
from groken.client import ConnectError


def _error(body: object, status: int = 400) -> ConnectError:
    return ConnectError(status, body if isinstance(body, str) else json.dumps(body))


def test_refusal_keeps_the_server_message_for_known_codes() -> None:
    error = _error(
        {"code": "permission_denied", "message": "Share the bot with a team first."},
        403,
    )
    assert refusal(error) == Refusal(
        "permission_denied", "Share the bot with a team first."
    )


def test_refusal_falls_back_to_a_default_sentence() -> None:
    assert refusal(_error({"code": "failed_precondition"})) == Refusal(
        "failed_precondition", "This is not available for this bot or account."
    )
    assert refusal(_error("not_found", 404)) == Refusal("not_found", "Not found.")


def test_refusal_reads_nested_gateway_errors() -> None:
    error = _error({"error": {"message": "Bad slug"}, "code": "invalid_argument"})
    assert refusal(error) == Refusal("invalid_argument", "Bad slug")


def test_temporal_unsupported_is_a_refusal_without_a_code() -> None:
    error = _error(
        {"error": "The server does not support publishSkill for Temporal agents"}, 500
    )
    assert refusal(error) == Refusal(
        "unimplemented", "The server does not support publishSkill for Temporal agents"
    )


def test_other_failures_stay_errors() -> None:
    assert refusal(_error({"code": "internal", "message": "boom"}, 500)) is None
    assert refusal(_error("upstream timeout", 504)) is None
    assert refusal(ValueError("x")) is None


def test_long_messages_are_capped() -> None:
    error = _error({"code": "permission_denied", "message": "x" * 1000})
    result = refusal(error)
    assert result is not None and len(result.message) == 300
