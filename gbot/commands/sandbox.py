"""Cloud computer state, recreate and upgrade schedule, and user runtime settings."""

import argparse
import sys
from collections.abc import Callable
from dataclasses import asdict
from typing import TypeVar

from gbot.bots import resolve_bot
from gbot.commands.approvals import _confirm, _require_confirmation
from gbot.context import Context
from gbot.service import conversation
from gbot.service import sandbox as service
from gbot.service.errors import refusal
from gbot.service.transport import ContextTransport
from groken.client import ConnectError

T = TypeVar("T")


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("sandbox", help="Manage the cloud computer")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--recreate", action="store_true")
    actions.add_argument("--force-recreate", action="store_true")
    actions.add_argument("--schedule-upgrade", metavar="HH:MM")
    actions.add_argument("--reschedule-upgrade", metavar="HH:MM")
    actions.add_argument("--cancel-upgrade", action="store_true")
    parser.add_argument("--discard-data", action="store_true")
    parser.add_argument("--acknowledge-schedule", action="store_true")
    parser.add_argument("--timezone", metavar="TZ")
    parser.add_argument("--recurring", action="store_true")
    parser.add_argument("--dismiss-outcome", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run_sandbox)

    settings = subparsers.add_parser("settings", help="Show or change runtime settings")
    changes = settings.add_mutually_exclusive_group()
    changes.add_argument("--pin", metavar="BOT")
    changes.add_argument("--unpin", metavar="BOT")
    changes.add_argument("--auto-review", choices=("on", "off"))
    settings.add_argument("--yes", action="store_true")
    settings.add_argument("--json", action="store_true")
    settings.set_defaults(func=run_settings)


def _refused(call: Callable[[], T]) -> T:
    try:
        return call()
    except ConnectError as error:
        found = refusal(error)
        if found is None:
            raise
        raise ValueError(found.message) from None


def _confirm_change(yes: bool, *, typed: bool, json_mode: bool) -> None:
    if not typed:
        _confirm(yes, json_mode=json_mode)
        return
    # Discarding data and forcing a recreate need the word itself, not just a yes.
    _require_confirmation(yes)
    if yes:
        return
    prompt = "Type recreate to confirm: "
    if json_mode:
        print(prompt, end="", file=sys.stderr, flush=True)
    if input("" if json_mode else prompt).strip() != "recreate":
        raise ValueError("Cancelled.")


def _check_sandbox_flags(args: argparse.Namespace) -> None:
    scheduling = (
        args.schedule_upgrade is not None or args.reschedule_upgrade is not None
    )
    if args.discard_data and not args.recreate:
        raise ValueError("Use --discard-data with --recreate.")
    if args.acknowledge_schedule and not args.recreate:
        raise ValueError("Use --acknowledge-schedule with --recreate.")
    if (args.timezone is not None or args.recurring) and not scheduling:
        raise ValueError(
            "Use --timezone and --recurring with --schedule-upgrade or --reschedule-upgrade."
        )
    if args.dismiss_outcome and not args.cancel_upgrade:
        raise ValueError("Use --dismiss-outcome with --cancel-upgrade.")


def run_sandbox(args: argparse.Namespace, ctx: Context) -> int:
    _check_sandbox_flags(args)
    transport = ContextTransport(ctx)
    if args.recreate or args.force_recreate:
        return _recreate(args, ctx, transport)
    if args.schedule_upgrade is not None or args.reschedule_upgrade is not None:
        return _schedule(args, ctx, transport)
    if args.cancel_upgrade:
        return _cancel(args, ctx, transport)
    return _show(ctx, transport)


def _show(ctx: Context, transport: ContextTransport) -> int:
    value = service.overview(transport)
    run = value.run
    ctx.out.write(
        {
            "state": run.state,
            "image_tag": run.image_tag,
            "image_update_available": run.image_update_available,
            "egress_tunnel_ownership": run.egress_tunnel_ownership,
            "upgrade_schedule": asdict(value.schedule) if value.schedule else None,
            "notice": value.notice,
        },
        "\n".join(
            [f"{label}: {shown}" for label, shown in service.fields(value)]
            + ([value.notice] if value.notice else [])
        ),
    )
    return 0


