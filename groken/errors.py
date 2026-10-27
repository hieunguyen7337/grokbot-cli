import httpx

from .client import ConnectError
from .gateway import ReplyIncompleteError


def explain_error(exc: Exception, *, cli: str = "groken") -> str:
    if isinstance(exc, ReplyIncompleteError):
        return (
            f"Bot {exc.bot_id} is still working after {exc.elapsed_s:g}s. "
            f"Try a longer --timeout or run: {cli} tail {exc.bot_id}"
        )
    if isinstance(exc, ConnectError):
        body = exc.body.lower()
        if exc.status == 401:
            if "refresh" in body or "unauthorized after" in body:
                return f"Authentication refresh failed repeatedly. Run: {cli} login"
            return f"Authentication expired. Run: {cli} login"
        if exc.status == 429 or "quota" in body or "rate limit" in body:
            return "Grok quota or rate limit reached. Wait and retry with backoff; check your account quota."
        if exc.status == 0:
            return "Network connection failed. Check your internet connection and the Grok app, then retry."
        if "could not be routed" in body:
            return f"The cloud sandbox is unreachable or recovering. Retry in a minute; if it persists, run: {cli} doctor"
        if "unknown gateway method" in body:
            return f"The installed Grok Bot gateway does not support this command. Update Grok Bot, then re-check with: {cli} doctor"
        return f"Gateway error {exc.status}: {exc.body[:200]}"
    if isinstance(exc, httpx.TimeoutException):
        return "The network request timed out. Check your connection and retry."
    if isinstance(exc, httpx.ConnectError):
        return "Could not connect to the Grok app or network. Check that it is running, then retry."
    return str(exc)
