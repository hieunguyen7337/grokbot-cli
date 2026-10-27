import argparse
import sys
from collections.abc import Callable, Iterator
from typing import Protocol

from groken.client import ConnectError
from groken.gateway import GatewayManager

from .output import Output


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


manager_factory: Callable[[], Manager] = GatewayManager


class Context:
    def __init__(
        self, args: argparse.Namespace, factory: Callable[[], Manager] | None = None
    ) -> None:
        self.args = args
        self.debug = args.debug
        self.out = Output(getattr(args, "json", False))
        self._factory = factory or manager_factory
        self._manager: Manager | None = None

    def manager(self) -> Manager:
        if self._manager is None:
            try:
                self._manager = self._factory()
            except SystemExit as exc:
                raise ConnectError(401, "not signed in") from exc
        return self._manager


def prompt(args: argparse.Namespace) -> str:
    text = sys.stdin.read() if args.text == ["-"] else " ".join(args.text)
    if not text.strip():
        raise ValueError("Prompt must not be empty.")
    return text
