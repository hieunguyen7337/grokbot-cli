"""Account channels and per-bot Slack apps."""

import argparse
import sys
from dataclasses import asdict

from gbot.bots import resolve_bot
from gbot.commands.approvals import _confirm, _require_confirmation
from gbot.context import Context
from gbot.handoff import run_handoff
from gbot.output import terminal_safe
from gbot.service import channels as service
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("channels", help="Slack, texting and listeners")
    children = parser.add_subparsers(dest="channel", required=True)
    for name in ("slack", "sms", "listeners"):
        child = children.add_parser(name)
        child.add_argument("--yes", action="store_true")
        child.add_argument("--json", action="store_true")
        child.add_argument("--no-browser", action="store_true")
        actions = child.add_mutually_exclusive_group()
        if name == "slack":
            child.add_argument("bot", metavar="BOT")
            child.add_argument("--workspace", metavar="ID")
            for verb in ("connect", "install", "reinstall", "uninstall"):
                actions.add_argument("--" + verb, action="store_true")
        elif name == "sms":
            actions.add_argument("--link", action="store_true")
            actions.add_argument("--unlink", metavar="HANDLE")
        else:
            actions.add_argument("--connect", metavar="PLATFORM")
        child.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    mutation = any(
        getattr(args, name, False)
        for name in ("connect", "install", "reinstall", "uninstall", "link", "unlink")
    )
    if mutation:
        # Channels always require explicit --yes, including interactive shells.
        if not args.yes:
            raise ValueError("Re-run with --yes to confirm")
        _require_confirmation(args.yes)
        _confirm(args.yes, json_mode=args.json)
    if args.channel == "slack" and args.workspace and not args.install:
        raise ValueError("--workspace requires --install")
    transport = ContextTransport(ctx)
    if args.channel == "slack":
        bot_id, _ = resolve_bot(ctx, args.bot)
        state = service.slack_state(transport, bot_id)
        outcome, message = "", ""
        if mutation:
            if args.connect:
                result = service.start_slack_connect(transport, bot_id)
            elif args.install:
                result = service.install_slack(transport, bot_id, args.workspace)
            elif args.reinstall:
                result = service.reinstall_slack(transport, bot_id)
            else:
                result = service.uninstall_slack(transport, bot_id)
            outcome, url, message = result
            if url:
                handoff = run_handoff(
                    url,
                    service.slack_check(transport, bot_id, state),
                    open_browser=not args.no_browser,
                    err=sys.stderr,
                )
                if handoff.status == "cancelled":
                    return 130
                if isinstance(handoff.value, service.SlackState):
                    state = handoff.value
                elif handoff.status == "timeout":
                    message = "Timed out waiting for Slack. Reload to check again."
            else:
                state = service.slack_state(transport, bot_id)
        data = asdict(state)
        data.pop("authorize_url")
        if mutation:
            data.update(outcome=outcome, message=message)
        text = f"Slack: {state.status}\nWorkspace: {state.workspace_name or 'none'}\nWorkspaces: {len(state.workspaces)}"
        flags = (
            (state.needs_manifest_update, "The Slack app needs a manifest update."),
            (state.pending_reinstall_approval, "Waiting for reinstall approval."),
            (state.app_unreachable, "The Slack app is unreachable."),
            (state.removed_in_slack, "The app was removed in Slack."),
        )
        text += "".join("\n" + sentence for enabled, sentence in flags if enabled)
        if message:
            text += "\n" + message
        ctx.out.write(data, terminal_safe(text))
    elif args.channel == "sms":
        link = service.messaging_link(transport)
        if link.available:
            if args.link:
                link = service.issue_link_code(transport)
            elif args.unlink:
                service.unlink_phone(transport, args.unlink)
            phones = service.linked_phones(transport)
        else:
            phones = ()
        data = {**asdict(link), "phones": [asdict(p) for p in phones]}
        text = (
            f"Text your bots: {link.line_number or 'No line number'}"
            if link.available
            else link.unavailable_reason
        )
        text += "".join(
            f"\n{p.handle_id}: {p.address} · linked {p.linked_at_ms} · last seen {p.last_seen_at_ms}"
            for p in phones
        )
        if link.pending_code:
            code, expires, message, uri = link.pending_code
            text += f"\nCode: {code} (expires {expires})\n{message}\n{uri}"
        ctx.out.write(data, terminal_safe(text))
    else:
        message = ""
        if args.connect:
            url = service.listener_connect_url(transport, args.connect)
            handoff = run_handoff(
                url,
                service.listener_check(transport, args.connect),
                open_browser=not args.no_browser,
                err=sys.stderr,
            )
            if handoff.status == "cancelled":
                return 130
            if handoff.status == "timeout":
                message = service.CALLBACK_HINT
        integrations = service.listener_integrations(transport)
        text = "\n".join(
            f"{r.platform}: {r.state} · connected: {r.is_connected} · needed by {r.needed_by_count} automations"
            + (f" · {r.detail}" if r.detail else "")
            + "".join(f" · {s.get('kind')}: {s.get('scope')}" for s in r.scope_issues)
            for r in integrations
        )
        ctx.out.write(
            {"integrations": [asdict(r) for r in integrations], "message": message},
            terminal_safe(text + ("\n" + message if message else "")),
        )
    return 0
