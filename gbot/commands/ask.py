import argparse
import time
from collections.abc import Callable
from pathlib import Path
from queue import Empty, SimpleQueue

from gbot.bots import resolve_bot
from gbot.commands.send import attachment_json, prompt_text, upload_files
from gbot.context import Context
from gbot.pending import discover, is_pending, render
from gbot.service.attachments import Attachment
from gbot.service.events import (
    BotChanged,
    BotOverlay,
    ConnectionChanged,
    EntryAdded,
    EntryChanged,
    Event,
)
from gbot.service.models import ConnectionStatus, Entry
from groken.client import ConnectError
from groken.gateway import AwaitingUserError, ReplyIncompleteError


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("ask", help="Ask a bot and wait for its reply")
    parser.add_argument("--bot")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--idle", type=float, default=45)
    parser.add_argument("--stream", action="store_true")
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
    manager = ctx.manager()
    streamed: list[str] = []

    def chunk(value: str) -> None:
        streamed.append(value)
        ctx.out.chunk(value)

    try:
        if files:
            reply = _ask_attached(args, ctx, bot_id, text, files, chunk)
            if args.stream and not ctx.out.json_mode:
                print()
                return 0
        elif args.stream:
            reply = manager.ask_stream(
                bot_id,
                text,
                args.timeout,
                args.idle,
                on_chunk=None if ctx.out.json_mode else chunk,
                on_entry=is_pending,
            )
            if not ctx.out.json_mode:
                print()
                return 0
        else:
            reply = manager.ask(
                bot_id, text, args.timeout, args.idle, on_entry=is_pending
            )
    except AwaitingUserError as exc:
        items = discover(ctx, bot_id)
        if ctx.out.json_mode:
            ctx.out.write(
                {
                    "bot": {"id": bot_id, "name": name},
                    "reply": exc.partial_reply,
                    "pending": [item.to_dict() for item in items],
                    **({"attachments": attachment_json(files)} if files else {}),
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
    ctx.out.write(
        {
            "bot": {"id": bot_id, "name": name},
            "reply": reply,
            **({"attachments": attachment_json(files)} if files else {}),
        },
        reply,
    )
    return 0


def _ask_attached(
    args: argparse.Namespace,
    ctx: Context,
    bot_id: str,
    text: str,
    files: list[Attachment],
    chunk: Callable[[str], None],
) -> str:
    service = ctx.service()
    hub = service.event_source()
    queue: SimpleQueue[Event] = SimpleQueue()
    deadline = time.monotonic() + args.timeout
    started = time.monotonic()
    entries: dict[str, Entry] = {}
    seen: set[str] = set()
    quiet = time.monotonic()
    busy = True
    settled = False

    def reply() -> str:
        return "\n".join(
            entry.text
            for entry in sorted(entries.values(), key=lambda e: e.seq)
            if entry.text
        )

    try:
        hub.follow(bot_id)
        hub.start(queue.put)
        # start() launches a thread; wait until the subscription is actually open.
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out connecting to the event stream.")
            try:
                event = queue.get(timeout=min(remaining, 0.5))
            except Empty:
                continue
            if isinstance(event, ConnectionChanged):
                if event.status == ConnectionStatus.SIGNED_OUT:
                    raise ConnectError(401, "not signed in")
                if event.status == ConnectionStatus.LIVE:
                    break
        seen.update(entry.id for entry in service.transcript(bot_id, limit=200).entries)
        while not queue.empty():
            queue.get_nowait()
        result = service.send(bot_id, text, attachments=files)
        quiet = time.monotonic()
        if not result.accepted:
            raise ValueError("Prompt was not accepted.")
        while True:
            now = time.monotonic()
            if (
                reply()
                and not busy
                and settled
                and not any(e.streaming for e in entries.values())
                and now - quiet >= 2
            ):
                return reply()
            if now >= deadline or now - quiet >= args.idle:
                raise ReplyIncompleteError(bot_id, now - started)
            try:
                event = queue.get(
                    timeout=min(
                        0.5, deadline - now, max(0.001, args.idle - (now - quiet))
                    )
                )
            except Empty:
                continue
            if (
                isinstance(event, ConnectionChanged)
                and event.status == ConnectionStatus.SIGNED_OUT
            ):
                raise ConnectError(401, "not signed in")
            if isinstance(event, (EntryAdded, EntryChanged)):
                entry = event.entry
                if (
                    entry.bot_id != bot_id
                    or entry.session_id is not None
                    or entry.id in seen
                ):
                    continue
                if result.last_seq is not None and entry.seq <= result.last_seq:
                    continue
                quiet = time.monotonic()
                if is_pending(dict(entry.raw)):
                    raise AwaitingUserError(bot_id, dict(entry.raw), reply())
                if (
                    entry.is_user
                    or entry.kind not in ("message", "send-message")
                    or entry.card_type is not None
                ):
                    continue
                previous = entries.get(entry.id)
                entries[entry.id] = entry
                if args.stream and not ctx.out.json_mode:
                    old = previous.text if previous else ""
                    chunk(entry.text.removeprefix(old))
            elif isinstance(event, BotChanged) and event.bot.id == bot_id:
                busy = event.bot.busy
                settled = True
                if event.bot.awaiting:
                    raise AwaitingUserError(bot_id, {}, reply())
            elif isinstance(event, BotOverlay) and event.bot_id == bot_id:
                running = event.fields.get(
                    "isRunningTurn", event.fields.get("isRunning")
                )
                if isinstance(running, bool):
                    busy = running or event.fields.get("isComposingMessage") is True
                    settled = True
    finally:
        hub.close()
        ctx.close()
