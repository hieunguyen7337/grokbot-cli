"""Bot files, user-store files and the bot's library."""

import argparse
import json
import time
from collections.abc import Callable
from dataclasses import asdict, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from gbot.bots import resolve_bot
from gbot.commands.approvals import _confirm
from gbot.context import Context
from gbot.output import terminal_safe
from gbot.service import bot_files, library
from gbot.service.errors import ServiceError, refusal
from gbot.service.transport import ContextTransport

T = TypeVar("T")


def register(subparsers: argparse._SubParsersAction) -> None:
    files = subparsers.add_parser("files", help="Manage a bot's files")
    files.add_argument("bot", metavar="BOT")
    actions = files.add_mutually_exclusive_group()
    actions.add_argument("--upload", metavar="PATH")
    actions.add_argument("--delete", metavar="NAME")
    actions.add_argument("--delete-user-file", metavar="PATH")
    files.add_argument("--yes", action="store_true")
    files.add_argument("--json", action="store_true")
    files.set_defaults(func=run_files)
    docs = subparsers.add_parser("library", help="Manage a bot's library documents")
    docs.add_argument("bot", metavar="BOT")
    actions = docs.add_mutually_exclusive_group()
    actions.add_argument("--pin", metavar="KEY")
    actions.add_argument("--unpin", metavar="KEY")
    actions.add_argument("--merge-pins", metavar="FILE")
    docs.add_argument("--yes", action="store_true")
    docs.add_argument("--json", action="store_true")
    docs.set_defaults(func=run_library)


def _size(count: int) -> str:
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{count} B"


def _when(ms: int) -> str:
    if ms <= 0:
        return "unknown"
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d %H:%M")


def _read(work: Callable[[], T], empty: T) -> tuple[T, str]:
    """A read that may be refused: the refusal sentence replaces the part and the command still succeeds."""
    try:
        return work(), ""
    except Exception as error:
        refused = refusal(error)
        if refused is None:
            raise
        return empty, refused.message


def _change(work: Callable[[], T]) -> T:
    try:
        return work()
    except Exception as error:
        refused = refusal(error)
        if refused is None:
            raise
        raise ServiceError(refused.message) from None


def run_files(args: argparse.Namespace, ctx: Context) -> int:
    transport = ContextTransport(ctx)
    bot_id, bot_name = resolve_bot(ctx, args.bot)
    if args.upload:
        path = Path(args.upload)
        if not path.is_file():
            raise ValueError(f"Not a file: {path}")
        _confirm(args.yes, json_mode=ctx.out.json_mode)
        file = _change(lambda: bot_files.upload_file(transport, bot_id, path))
        ctx.out.write(
            {"uploaded": asdict(file)},
            f"Uploaded {terminal_safe(file.name)} ({_size(file.size_bytes)}).",
        )
        return 0
    if args.delete:
        _confirm(args.yes, json_mode=ctx.out.json_mode)
        _change(lambda: bot_files.delete_agent_file(transport, bot_id, args.delete))
        ctx.out.write(
            {"deleted": args.delete}, f"Deleted {terminal_safe(args.delete)}."
        )
        return 0
    if args.delete_user_file:
        _confirm(args.yes, json_mode=ctx.out.json_mode)
        _change(
            lambda: bot_files.delete_user_store_file(
                transport, bot_id, args.delete_user_file
            )
        )
        ctx.out.write(
            {"deleted_user_file": args.delete_user_file},
            f"Deleted {terminal_safe(args.delete_user_file)}.",
        )
        return 0
    listing, listing_notice = _read(
        lambda: bot_files.agent_files(transport, bot_id),
        bot_files.AgentFiles((), 0, False),
    )
    store, store_notice = _read(
        lambda: bot_files.user_store_files(transport, bot_id), ()
    )
    lines = [listing_notice] if listing_notice else []
    if not listing_notice:
        lines.append(
            f"{len(listing.files)} files, {_size(listing.total_bytes)}; "
            + ("you can edit." if listing.can_edit else "read only.")
            if listing.files
            else "No bot files."
        )
    lines.extend(
        f"{terminal_safe(f.name)}  {_size(f.size_bytes)}  {_when(f.updated_at_ms)}"
        for f in listing.files
    )
    lines.append(
        store_notice or ("User-store files:" if store else "No user-store files.")
    )
    lines.extend(
        f"{terminal_safe(f.path)}  {_size(f.size_bytes)}  {_when(f.updated_at_ms)}"
        for f in store
    )
    ctx.out.write(
        {
            "bot": bot_name,
            "files": [asdict(f) for f in listing.files],
            "total_bytes": listing.total_bytes,
            "can_edit": listing.can_edit,
            "user_store_files": [asdict(f) for f in store],
            "notices": [n for n in (listing_notice, store_notice) if n],
        },
        "\n".join(lines),
    )
    return 0


