"""Manage catalog plugins and enter settings without echoed values."""

import argparse
import getpass
import sys
import warnings
from dataclasses import asdict

from gbot.bots import resolve_bot
from gbot.commands.approvals import _confirm, _require_confirmation
from gbot.context import Context
from gbot.service import plugins
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("plugins", help="Manage a bot's plugins")
    parser.add_argument("bot", metavar="BOT")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--add", metavar="ENTRY")
    actions.add_argument("--remove", metavar="PLUGIN")
    actions.add_argument("--set-var", nargs=2, metavar=("PLUGIN", "NAME"))
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def find_plugin(rows: list[plugins.Plugin], query: str) -> plugins.Plugin:
    matches = [
        p
        for p in rows
        if query.casefold() in {str(p.plugin_id), p.display_name.casefold()}
        and not p.is_bot_skills
    ]
    if len(matches) != 1:
        raise ValueError(
            "Choose a plugin: "
            + ", ".join(
                f"{p.display_name} ({p.plugin_id})"
                for p in matches or rows
                if not p.is_bot_skills
            )
        )
    return matches[0]


def needs_setup(plugin: plugins.Plugin) -> bool:
    return bool(plugins.variable_fields(plugin)) and not plugin.has_configured_variables


def plugin_text(plugin: plugins.Plugin) -> str:
    return " · ".join(
        part
        for part in (
            "Skills: " + ", ".join(plugin.skill_names) if plugin.skill_names else "",
            "Servers: " + ", ".join(plugin.server_names) if plugin.server_names else "",
            "needs setup" if needs_setup(plugin) else "",
        )
        if part
    )


def run(args: argparse.Namespace, ctx: Context) -> int:
    mutation = (
        args.add is not None or args.remove is not None or args.set_var is not None
    )
    if mutation:
        _require_confirmation(args.yes)
        _confirm(args.yes, json_mode=args.json)
    transport = ContextTransport(ctx)
    bot_id, _ = resolve_bot(ctx, args.bot)
    note = ""
    if args.add is not None:
        entry = plugins.find_entry(plugins.catalog(transport), args.add)
        rows = plugins.add_plugin(transport, bot_id, entry)
        added = next((p for p in rows if str(p.plugin_id) == entry.id), None)
        if (
            added
            and not added.has_configured_variables
            and plugins.variable_fields(added, entry)
        ):
            note = f"Fill in its settings with gbot plugins {args.bot} --set-var {added.plugin_id} NAME."
    elif args.remove is not None:
        selected = find_plugin(plugins.bot_plugins(transport, bot_id), args.remove)
        rows = plugins.remove_plugin(transport, bot_id, selected.plugin_id)
    elif args.set_var is not None:
        query, name = args.set_var
        selected = find_plugin(plugins.bot_plugins(transport, bot_id), query)
        value = ""
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                value = (
                    getpass.getpass(f"Value for {name} (hidden): ")
                    if sys.stdin.isatty()
                    else sys.stdin.readline().rstrip("\r\n")
                )
            plugins.set_variables(transport, bot_id, selected.plugin_id, {name: value})
        except getpass.GetPassWarning:
            raise ValueError(
                "This terminal cannot hide input; pipe the value on stdin instead."
            ) from None
        finally:
            value = ""
        ctx.out.write(
            {"plugin_id": selected.plugin_id, "saved": True}, "Saved plugin settings."
        )
        return 0
    else:
        rows = plugins.bot_plugins(transport, bot_id)
    visible = [p for p in rows if not p.is_bot_skills]
    ctx.out.write(
        [asdict(p) for p in visible],
        (
            "\n".join(f"{p.display_name}  {plugin_text(p)}" for p in visible)
            or "No plugins"
        )
        + (f"\n{note}" if note else ""),
    )
    return 0
