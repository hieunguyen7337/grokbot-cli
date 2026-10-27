import argparse
import json
from datetime import UTC, datetime
from threading import Event

import httpx

from gbot.bots import record, resolve_bot
from gbot.context import Context
from groken.client import ConnectError


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("tail", help="Read a bot transcript")
    parser.add_argument("--bot")
    parser.add_argument("-n", type=int, default=20)
    parser.add_argument("--since")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--follow", action="store_true")
    parser.set_defaults(func=run)


def render(entry: dict[str, object], full: bool) -> str:
    content = str(record(entry.get("message")).get("content", entry.get("content", "")))
    content = " ".join(content.splitlines())
    if not full:
        content = content[:160]
    stamp = entry.get("timestampMs")
    time = (
        datetime.fromtimestamp(stamp / 1000, tz=UTC).astimezone().strftime("%H:%M:%S")
        if isinstance(stamp, (int, float))
        else "--:--:--"
    )
    return f"[{time}] {entry.get('kind', 'unknown')}: {content}"


def run(args: argparse.Namespace, ctx: Context) -> int:
    if args.n < 0:
        raise ValueError("-n must be non-negative")
    bot_id, _ = resolve_bot(ctx, args.bot)
    manager = ctx.manager()
    entries = manager.transcript_tail(bot_id)
    seen = {str(entry["id"]) for entry in entries if "id" in entry}
    if args.since is not None:
        index = next(
            (i for i, entry in enumerate(entries) if entry.get("id") == args.since),
            None,
        )
        if index is None:
            raise ValueError(f"Transcript entry not found: {args.since}")
        entries = entries[index + 1 :]
    entries = entries[-args.n :] if args.n else []
    if not args.follow:
        ctx.out.write(entries, "\n".join(render(entry, args.full) for entry in entries))
        return 0

    def emit(entry: dict[str, object]) -> None:
        entry_id = entry.get("id")
        if not entry or (entry_id is not None and str(entry_id) in seen):
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
    delay = 0.25
    reconnecting = False
    try:
        while True:
            try:
                if reconnecting:
                    # Entries appended while the stream was down.
                    for entry in manager.transcript_tail(bot_id):
                        emit(entry)
                reconnecting = True
                for event in manager.events(["transcript"]):
                    # Gateway frames are {"event", "data": {"channel", "payload"}}.
                    envelope = record(event.get("data"))
                    payload = record(envelope.get("payload"))
                    if (
                        envelope.get("channel") != "transcript"
                        or payload.get("type") != "appended"
                        or payload.get("agentId") != bot_id
                    ):
                        continue
                    emit(record(payload.get("entry")))
                    delay = 0.25
            except (ConnectError, httpx.HTTPError) as exc:
                if isinstance(exc, ConnectError) and exc.status == 401:
                    raise
                ctx.out.error(exc)
            # Reconnection is the only timed wait; transcript updates use SSE.
            Event().wait(delay)
            delay = min(delay * 2, 5.0)
    except KeyboardInterrupt:
        return 0
