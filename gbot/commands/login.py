import argparse
import webbrowser

from gbot.context import Context
from groken import auth
from groken.client import ConnectError


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("login", help="Sign in to Grok Bot")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    login = auth.start_login()
    ctx.out.write({"login_url": login["login_url"]}, login["login_url"])
    if not args.no_browser:
        try:
            webbrowser.open(login["login_url"])
        except (OSError, webbrowser.Error) as exc:
            ctx.out.error(exc)
    tokens = auth.poll_for_tokens(
        login["uuid"], login["verifier"], timeout_s=args.timeout
    )
    if tokens is None:
        raise ConnectError(401, "login timed out")
    auth.save_tokens(tokens)
    ctx.out.write({"signed_in": True}, "Signed in.")
    return 0
