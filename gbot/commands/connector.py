"""Inspect or change one account connector."""

import argparse
import json
import sys
from collections.abc import Mapping
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
    parser.add_argument("--user-settings", action="store_true")
    parser.add_argument("--set-user-settings", metavar="JSON")
    parser.add_argument("--keep-disabled-tools", action="store_true")
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


def _no_constant(name: str) -> object:
    raise ValueError(f"{name} is not valid JSON.")


def run(args: argparse.Namespace, ctx: Context) -> int:
    settings_action = args.user_settings or args.set_user_settings is not None
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
        or args.set_user_settings is not None
    )
    if args.user_settings and args.set_user_settings is not None:
        raise ValueError("Use either --user-settings or --set-user-settings.")
    if args.keep_disabled_tools and args.set_user_settings is None:
        raise ValueError("Use --keep-disabled-tools with --set-user-settings.")
    if settings_action and (
        args.server
        or any(v is not None for v in mutations)
        or args.remove
        or args.sign_in
        or args.clear_always_allow
    ):
        raise ValueError("User MCP settings are account-wide and run by themselves.")
    if (args.account or args.reauth or args.no_browser) and not args.sign_in:
        raise ValueError("Use --account, --reauth and --no-browser with --sign-in.")
    if args.clear_always_allow and (
        args.server
        or any(v is not None for v in mutations)
        or args.remove
        or args.sign_in
    ):
        raise ValueError("Use --clear-always-allow by itself.")
    if not args.server and not args.clear_always_allow and not settings_action:
        raise ValueError("Specify SERVER or --clear-always-allow.")
    settings_payload: dict[str, object] | None = None
    if args.set_user_settings is not None:
        raw_settings = (
            sys.stdin.read()
            if args.set_user_settings == "-"
            else args.set_user_settings
        )
        try:
            decoded = json.loads(raw_settings, parse_constant=_no_constant)
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError("--set-user-settings requires a JSON object.") from error
        if not isinstance(decoded, Mapping):
            raise ValueError("--set-user-settings requires a JSON object.")
        settings_payload = dict(decoded)
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
    if args.user_settings:
        settings = service.user_mcp_settings(transport)
        ctx.out.write(
            {"settings": asdict(settings) if settings is not None else None},
            json.dumps(settings.raw, indent=2)
            if settings is not None
            else "No user MCP settings were returned.",
        )
        return 0
    if settings_payload is not None:
        _confirm(args.yes, json_mode=args.json)
        settings = service.set_user_mcp_settings(
            transport,
            settings_payload,
            keep_disabled_tools=args.keep_disabled_tools,
        )
        ctx.out.write(
            {"settings": asdict(settings) if settings is not None else None},
            "User MCP settings updated."
            if settings is not None
            else "User MCP settings were updated; the server returned no settings.",
        )
        return 0
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
