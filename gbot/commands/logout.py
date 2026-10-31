import argparse

from gbot.context import Context
from groken import auth


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("logout", help="Remove the saved session")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    removed = auth.clear_tokens()
    ctx.out.write(
        {"removed": removed}, "Session removed." if removed else "No saved session."
    )
    return 0
