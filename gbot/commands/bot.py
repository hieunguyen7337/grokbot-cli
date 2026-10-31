"""Manage bots and their sidebar settings."""

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

from gbot.bots import resolve_bot
from gbot.context import Context
from gbot.service import bots, conversation
from gbot.service.models import Bot
from gbot.service.transport import ContextTransport

from .approvals import _confirm, _require_confirmation


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("bot", help="Create, edit and configure bots")
    actions = parser.add_subparsers(dest="bot_action", required=True)
    for action in (
        "new",
        "edit",
        "delete",
        "hide",
        "show",
        "notify",
        "drafting",
        "main",
        "info",
    ):
        command = actions.add_parser(action)
        command.add_argument("--json", action="store_true")
        command.add_argument("--yes", action="store_true")
        command.set_defaults(func=run)
        if action == "new":
            command.add_argument("name", metavar="NAME")
            command.add_argument("--description", default="")
            command.add_argument("--shape", default="blob", choices=bots.SHAPES)
            command.add_argument("--color", default="blue", choices=bots.COLORS)
            command.add_argument("--avatar", type=Path, metavar="FILE.png")
        elif action == "delete":
            command.add_argument("bot", nargs="+", metavar="BOT")
        else:
            command.add_argument(
                "bot", nargs="?" if action == "main" else None, metavar="BOT"
            )
            if action == "edit":
                command.add_argument("--name")
                command.add_argument("--title")
                description = command.add_mutually_exclusive_group()
                description.add_argument("--description")
                description.add_argument(
                    "--description-file", type=Path, metavar="FILE"
                )
            elif action in {"notify", "drafting"}:
                command.add_argument("value", choices=("on", "off"))


def _selected(ctx: Context, transport: ContextTransport, requested: str) -> Bot:
    bot_id, _ = resolve_bot(ctx, requested)
    for bot in conversation.roster(transport):
        if bot.id == bot_id:
            return bot
    raise ValueError("Bot disappeared from the roster; retry.")


def run(args: argparse.Namespace, ctx: Context) -> int:
    action = args.bot_action
    reading = action == "info" or (action == "main" and args.bot is None)
    if not reading:
        _require_confirmation(args.yes)
    transport = ContextTransport(ctx)
    if action == "main" and args.bot is None:
        main = bots.main_agent(transport)
        ctx.out.write({"main_agent_id": main}, main or "No main bot set.")
        return 0
    selected = []
    if action != "new":
        requested_bots = args.bot if action == "delete" else [args.bot]
        if not isinstance(requested_bots, list):
            raise ValueError("Select a bot.")
        for requested in requested_bots:
            if not isinstance(requested, str):
                raise TypeError("Select a bot.")
            selected.append(_selected(ctx, transport, requested))
    if action == "info":
        bot = selected[0]
        server = bots.server_bots(transport).get(bot.id)
        data = {
            "id": bot.id,
            "name": bot.name,
            "title": bot.title,
            "description": bot.description,
            "harness": server.harness if server else bot.raw.get("harness"),
            "owner": server.owner if server else bot.raw.get("viewerIsOwner", True),
            "hidden": bot.hidden,
            "notify": bot.raw.get("notifyOnUpdatesEnabled", True),
            "drafting_disabled": server.drafting_disabled
            if server
            else bot.raw.get("draftingDisabled", False),
            "voice": {
                "id": server.voice_id if server else bot.raw.get("voiceId"),
                "speed": server.voice_speed if server else bot.raw.get("voiceSpeed"),
                "language": server.voice_language
                if server
                else bot.raw.get("voiceLanguage"),
            },
            "main": bots.main_agent(transport) == bot.id,
        }
        ctx.out.write(data, "\n".join(f"{key}: {value}" for key, value in data.items()))
        return 0
    description = getattr(args, "description", None)
    if action == "edit" and args.description_file is not None:
        description = args.description_file.read_text(encoding="utf-8")
    png = None
    if action == "new" and args.avatar is not None:
        png = args.avatar.read_bytes()
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Avatar must be a PNG file.")
    preview = sys.stderr if ctx.out.json_mode else sys.stdout
    targets = ", ".join(f"{bot.name} ({bot.id})" for bot in selected)
    print(f"{action}: {targets or args.name}", file=preview)
    if action == "delete":
        print("Each bot's conversation history is removed.", file=preview)
    elif action == "edit":
        for key, value in (
            ("name", args.name),
            ("title", args.title),
            ("description", description),
        ):
            if value is not None:
                print(f"{key}: {value}", file=preview)
    elif action in {"notify", "drafting"}:
        print(args.value, file=preview)
    _confirm(args.yes, json_mode=ctx.out.json_mode)
    result: dict[str, object] = {"action": action}
    if action == "new":
        bot = bots.create(
            transport,
            args.name,
            description=description or "",
            shape=args.shape,
            color=args.color,
            png=png,
        )
        result.update(bot_id=bot.id, name=bot.name)
    elif action == "delete":
        ids = [bot.id for bot in selected]
        deleted = bots.delete(transport, ids)
        result.update(bot_ids=ids, **asdict(deleted))
        ctx.out.write(
            result,
            f"Delete completed. Refused: {len(deleted.refused_ids)}; failed: {len(deleted.failed_ids)}.",
        )
        return 1 if deleted.refused_ids or deleted.failed_ids else 0
    else:
        bot = selected[0]
        result["bot_id"] = bot.id
        if action == "edit":
            updated = bots.update(
                transport,
                bot,
                name=args.name,
                title=args.title,
                description=description,
            )
            result["bot"] = dict(updated.raw) if updated else None
        elif action in {"hide", "show"}:
            bots.set_hidden(transport, bot.id, action == "hide")
            result["hidden"] = action == "hide"
        elif action == "notify":
            bots.set_notify_on_updates(transport, bot.id, args.value == "on")
            result["notify"] = args.value == "on"
        elif action == "drafting":
            bots.set_drafting_disabled(transport, bot.id, args.value == "off")
            result["drafting_disabled"] = args.value == "off"
        elif action == "main":
            bots.set_main(transport, bot.id)
            result["main_agent_id"] = bot.id
    ctx.out.write(result, "Done.")
    return 0
