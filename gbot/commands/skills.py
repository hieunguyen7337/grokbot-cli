"""List, maintain and import bot skills."""

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

from gbot.bots import resolve_bot
from gbot.commands.approvals import _confirm, _require_confirmation
from gbot.context import Context
from gbot.service import workflows as service
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("skills", help="Read and manage bot skills")
    parser.add_argument("bot", metavar="BOT", nargs="?")
    action = parser.add_mutually_exclusive_group()
    for flag in ("catalog", "new"):
        action.add_argument(f"--{flag}", action="store_true")
    for flag in (
        "show",
        "edit",
        "delete",
        "run",
        "import-file",
        "import-url",
        "install",
    ):
        action.add_argument(f"--{flag}")
    for flag in ("name", "description", "body", "schedule", "search"):
        parser.add_argument(f"--{flag}")
    schedule = parser.add_mutually_exclusive_group()
    for flag in ("unschedule", "pause", "resume"):
        schedule.add_argument(f"--{flag}", action="store_true")
    for flag in ("all", "yes", "json"):
        parser.add_argument(f"--{flag}", action="store_true")
    parser.set_defaults(func=run)


def _body(path: str) -> str:
    return sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")


def run(args: argparse.Namespace, ctx: Context) -> int:
    mutation = bool(
        args.new
        or args.edit
        or args.delete
        or args.run
        or args.import_file
        or args.import_url
        or args.install
    )
    if args.catalog and args.bot:
        raise ValueError("Use --catalog without BOT.")
    if not args.catalog and not args.bot:
        raise ValueError("Specify BOT or --catalog.")
    if args.search is not None and not args.catalog:
        raise ValueError("--search requires --catalog.")
    if any(
        value is not None for value in (args.description, args.body, args.schedule)
    ) and not (args.new or args.edit):
        raise ValueError(
            "--description, --body and --schedule require --new or --edit."
        )
    if args.name is not None and not (
        args.new or args.edit or args.import_file or args.import_url
    ):
        raise ValueError("--name requires --new, --edit or an import.")
    if (args.unschedule or args.pause or args.resume) and not args.edit:
        raise ValueError("--unschedule, --pause and --resume require --edit.")
    if args.unschedule and args.schedule is not None:
        raise ValueError("Use --schedule or --unschedule, not both.")
    if args.edit and not (
        any(
            value is not None
            for value in (args.name, args.description, args.body, args.schedule)
        )
        or args.unschedule
        or args.pause
        or args.resume
    ):
        raise ValueError(
            "Nothing to change; give --name, --description, --body, --schedule,"
            " --unschedule, --pause or --resume."
        )
    if args.all and (mutation or args.show or args.catalog):
        raise ValueError("--all is only for listing a bot's skills.")
    if mutation:
        _require_confirmation(args.yes)
        _confirm(args.yes, json_mode=args.json)
    transport = ContextTransport(ctx)
    if args.catalog:
        entries = service.catalog(transport)
        search = (args.search or "").casefold()
        entries = [
            row
            for row in entries
            if search in f"{row.name} {row.publisher} {row.description}".casefold()
        ]
        ctx.out.write(
            [
                {key: value for key, value in asdict(row).items() if key != "install"}
                for row in entries
            ],
            "\n".join(
                f"{row.id}  {row.name} · {row.publisher} · {row.description[:100]}"
                for row in entries
            )
            or "No catalog skills",
        )
        return 0
    bot_id, _ = resolve_bot(ctx, args.bot)
    result: object
    if args.new:
        if args.name is None or args.description is None or args.body is None:
            raise ValueError("--new requires --name, --description and --body.")
        rows = service.create(
            transport,
            bot_id,
            name=args.name,
            description=args.description,
            body=_body(args.body),
            schedule=args.schedule,
        )
    elif args.import_file or args.import_url or args.install:
        if args.import_file:
            added, rows = service.import_text(
                transport, bot_id, _body(args.import_file), args.name
            )
        elif args.import_url:
            added, rows = service.import_url(
                transport, bot_id, args.import_url, args.name
            )
        else:
            entry = next(
                (row for row in service.catalog(transport) if row.id == args.install),
                None,
            )
            if entry is None:
                raise ValueError("Unknown catalog skill; use --catalog.")
            added, rows = service.install(transport, bot_id, entry)
        ctx.out.write(
            {"added_count": added, "workflow_count": len(rows)},
            f"Workflows: {len(rows) - added} → {len(rows)} ({added:+d})",
        )
        return 0
    else:
        rows = service.skills(transport, bot_id)
        query = args.show or args.edit or args.delete or args.run
        if query:
            skill = service.find(rows, query)
            if args.show:
                ctx.out.write(
                    asdict(skill), f"{skill.name}\n{skill.description}\n\n{skill.body}"
                )
                return 0
            if args.delete:
                rows = service.delete(transport, bot_id, skill)
            elif args.run:
                service.run_now(transport, bot_id, skill)
                ctx.out.write(
                    {"id": skill.id, "started": True}, f"Run requested: {skill.name}"
                )
                return 0
            else:
                changes: dict[str, object] = {}
                for field in ("name", "description", "schedule"):
                    if getattr(args, field) is not None:
                        changes[field] = getattr(args, field)
                if args.body is not None:
                    changes["body"] = _body(args.body)
                if args.unschedule:
                    changes["schedule"] = None
                if args.pause or args.resume:
                    changes["schedule_enabled"] = args.resume
                rows = service.update(transport, bot_id, skill, **changes)  # type: ignore[arg-type]
    # Managed skills number in the hundreds on a live bot, so they show only on request.
    if not args.all:
        rows = [row for row in rows if row.editable or row.schedule]
    result = [asdict(row) for row in rows]
    ctx.out.write(
        result,
        "\n".join(
            f"{row.name} · {row.source} · {row.schedule or 'Unscheduled'}"
            + (" (paused)" if row.schedule and not row.schedule_enabled else "")
            for row in rows
        )
        or "No skills",
    )
    return 0
