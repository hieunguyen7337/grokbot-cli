"""Discover and dispatch independently registered slash commands."""

import importlib
import pkgutil
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Literal

from gbot.output import terminal_safe

if TYPE_CHECKING:
    from textual.screen import Screen

    from gbot.service.api import Service
    from gbot.tui.app import GbotApp

Scope = Literal["home", "session", "any"]


@dataclass(frozen=True)
class SlashContext:
    app: "GbotApp"
    screen: "Screen"
    bot_id: str | None
    session_id: str | None

    @property
    def service(self) -> "Service":
        return self.app.service


@dataclass(frozen=True)
class SlashCommand:
    name: str
    summary: str
    run: Callable[[SlashContext, str], None]
    scope: Scope = "any"
    args: str = ""
    needs_bot: bool = False


@cache
def commands() -> tuple[SlashCommand, ...]:
    found: dict[str, tuple[SlashCommand, str]] = {}
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda item: item.name):
        module_name = f"{__name__}.{info.name}"
        module = importlib.import_module(module_name)
        for command in getattr(module, "COMMANDS", ()):
            if not re.fullmatch(r"[a-z][a-z0-9-]*", command.name):
                raise ValueError(f"Invalid command {command.name!r} in {module_name}")
            if command.name in found:
                raise ValueError(
                    f"Duplicate command {command.name!r} in {found[command.name][1]} and {module_name}"
                )
            found[command.name] = (command, module_name)
    return tuple(value[0] for _, value in sorted(found.items()))


def available(scope: Scope) -> tuple[SlashCommand, ...]:
    return tuple(c for c in commands() if c.scope in ("any", scope))


def complete(prefix: str, scope: Scope) -> tuple[SlashCommand, ...]:
    return tuple(
        c
        for c in available(scope)
        if c.name.startswith(prefix.casefold().removeprefix("/"))
    )


def parse(text: str) -> tuple[str, str]:
    parts = text.strip().removeprefix("/").split(maxsplit=1)
    return (
        (parts[0].casefold(), parts[1].strip() if len(parts) > 1 else "")
        if parts
        else ("", "")
    )


def run(ctx: SlashContext, text: str) -> str | None:
    from gbot.tui.screens.home import HomeScreen

    name, args = parse(text)
    matches = [c for c in commands() if c.name == name] or [
        c for c in commands() if name and c.name.startswith(name)
    ]
    if len(matches) != 1:
        return f"Unknown command /{name} · /help lists commands"
    command = matches[0]
    scope = "home" if isinstance(ctx.screen, HomeScreen) else "session"
    if command.scope not in ("any", scope):
        return f"/{command.name} works " + (
            "in a session" if command.scope == "session" else "on the home screen"
        )
    if command.needs_bot and not ctx.bot_id:
        return "Select a bot first"
    try:
        command.run(ctx, args)
    except Exception as error:  # noqa: BLE001 - command boundary
        return terminal_safe(str(error)).split("\n", 1)[0]
    return None
