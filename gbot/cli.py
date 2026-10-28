import argparse
import importlib
import pkgutil
import sys
from typing import NoReturn

import httpx

from groken.client import ConnectError
from groken.gateway import ReplyIncompleteError

from . import __version__, commands
from .context import Context
from .output import Output, safe_streams

_UNRECOGNIZED = "unrecognized arguments: "


def _redact(token: str) -> str:
    # Keep option names so the user can see what was wrong, never their values:
    # `gbot secret REF --value=...` must not echo a secret into logs.
    if token.startswith("-"):
        return token.split("=", 1)[0] + ("=<hidden>" if "=" in token else "")
    return "<hidden>"


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        if message.startswith(_UNRECOGNIZED):
            tokens = message[len(_UNRECOGNIZED) :].split(" ")
            message = _UNRECOGNIZED + " ".join(_redact(token) for token in tokens)
        raise ValueError(message)


def main(argv: list[str] | None = None) -> int:
    try:
        with safe_streams():
            try:
                return _main(argv)
            finally:
                sys.stdout.flush()
                sys.stderr.flush()
    except BrokenPipeError:
        return 0


def _main(argv: list[str] | None) -> int:
    parser = Parser(
        prog="gbot",
        description="Talk to your existing Grok Bot bots.",
        epilog="Exit codes: 0 ok; 1 error; 2 needs attention; 3 not signed in or auth failed; 4 still working; 130 interrupted.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--debug", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    for module in pkgutil.iter_modules(commands.__path__):
        importlib.import_module(f"{commands.__name__}.{module.name}").register(
            subparsers
        )
    args = None
    try:
        args = parser.parse_args(argv)
        if not hasattr(args, "func"):
            parser.print_help()
            return 0
        return args.func(args, Context(args))
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        raise
    except Exception as exc:
        if args is not None and args.debug:
            raise
        error_type, code = _classify_error(exc)
        json_mode = (
            getattr(args, "json", False)
            if args is not None
            else "--json" in (argv if argv is not None else sys.argv[1:])
        )
        Output(json_mode).error(exc, error_type, code)
        return code


def _classify_error(exc: Exception) -> tuple[str, int]:
    if isinstance(exc, ReplyIncompleteError):
        return "still_working", 4
    if isinstance(exc, ConnectError):
        if exc.status == 401:
            return "auth", 3
        return ("network" if exc.status == 0 else "gateway"), 1
    if isinstance(exc, httpx.TimeoutException):
        return "timeout", 1
    if isinstance(exc, httpx.ConnectError):
        return "network", 1
    if isinstance(exc, ValueError):
        return "invalid", 1
    return "error", 1
