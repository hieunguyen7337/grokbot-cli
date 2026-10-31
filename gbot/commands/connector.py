"""Inspect or change one account connector."""

import argparse
import sys
from dataclasses import asdict

from gbot.commands.approvals import _confirm, _require_confirmation
from gbot.context import Context
from gbot.handoff import run_handoff
from gbot.service import connectors as service
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("connector", help="Manage one connector")
    parser.add_argument("server", metavar="SERVER", nargs="?")
    for option in (
        "disable-tool",
        "enable-tool",
        "permission",
        "reads",
        "writes",
        "instructions",
        "remove-account",
        "account",
    ):
        parser.add_argument(f"--{option}")
    parser.add_argument("--rename-account", nargs=2, metavar=("OLD", "NEW"))
    parser.add_argument("--shared-spaces", choices=("on", "off"))
    for option in (
        "remove",
        "sign-in",
        "reauth",
        "no-browser",
        "clear-always-allow",
        "yes",
        "json",
    ):
        parser.add_argument(f"--{option}", action="store_true")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    mutations = (
        args.disable_tool,
        args.enable_tool,
        args.permission,
        args.reads,
        args.writes,
        args.instructions,
        args.rename_account,
        args.remove_account,
        args.shared_spaces,
    )
    mutation = (
        any(v is not None for v in mutations)
        or args.remove
        or args.sign_in
        or args.clear_always_allow
    )
    if (args.account or args.reauth or args.no_browser) and not args.sign_in:
        raise ValueError("Use --account, --reauth and --no-browser with --sign-in.")
    if args.clear_always_allow and (
        args.server
        or any(v is not None for v in mutations)
        or args.remove
        or args.sign_in
    ):
        raise ValueError("Use --clear-always-allow by itself.")
    if not args.server and not args.clear_always_allow:
        raise ValueError("Specify SERVER or --clear-always-allow.")
    if mutation:
        _require_confirmation(args.yes)
    permission = None
    if args.permission is not None:
        name, separator, label = args.permission.partition("=")
        if not separator or not name:
            raise ValueError("Use --permission TOOL=LEVEL.")
        permission = (name, service.normalize(label))
    for label in (args.reads, args.writes):
        if label is not None:
            service.normalize(label)
    transport = ContextTransport(ctx)
    if args.clear_always_allow:
        _confirm(args.yes, json_mode=args.json)
        count = service.clear_always_allow(transport)
        ctx.out.write({"cleared_count": count}, f"Forgot {count} always-allow answers.")
        return 0
    server = service.find(service.servers(transport), args.server)
    if args.remove and server.is_team:
        raise ValueError("Your team admin manages this connector.")
    if mutation:
        _confirm(args.yes, json_mode=args.json)
    for name, disabled in ((args.disable_tool, True), (args.enable_tool, False)):
        if name is not None:
            service.set_tool_disabled(transport, server.id, name, disabled)
    if permission is not None or args.reads is not None or args.writes is not None:
        service.set_permission(
            transport, server.id, tool=permission, reads=args.reads, writes=args.writes
        )
    if args.instructions is not None:
        service.set_instructions(
            transport,
            server.id,
            sys.stdin.read() if args.instructions == "-" else args.instructions,
        )
    if args.rename_account is not None:
        service.rename_account(transport, server.id, *args.rename_account)
    if args.remove_account is not None:
        service.remove_account(transport, server.id, args.remove_account)
    if args.shared_spaces is not None:
        service.set_shared_space(transport, server.id, args.shared_spaces == "on")
    if args.remove:
        service.remove_server(transport, server.id)
        ctx.out.write({"removed": True}, "Connector removed.")
        return 0
    if args.sign_in:
        outcome, url, sentence = service.start_sign_in(
            transport, server.id, account_key=args.account, reauth=args.reauth
        )
        if outcome == "started" and url:
            result = run_handoff(
                url,
                service.sign_in_check(transport, server),
                err=sys.stderr,
                open_browser=not args.no_browser,
            )
            if result.status == "cancelled":
                return 130
            sentence = (
                service.TIMEOUT if result.status == "timeout" else "Sign-in completed."
            )
            if isinstance(result.value, str):
                sentence = result.value
        ctx.out.write({"outcome": outcome, "message": sentence}, sentence)
        return 0
    # Re-read after mutations so detail reflects the server's current state.
    if mutation:
        server = service.find(service.servers(transport), server.id)
    tools = service.tools(transport, server.id)
    policy = service.policy(transport, server.id)
    shared = server.id in service.shared_spaces(transport)
    data = {
        **asdict(server),
        "status_sentence": service.status_sentence(server),
        "tools": [asdict(t) for t in tools],
        "policy": asdict(policy),
        "shared_spaces": shared,
    }
    lines = [
        server.plugin_name or server.name,
        service.status_sentence(server),
        f"Account: {server.account_key or '-'}",
        f"Transport: {server.transport or '-'}",
        f"Read default: {policy.reads or 'auto_review'}",
        f"Write default: {policy.writes or 'auto_review'}",
        f"Group chats: {'allowed' if shared else 'not allowed'}",
        f"Instructions: {server.custom_instructions}",
    ]
    lines.extend(
        f"{t.name}: {'read' if t.is_read_only else 'write'} · {t.permission}"
        + (" · disabled" if t.is_disabled else "")
        for t in tools
    )
    ctx.out.write(data, "\n".join(lines))
    return 0
