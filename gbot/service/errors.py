"""Typed failures every service consumer can tell apart without parsing messages."""

import json
from dataclasses import dataclass

from groken.client import ConnectError


class ServiceError(Exception):
    """Base class for failures the TUI and CLI show as a state rather than a crash."""


class SignedOutError(ServiceError):
    """No usable login: no tokens, or the backend still says 401 after one refresh."""

    def __init__(self, detail: str = "Not signed in. Run: gbot login") -> None:
        super().__init__(detail)


class AsleepError(ServiceError):
    """The gateway answered 417: the bot computer is hibernated.

    Raised only for background work (the event stream, polling). Background work never wakes the pod; an action the
    person takes does, by re-minting the gateway connection through EnsureSandBox.
    """

    def __init__(self, detail: str = "The bot computer is asleep.") -> None:
        super().__init__(detail)


REFUSAL_CODES = frozenset(
    {
        "permission_denied",
        "failed_precondition",
        "not_found",
        "invalid_argument",
        "unimplemented",
    }
)
_TEMPORAL = "for temporal agents"
_DEFAULTS = {
    "permission_denied": "The server refused this for your account.",
    "failed_precondition": "This is not available for this bot or account.",
    "not_found": "Not found.",
    "invalid_argument": "The server did not accept this request.",
    "unimplemented": "The server does not support this yet.",
}


@dataclass(frozen=True)
class Refusal:
    """A server refusal to show as a plain notice rather than an error."""

    code: str
    message: str


def refusal(error: BaseException) -> Refusal | None:
    """The code and readable message of a refusal the person should see as a notice, else None.

    Team-only calls on a personal account refuse with a code and a message meant for the user, and a backend-hosted
    bot answers gateway commands its server lacks with a "not supported for Temporal agents" error. Anything else
    (transport failures, 5xx without a known code) returns None and stays an error.
    """
    if not isinstance(error, ConnectError):
        return None
    text = error.body if isinstance(error.body, str) else ""
    try:
        body = json.loads(text)
    except ValueError:
        body = None
    code = ""
    message = ""
    if isinstance(body, dict):
        raw_code = body.get("code")
        code = raw_code.casefold() if isinstance(raw_code, str) else ""
        raw = body.get("message", body.get("error"))
        if isinstance(raw, dict):
            raw = raw.get("message")
        message = raw.strip() if isinstance(raw, str) else ""
    elif text.strip().casefold() in REFUSAL_CODES:
        code = text.strip().casefold()
    else:
        message = text.strip()
    if _TEMPORAL in text.casefold():
        return Refusal(
            code if code in REFUSAL_CODES else "unimplemented",
            message[:300] or _DEFAULTS["unimplemented"],
        )
    if code not in REFUSAL_CODES:
        return None
    return Refusal(code, message[:300] or _DEFAULTS[code])
