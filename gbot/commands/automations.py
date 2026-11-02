"""List and manage bot automations."""

import argparse
import sys
from dataclasses import asdict
from threading import Event

from gbot.bots import resolve_bot
from gbot.commands.approvals import _confirm, _require_confirmation
from gbot.context import Context
from gbot.service import automations as service
from gbot.service import conversation
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "automations", help="Manage scheduled and triggered prompts"
    )
    parser.add_argument("bot", metavar="BOT", nargs="?")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--show", metavar="ID")
    actions.add_argument("--routines", action="store_true")
    actions.add_argument("--routine-on", metavar="AUTOMATION_ID")
    actions.add_argument("--routine-off", metavar="AUTOMATION_ID")
    actions.add_argument("--new", action="store_true")
    for flag in ("edit", "on", "delete", "run"):
        actions.add_argument(f"--{flag}", metavar="ID")
    parser.add_argument("--off", nargs="?", const="", metavar="ID")
    for flag in ("name", "prompt", "schedule"):
        parser.add_argument(f"--{flag}")
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--time-zone")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def _row(item: service.Automation) -> dict[str, object]:
    return {
        **item.raw,
        "bot_id": item.bot_id,
        "server_id": item.server_id,
        "allowed": sorted(item.allowed) if item.allowed is not None else None,
    }


def run(args: argparse.Namespace, ctx: Context) -> int:
    routine_action = args.routines or args.routine_on or args.routine_off
    mutation = args.new or any(
        v is not None
        for v in (
            args.edit,
            args.on,
            args.off,
            args.delete,
            args.run,
            args.routine_on,
            args.routine_off,
        )
    )
    if (
        args.off is not None
        and not (args.new and args.off == "")
        and (
            not args.off
            or any((args.new, args.edit, args.on, args.delete, args.run, args.show))
        )
    ):
        raise ValueError("Use --off ID, or --new --off.")
    if any(v is not None for v in (args.name, args.prompt, args.schedule)) and not (
        args.new or args.edit
    ):
        raise ValueError("Use --name, --prompt and --schedule with --new or --edit.")
    if args.no_wait and not args.run:
        raise ValueError("Use --no-wait with --run.")
    if args.time_zone and not routine_action:
        raise ValueError(
            "Use --time-zone with --routines, --routine-on or --routine-off."
        )
    if mutation:
        _require_confirmation(args.yes)
    if (mutation or args.show or args.routines) and not args.bot:
        raise ValueError("Specify BOT for this action.")
    if args.new and any(v is None for v in (args.name, args.prompt, args.schedule)):
        raise ValueError("--new requires --name, --prompt and --schedule.")
    prompt = sys.stdin.read() if args.prompt == "-" else args.prompt
    transport = ContextTransport(ctx)
    bot_id = resolve_bot(ctx, args.bot)[0] if args.bot else None
    bots = conversation.roster(transport)
    bot = next((b for b in bots if b.id == bot_id), None)
    if bot is None and bot_id:
        raise ValueError("Bot not found.")
    if routine_action:
        assert bot is not None
        listed = service.list_agent_routines(
            transport, bot.id, time_zone=args.time_zone
        )
        if not listed.available:
            data = {
                "supported": False,
                "routines": [],
                "routine_policy": None,
                "raw": dict(listed.raw),
            }
            ctx.out.write(data, "Agent routines are unavailable for this account.")
            return 2
        if args.routine_on or args.routine_off:
            automation_id = args.routine_on or args.routine_off
            matches = [
                item for item in listed.routines if item.automation_id == automation_id
            ]
            if len(matches) != 1:
                raise ValueError("Routine not found; use its exact automation ID.")
            _confirm(args.yes, json_mode=args.json)
            routine = service.set_agent_routine_enabled(
                transport,
                bot.id,
                automation_id,
                bool(args.routine_on),
                time_zone=args.time_zone,
            )
            ctx.out.write(
                {"routine": asdict(routine) if routine else None},
                "Routine enabled." if args.routine_on else "Routine disabled.",
            )
            return 0
        ctx.out.write(
            {
                "supported": True,
                "routines": [asdict(item) for item in listed.routines],
                "routine_policy": dict(listed.routine_policy)
                if listed.routine_policy is not None
                else None,
                "raw": dict(listed.raw),
            },
            "\n".join(
                f"{item.name} · {'on' if item.is_enabled else 'off'} · {item.schedule}"
                for item in listed.routines
            )
            or "No agent routines.",
        )
        return 0
    target = args.show or args.edit or args.on or args.off or args.delete or args.run
    item = service.get(transport, bot, target) if bot and target else None
    if mutation:
        _confirm(args.yes, json_mode=args.json)
        assert bot is not None
        if args.new:
            rows = service.create(
                transport,
                bot,
                name=args.name,
                prompt=prompt,
                schedule=args.schedule,
                enabled=args.off is None,
            )
        else:
            assert item is not None
            if args.edit:
                rows = service.update(
                    transport,
                    bot,
                    item,
                    name=args.name,
                    prompt=prompt,
                    schedule=args.schedule,
                )
            elif args.on or args.off:
                rows = service.set_enabled(transport, bot, item, bool(args.on))
            elif args.delete:
                rows = service.delete(transport, bot, item)
            else:
                service.run_now(transport, bot, item)
                new_run = (
                    None
                    if args.no_wait
                    else service.wait_for_run(transport, bot, item, cancel=Event())
                )
                status = (
                    "requested"
                    if args.no_wait
                    else new_run.status
                    if new_run
                    else "timeout"
                )
                ctx.out.write(
                    {
                        "id": item.id,
                        "status": status,
                        "run": asdict(new_run) if new_run else None,
                    },
                    f"{item.name}: {status}",
                )
                return 0 if args.no_wait or new_run else 1
        ctx.out.write(
            {"automations": [_row(a) for a in rows]},
            "Automation updated." if not args.delete else "Automation deleted.",
        )
        return 0
    if item:
        text = (
            f"{item.name} · {'on' if item.is_enabled else 'off'}\nTrigger: {service.describe_trigger(item.trigger)}\nNext run: {item.next_run_at_ms}\nLast run: {item.last_run_at_ms}\n{item.prompt}\n"
            + "\n".join(
                f"{r.id}: {r.status} ({r.started_at_ms})" for r in item.runs[:5]
            )
        )
        ctx.out.write(_row(item), text)
    else:
        rows = (
            service.list_for_bot(transport, bot)
            if bot
            else service.list_for_account(transport, bots)
        )
        names = {b.id: b.name for b in bots}
        ctx.out.write(
            [_row(a) for a in rows],
            "\n".join(
                f"{names.get(a.bot_id, a.bot_id)} · {a.name} · {'on' if a.is_enabled else 'off'} · {service.describe_trigger(a.trigger)} · next {a.next_run_at_ms}"
                for a in rows
            )
            or "No automations.",
        )
    return 0
