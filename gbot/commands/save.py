import argparse
from pathlib import Path

from gbot.bots import resolve_bot
from gbot.context import Context
from gbot.service import attachments, conversation
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "save", help="Save files attached to a transcript entry"
    )
    parser.add_argument("--bot", required=True)
    parser.add_argument("--session", metavar="ID")
    parser.add_argument("--out", type=Path, default=None, metavar="DIR")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("ref", metavar="REF")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    bot_id, _ = resolve_bot(ctx, args.bot)
    transport = ContextTransport(ctx)
    entries = []
    before = None
    while True:
        page = conversation.transcript(
            transport, bot_id, before_seq=before, limit=200, session_id=args.session
        )
        entries.extend(page.entries)
        if page.next_before_seq is None or page.next_before_seq == before:
            break
        before = page.next_before_seq
    exact = [entry for entry in entries if entry.id == args.ref]
    if not exact and len(args.ref) < 6:
        raise ValueError("REF prefixes must contain at least 6 characters.")
    matches = exact or [entry for entry in entries if entry.id.startswith(args.ref)]
    if not matches:
        raise ValueError(f"Unknown transcript REF: {args.ref}")
    if len(matches) != 1:
        raise ValueError(f"Ambiguous transcript REF: {args.ref}")
    files = attachments.entry_files(matches[0])
    if not files:
        raise ValueError("Entry has no files.")
    dest = args.out if args.out is not None else Path.home() / "Downloads"
    saved: list[str] = []
    links: list[str] = []
    lines: list[str] = []
    for file in files:
        if file.remote_url:
            links.append(file.remote_url)
            lines.append(f"link: {file.remote_url}")
        elif file.path:
            path = attachments.download(
                transport, bot_id, file.path, dest, name=file.name
            )
            saved.append(str(path))
            lines.append(str(path))
    ctx.out.write({"saved": saved, "links": links}, "\n".join(lines))
    return 0
