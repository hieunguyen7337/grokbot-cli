import argparse
import json
import time
from datetime import UTC, datetime
from queue import SimpleQueue

from gbot.commands.tail import next_event, render
from gbot.context import Context
from gbot.output import terminal_safe
from gbot.service.errors import SignedOutError
from gbot.service.events import (
    BotChanged,
    BotOverlay,
    ConnectionChanged,
    EntryAdded,
    Event,
    RosterReplaced,
)
from gbot.service.models import Bot, ConnectionStatus
from groken.client import ConnectError


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("watch", help="Watch bot state changes")
    parser.add_argument("--bot")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def state(bot: Bot) -> str:
    return (
        "awaiting"
        if bot.awaiting
        else "working"
        if bot.busy
        else "new"
        if bot.unread
        else "idle"
    )


def summary(bot: Bot) -> str:
    return terminal_safe(" ".join(bot.preview[:60].splitlines()))


def select(bots: list[Bot], selector: str) -> Bot:
    for matches in (
        [bot for bot in bots if bot.id == selector],
        [bot for bot in bots if bot.name == selector],
        [bot for bot in bots if bot.name.casefold() == selector.casefold()],
    ):
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise ValueError(f"Ambiguous bot: {selector}")
    raise ValueError(f"Unknown bot: {selector}")


def run(args: argparse.Namespace, ctx: Context) -> int:
    try:
        service = ctx.service()
        bots = service.roster() if args.once or args.bot else []
        selected = select(bots, args.bot).id if args.bot else None
        if args.once:
            rows = [
                {
                    "id": bot.id,
                    "name": bot.name,
                    "state": state(bot),
                    "summary": summary(bot),
                    "last_activity_at": bot.last_activity_at,
                }
                for bot in bots
                if selected is None or bot.id == selected
            ]
            name_width = max([4, *(len(str(row["name"])) for row in rows)])
            state_width = max([5, *(len(str(row["state"])) for row in rows)])
            lines = [f"{'NAME':<{name_width}}  {'STATE':<{state_width}}  SUMMARY"]
            lines.extend(
                f"{row['name']!s:<{name_width}}  {row['state']!s:<{state_width}}  {row['summary']}"
                for row in rows
            )
            ctx.out.write(rows, "\n".join(lines))
            return 2 if any(row["state"] == "awaiting" for row in rows) else 0

        hub = service.event_source()
        queue: SimpleQueue[Event] = SimpleQueue()
        if selected is not None:
            hub.follow(selected)
        hub.start(queue.put)
        roster: dict[str, Bot] = {}
        shown: dict[str, tuple[str, str]] = {}
        seen_entries: set[tuple[str, str | None, str]] = set()

        def emit_bot(bot: Bot) -> None:
            if selected is not None and bot.id != selected:
                return
            value = (state(bot), summary(bot))
            if shown.get(bot.id) == value:
                return
            shown[bot.id] = value
            now = int(time.time() * 1000)
            obj = {
                "type": "state",
                "id": bot.id,
                "name": bot.name,
                "state": value[0],
                "summary": value[1],
                "at": now,
            }
            stamp = datetime.fromtimestamp(now / 1000, tz=UTC).astimezone()
            text = f"{stamp.strftime('%H:%M:%S')} {bot.name} {value[0]}  {value[1]}"
            print(
                json.dumps(obj, ensure_ascii=False)
                if ctx.out.json_mode
                else terminal_safe(text),
                flush=True,
            )

        while True:
            event = next_event(queue)
            if isinstance(event, RosterReplaced):
                roster = {bot.id: bot for bot in event.bots}
                shown = {key: value for key, value in shown.items() if key in roster}
                for bot in event.bots:
                    emit_bot(bot)
            elif isinstance(event, BotChanged):
                roster[event.bot.id] = event.bot
                emit_bot(event.bot)
            elif isinstance(event, BotOverlay) and event.bot_id in roster:
                bot = roster[event.bot_id].with_overlay(event.fields)
                roster[bot.id] = bot
                emit_bot(bot)
            elif isinstance(event, EntryAdded) and selected == event.entry.bot_id:
                entry = event.entry
                if entry.key not in seen_entries:
                    seen_entries.add(entry.key)
                    obj = {
                        "type": "entry",
                        "id": entry.bot_id,
                        "entry": dict(entry.raw),
                    }
                    print(
                        json.dumps(obj, ensure_ascii=False)
                        if ctx.out.json_mode
                        else terminal_safe(render(dict(entry.raw), False)),
                        flush=True,
                    )
            elif isinstance(event, ConnectionChanged):
                if event.status == ConnectionStatus.SIGNED_OUT:
                    raise ConnectError(401, "not signed in")
                obj = {
                    "type": "connection",
                    "status": event.status.value,
                    "detail": event.detail,
                }
                print(
                    json.dumps(obj, ensure_ascii=False)
                    if ctx.out.json_mode
                    else terminal_safe(
                        f"connection {event.status.value} {event.detail}".rstrip()
                    ),
                    flush=True,
                )
    except KeyboardInterrupt:
        return 0
    except SignedOutError as exc:
        raise ConnectError(401, "not signed in") from exc
    finally:
        ctx.close()