def _pin_from_json(row: object) -> library.Pin:
    if not isinstance(row, dict):
        raise TypeError("Each pin must be an object.")
    names = {f.name for f in fields(library.Pin)}
    pin = library.Pin(**{k: v for k, v in row.items() if k in names})
    if pin.kind not in library.KINDS:
        raise ValueError("Each pin needs a kind of page, media, doc or app.")
    return pin


def run_library(args: argparse.Namespace, ctx: Context) -> int:
    transport = ContextTransport(ctx)
    bot_id, bot_name = resolve_bot(ctx, args.bot)
    key = args.pin or args.unpin
    if key:
        _confirm(args.yes, json_mode=ctx.out.json_mode)
        pin = library.Pin(
            "doc", key=key, pinned_at_ms=int(time.time() * 1000) if args.pin else 0
        )
        pins = _change(lambda: library.set_pin(transport, bot_id, pin, bool(args.pin)))
        ctx.out.write(
            {"pinned": bool(args.pin), "pins": [asdict(p) for p in pins]},
            ("Pinned " if args.pin else "Unpinned ")
            + terminal_safe(key)
            + f". {len(pins)} pins.",
        )
        return 0
    if args.merge_pins:
        try:
            data = json.loads(Path(args.merge_pins).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError(f"Could not read pins from {args.merge_pins}.") from error
        if isinstance(data, dict):
            data = data.get("pins")
        if not isinstance(data, list):
            raise ValueError("The file must hold a JSON list of pins.")
        wanted = [_pin_from_json(row) for row in data]
        _confirm(args.yes, json_mode=ctx.out.json_mode)
        pins = _change(lambda: library.merge_pins(transport, bot_id, wanted))
        ctx.out.write(
            {"merged": len(wanted), "pins": [asdict(p) for p in pins]},
            f"Merged {len(wanted)} pins. {len(pins)} pins now.",
        )
        return 0
    docs, docs_notice = _read(lambda: library.library_docs(transport, bot_id), ())
    pins, pins_notice = _read(lambda: library.library_pins(transport, bot_id), ())
    pinned = {p.key for p in pins if p.kind == "doc"}
    lines = [docs_notice or ("" if docs else "No library documents.")]
    lines.extend(
        f"{'* ' if d.key in pinned else '  '}{terminal_safe(d.title or d.external_id)}"
        f"  {terminal_safe(d.provider)}  {terminal_safe(d.kind)}  {_when(d.last_touched_at_ms)}"
        f"  key {terminal_safe(d.key)}"
        for d in docs
    )
    lines.append(pins_notice or ("Pins:" if pins else "No pins."))
    lines.extend(
        f"{p.kind}  {terminal_safe(p.key or p.name or p.canvas_id or p.document_id)}"
        for p in pins
    )
    ctx.out.write(
        {
            "bot": bot_name,
            "docs": [{**asdict(d), "pinned": d.key in pinned} for d in docs],
            "pins": [asdict(p) for p in pins],
            "notices": [n for n in (docs_notice, pins_notice) if n],
        },
        "\n".join(line for line in lines if line),
    )
    return 0
