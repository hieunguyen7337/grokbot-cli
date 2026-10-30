"""Typed failures every service consumer can tell apart without parsing messages."""


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
