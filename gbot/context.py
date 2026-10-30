from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Protocol

from groken.client import ConnectError, SandClient
from groken.gateway import GatewayManager

from .output import Output
from .service.errors import SignedOutError

if TYPE_CHECKING:
    from .service.client import GbotService


class Manager(Protocol):
    def command(self, method: str, args: dict[str, object] | None = None) -> object: ...
    def send_prompt(self, agent_id: str, text: str) -> dict[str, object]: ...
    def transcript_tail(self, agent_id: str) -> list[dict[str, object]]: ...
    def ask(
        self,
        agent_id: str,
        text: str,
        timeout_s: float = 600,
        idle_s: float = 45,
        *,
        on_entry: Callable[[dict[str, object]], bool] | None = None,
    ) -> str: ...
    def ask_stream(
        self,
        agent_id: str,
        text: str,
        timeout_s: float = 600,
        idle_s: float = 45,
        on_chunk: Callable[[str], None] | None = None,
        *,
        on_entry: Callable[[dict[str, object]], bool] | None = None,
    ) -> str: ...
    def events(
        self, channels: list[str] | None = None
    ) -> Iterator[dict[str, object]]: ...


class Backend(Protocol):
    def unary(
        self, service: str, method: str, payload: dict[str, object]
    ) -> dict[str, object]: ...

    def list_sand_mcp_tools(
        self, server_identifiers: list[str] | None = None
    ) -> dict[str, object]: ...


manager_factory: Callable[[], Manager] = GatewayManager
backend_factory: Callable[[], Backend] = SandClient


def _connect_service() -> GbotService:
    from .service.client import connect

    return connect()


service_factory: Callable[[], GbotService] = _connect_service


class Context:
    def __init__(
        self, args: argparse.Namespace, factory: Callable[[], Manager] | None = None
    ) -> None:
        self.args = args
        self.debug = args.debug
        self.out = Output(getattr(args, "json", False))
        self._factory = factory or manager_factory
        self._manager: Manager | None = None
        self._backend: Backend | None = None
        self._service: GbotService | None = None

    def service(self) -> GbotService:
        if self._service is None:
            try:
                self._service = service_factory()
            except SignedOutError as exc:
                raise ConnectError(401, "not signed in") from exc
        return self._service

    def close(self) -> None:
        if self._service is not None:
            self._service.close()

    def manager(self) -> Manager:
        if self._manager is None:
            try:
                self._manager = self._factory()
            except SystemExit as exc:
                raise ConnectError(401, "not signed in") from exc
        return self._manager

    def backend(self) -> Backend:
        if self._backend is None:
            try:
                self._backend = backend_factory()
            except SystemExit as exc:
                raise ConnectError(401, "not signed in") from exc
        return self._backend


def prompt(args: argparse.Namespace) -> str:
    text = sys.stdin.read() if args.text == ["-"] else " ".join(args.text)
    if not text.strip():
        raise ValueError("Prompt must not be empty.")
    return text
