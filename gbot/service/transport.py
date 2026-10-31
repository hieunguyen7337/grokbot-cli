"""One seam for every network call: gateway commands and backend GrokBotService RPCs."""

from collections.abc import Callable, Mapping
from typing import Protocol

from groken.client import GROK_BOT, ConnectError

from .routing import Harness, Router


class Transport(Protocol):
    def command(self, name: str, args: Mapping[str, object] | None = None) -> object:
        """POST /api/<name> on the bot's gateway and return the decoded reply."""
        ...

    def rpc(self, method: str, payload: Mapping[str, object]) -> dict[str, object]:
        """Call aiserver.v1.GrokBotService/<method> on the backend."""
        ...


class _ContextTransport:
    """Adapter over the CLI's lazily built gateway manager and backend client (not thread-safe)."""

    def __init__(self, ctx: object) -> None:
        # Typed loosely to keep gbot.service free of a gbot.context import cycle.
        self._ctx = ctx

    def command(self, name: str, args: Mapping[str, object] | None = None) -> object:
        manager = self._ctx.manager()  # pyright: ignore[reportAttributeAccessIssue]
        return manager.command(name, dict(args) if args is not None else None)

    def rpc(self, method: str, payload: Mapping[str, object]) -> dict[str, object]:
        backend = self._ctx.backend()  # pyright: ignore[reportAttributeAccessIssue]
        return backend.unary(GROK_BOT, method, dict(payload))


class ContextTransport(Router):
    """CLI transport using the context's shared harness registry."""

    def __init__(self, ctx: object) -> None:
        harness = getattr(ctx, "harness", None)
        if harness is None:
            harness = Harness()
            ctx.harness = harness  # pyright: ignore[reportAttributeAccessIssue]
        super().__init__(_ContextTransport(ctx), harness)


Reply = object | Callable[[dict[str, object]], object]


class FakeTransport:
    """Scripted transport for tests and demos.

    Replies are values, callables taking the args dict, or exceptions to raise. Every call is recorded in `calls`
    as (kind, name, args) with kind "command" or "rpc". A missing command or RPC raises ConnectError(404).
    """

    def __init__(
        self,
        commands: Mapping[str, Reply] | None = None,
        rpcs: Mapping[str, Reply] | None = None,
    ) -> None:
        self.commands: dict[str, Reply] = dict(commands or {})
        self.rpcs: dict[str, Reply] = dict(rpcs or {})
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    @staticmethod
    def _reply(
        table: Mapping[str, Reply], name: str, args: dict[str, object]
    ) -> object:
        if name not in table:
            raise ConnectError(404, f"unknown: {name}")
        reply = table[name]
        if isinstance(reply, BaseException):
            raise reply
        if callable(reply):
            return reply(args)
        return reply

    def command(self, name: str, args: Mapping[str, object] | None = None) -> object:
        sent = dict(args or {})
        self.calls.append(("command", name, sent))
        return self._reply(self.commands, name, sent)

    def rpc(self, method: str, payload: Mapping[str, object]) -> dict[str, object]:
        sent = dict(payload)
        self.calls.append(("rpc", method, sent))
        reply = self._reply(self.rpcs, method, sent)
        return dict(reply) if isinstance(reply, Mapping) else {}
