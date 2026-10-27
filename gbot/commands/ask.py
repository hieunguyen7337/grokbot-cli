import argparse
import inspect
from collections.abc import Callable
from typing import cast

from gbot.bots import resolve_bot
from gbot.context import Context, prompt
from gbot.pending import discover, is_pending, render
from groken.gateway import AwaitingUserError, GatewayManager


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("ask", help="Ask a bot and wait for its reply")
    parser.add_argument("--bot")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--idle", type=float, default=45)
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("text", nargs="+")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    text = prompt(args)
    bot_id, name = resolve_bot(ctx, args.bot)
    manager = cast(GatewayManager, ctx.manager())
    method = manager.ask_stream if args.stream else manager.ask
    # Older injected/relay managers retain the original ask interface.
    parameters = inspect.signature(method).parameters
    options: dict[str, Callable[[dict[str, object]], bool]] = {}
    if "on_entry" in parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()
    ):
        options["on_entry"] = is_pending
    streamed: list[str] = []

    def chunk(value: str) -> None:
        streamed.append(value)
        ctx.out.chunk(value)

    try:
        if args.stream:
            reply = manager.ask_stream(
                bot_id,
                text,
                args.timeout,
                args.idle,
                on_chunk=None if ctx.out.json_mode else chunk,
                **options,
            )
            if not ctx.out.json_mode:
                print()
                return 0
        else:
            reply = manager.ask(bot_id, text, args.timeout, args.idle, **options)
    except AwaitingUserError as exc:
        items = discover(ctx, bot_id)
        if ctx.out.json_mode:
            ctx.out.write(
                {
                    "bot": {"id": bot_id, "name": name},
                    "reply": exc.partial_reply,
                    "pending": [item.to_dict() for item in items],
                },
                "",
            )
        else:
            if streamed:
                print()
            elif exc.partial_reply:
                print(exc.partial_reply)
            print(render(items))
        return 2
    ctx.out.write({"bot": {"id": bot_id, "name": name}, "reply": reply}, reply)
    return 0
