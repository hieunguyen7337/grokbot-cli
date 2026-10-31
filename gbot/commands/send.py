import argparse
import sys
from pathlib import Path

from gbot.bots import resolve_bot
from gbot.context import Context
from gbot.service import attachments, conversation
from gbot.service.transport import ContextTransport
from groken.client import ConnectError


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("send", help="Send a prompt without waiting")
    parser.add_argument("--bot")
    parser.add_argument("--session", metavar="ID")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--attach", action="append", type=Path, default=[], metavar="PATH"
    )
    parser.add_argument("text", nargs="*")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    text = prompt_text(args)
    bot_id, name = resolve_bot(ctx, args.bot)
    files = upload_files(args, ctx, bot_id)
    result = conversation.send(
        ContextTransport(ctx), bot_id, text, session_id=args.session, attachments=files
    )
    ctx.out.write(
        {
            "accepted": result.accepted,
            "bot": {"id": bot_id, "name": name},
            "last_seq": result.last_seq,
            **({"attachments": attachment_json(files)} if files else {}),
        },
        f"Sent to {name}.",
    )
    return 0


def attachment_json(files: list[attachments.Attachment]) -> list[dict[str, str]]:
    return [{"name": file.name, "path": file.path} for file in files]


def prompt_text(args: argparse.Namespace) -> str:
    text = sys.stdin.read() if args.text == ["-"] else " ".join(args.text)
    if not text.strip() and not args.attach:
        raise ValueError("Prompt must not be empty.")
    return text


def upload_files(
    args: argparse.Namespace, ctx: Context, bot_id: str
) -> list[attachments.Attachment]:
    files = []
    for path in args.attach:

        def progress(sent: int, total: int, filename: str = path.name) -> None:
            print(f"Uploading {filename}: {sent}/{total} bytes", file=sys.stderr)

        try:
            files.append(
                attachments.upload(
                    ContextTransport(ctx),
                    bot_id,
                    path,
                    progress=progress
                    if sys.stderr.isatty() and not ctx.out.json_mode
                    else None,
                )
            )
        except ConnectError as exc:
            raise ValueError(str(exc)) from exc
    return files
