import argparse
import importlib
import pkgutil
from typing import NoReturn

from groken.client import ConnectError

from . import __version__, commands
from .context import Context
from .output import Output


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


def main(argv: list[str] | None = None) -> int:
    parser = Parser(prog="gbot", description="Talk to your existing Grok Bot bots.")
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
    except Exception as exc:
        if args is not None and args.debug:
            raise
        Output().error(exc)
        return 3 if isinstance(exc, ConnectError) and exc.status == 401 else 1