def _recreate(
    args: argparse.Namespace, ctx: Context, transport: ContextTransport
) -> int:
    _confirm_change(
        args.yes,
        typed=args.force_recreate or args.discard_data,
        json_mode=args.json,
    )
    if args.force_recreate:
        result = _refused(lambda: service.force_recreate(transport))
    else:
        result = _refused(
            lambda: service.recreate(
                transport,
                preserve_data=not args.discard_data,
                acknowledge_terminal_upgrade_schedule=args.acknowledge_schedule,
            )
        )
    ctx.out.write(
        {
            "started": result.started,
            "reason": result.reason,
            "operation_id": result.operation_id,
        },
        "\n".join(
            [
                f"Started: {'yes' if result.started else 'no'}",
                f"Reason: {result.reason or 'none'}",
                f"Operation: {result.operation_id or 'none'}",
            ]
        ),
    )
    return 0 if result.started else 1


def _schedule(
    args: argparse.Namespace, ctx: Context, transport: ContextTransport
) -> int:
    reschedule = args.reschedule_upgrade is not None
    local_time = (
        args.reschedule_upgrade if reschedule else args.schedule_upgrade
    ) or ""
    timezone = args.timezone or "UTC"
    service.check_schedule(timezone, local_time)
    _confirm_change(args.yes, typed=False, json_mode=args.json)
    change = service.reschedule_upgrade if reschedule else service.schedule_upgrade
    schedule = _refused(lambda: change(transport, timezone, local_time, args.recurring))
    ctx.out.write(
        asdict(schedule),
        "\n".join(
            f"{label}: {shown}" for label, shown in service.schedule_fields(schedule)
        ),
    )
    return 0


def _cancel(args: argparse.Namespace, ctx: Context, transport: ContextTransport) -> int:
    _confirm_change(args.yes, typed=False, json_mode=args.json)
    schedule = _refused(
        lambda: service.cancel_upgrade(
            transport, dismiss_terminal_outcome=args.dismiss_outcome
        )
    )
    ctx.out.write(
        asdict(schedule) if schedule else None,
        "\n".join(
            f"{label}: {shown}" for label, shown in service.schedule_fields(schedule)
        ),
    )
    return 0


def run_settings(args: argparse.Namespace, ctx: Context) -> int:
    transport = ContextTransport(ctx)
    current = _refused(lambda: service.runtime_settings(transport))
    names = {bot.id: bot.name for bot in conversation.roster(transport)}
    pinned_ids = list(current.pinned_agent_ids)
    if args.auto_review is not None:
        enable = args.auto_review == "on"
        if enable != current.auto_review_enabled:
            _confirm_change(args.yes, typed=False, json_mode=args.json)
            current = _refused(
                lambda: service.update_runtime_settings(
                    transport, current, auto_review_enabled=enable
                )
            )
    elif args.pin is not None or args.unpin is not None:
        value = args.pin if args.pin is not None else args.unpin
        bot_id = value if value in pinned_ids else resolve_bot(ctx, value)[0]
        pinned = bot_id in pinned_ids
        if args.pin is not None and not pinned:
            ids = [*pinned_ids, bot_id]
        elif args.unpin is not None and pinned:
            ids = [item for item in pinned_ids if item != bot_id]
        else:
            ids = None
        if ids is not None:
            _confirm_change(args.yes, typed=False, json_mode=args.json)
            current = _refused(
                lambda: service.update_runtime_settings(
                    transport, current, pinned_agent_ids=ids
                )
            )
    main = current.main_agent_id
    ctx.out.write(
        {
            "pinned_bots": [
                {"id": bot_id, "name": names.get(bot_id, bot_id)}
                for bot_id in current.pinned_agent_ids
            ],
            "auto_review_enabled": current.auto_review_enabled,
            "has_seen_onboarding": current.has_seen_onboarding,
            "main_bot": {"id": main, "name": names.get(main, main)} if main else None,
            "email_provider": current.email_provider,
            "updated_at_ms": current.updated_at_ms,
        },
        "\n".join(
            f"{label}: {shown}"
            for label, shown in service.settings_fields(current, names)
        ),
    )
    return 0
