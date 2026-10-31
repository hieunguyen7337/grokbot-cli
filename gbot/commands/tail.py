import argparse
import json
from datetime import UTC, datetime
from queue import Empty, SimpleQueue

from gbot.bots import record, resolve_bot
from gbot.context import Context
from gbot.pending import describe
from gbot.service import conversation
from gbot.service.errors import SignedOutError
from gbot.service.events import ConnectionChanged, EntryAdded, Event
from gbot.service.models import ConnectionStatus
from gbot.service.transport import ContextTransport
from groken.client import ConnectError


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("tail", help="Read a bot transcript")
    parser.add_argument("--bot")
    parser.add_argument("-n", type=int, default=20)
    parser.add_argument("--since")
    parser.add_argument("--after", type=int)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--follow", action="store_true")
    parser.set_defaults(func=run)


def render(entry: dict[str, object], full: bool) -> str:
    message = record(entry.get("message"))
    kind = message.get("type")
    if entry.get("kind") == "send-message" and kind and kind != "text":
        content = describe(entry)
        prefix = ""
    else:
        content = str(message.get("content", entry.get("content", "")))
        prefix = f"{entry.get('kind', 'unknown')}: "
    content = " ".join(content.splitlines())
    if not full:
        content = content[:160]
    stamp = entry.get("timestampMs")
    time = (
        datetime.fromtimestamp(stamp / 1000, tz=UTC).astimezone().strftime("%H:%M:%S")
        if isinstance(stamp, (int, float))
        else "--:--:--"
    )
    return f"[{time}] {prefix}{content}"


def next_event(queue: SimpleQueue[Event]) -> Event:
    # An unbounded get ignores Ctrl+C on Windows; a bounded one lets KeyboardInterrupt through.
    while True:
        try:
            return queue.get(timeout=0.5)
        except Empty:
            continue


def run(args: argparse.Namespace, ctx: Context) -> int:
    try:
        return _run(args, ctx)
    except SignedOutError as exc:
        raise ConnectError(401, "not signed in") from exc
    finally:
        if args.follow:
            ctx.close()


def _run(args: argparse.Namespace, ctx: Context) -> int:
    if args.n < 0:
        raise ValueError("-n must be non-negative")
    bot_id, _ = resolve_bot(ctx, args.bot)
    entries = (
        [
            dict(entry.raw)
            for entry in ctx.service().transcript(bot_id, limit=100).entries
        ]
        if args.follow
        else [
            dict(entry.raw)
            for entry in conversation.transcript(
                ContextTransport(ctx), bot_id, limit=100
            ).entries
        ]
    )
    seen = {str(entry["id"]) for entry in entries if "id" in entry}
    if args.since is not None:
        index = next(
            (i for i, entry in enumerate(entries) if entry.get("id") == args.since),
            None,
        )
        if index is None:
            raise ValueError(f"Transcript entry not found: {args.since}")
        entries = entries[index + 1 :]

    def after(entry: dict[str, object]) -> bool:
        seq = entry.get("seq")
        return args.after is None or (type(seq) is int and seq > args.after)

    entries = [entry for entry in entries if after(entry)]
    entries = entries[-args.n :] if args.n else []
    if not args.follow:
        ctx.out.write(entries, "\n".join(render(entry, args.full) for entry in entries))
        return 0

    def emit(entry: dict[str, object]) -> None:
        entry_id = entry.get("id")
        if (
            not entry
            or not after(entry)
            or (entry_id is not None and str(entry_id) in seen)
        ):
            return
        if entry_id is not None:
            seen.add(str(entry_id))
        # One compact object per line, so `--follow --json` is JSON Lines.
        print(
            json.dumps(entry, ensure_ascii=False)
            if ctx.out.json_mode
            else render(entry, args.full),
            flush=True,
        )

    seen.difference_update(str(entry["id"]) for entry in entries if "id" in entry)
    for entry in entries:
        emit(entry)
    try:
        hub = ctx.service().event_source()
        queue: SimpleQueue[Event] = SimpleQueue()
        hub.follow(bot_id)
        hub.start(queue.put)
        last_connection: tuple[ConnectionStatus, str] | None = None
        while True:
            event = next_event(queue)
            if isinstance(event, EntryAdded):
                if event.entry.bot_id == bot_id and event.entry.session_id is None:
                    emit(dict(event.entry.raw))
            elif isinstance(event, ConnectionChanged):
                if event.status == ConnectionStatus.SIGNED_OUT:
                    raise ConnectError(401, "not signed in")
                current = (event.status, event.detail)
                if current != last_connection and event.detail:
                    ctx.out.error(RuntimeError(event.detail))
                last_connection = current
    except KeyboardInterrupt:
        return 0
