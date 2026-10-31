"""Teams app installation and Microsoft account linking."""

import argparse
import sys
from dataclasses import asdict

from gbot.bots import resolve_bot
from gbot.context import Context
from gbot.handoff import run_handoff
from gbot.service import teams
from gbot.service.handoff import HandoffResult
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("teams", help="Manage Microsoft Teams")
    parser.add_argument("bot", metavar="BOT", nargs="?")
    parser.add_argument("--account", action="store_true")
    actions = parser.add_mutually_exclusive_group()
    for name in ("connect", "install", "reinstall", "uninstall", "link-account"):
        actions.add_argument("--" + name, action="store_true")
    for name in ("add-to-team", "disconnect", "unlink-account"):
        actions.add_argument("--" + name)
    parser.add_argument("--admin", action="store_true")
    parser.add_argument("--team", action="append", nargs="+", default=[])
    parser.add_argument("--no-personal", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def _handoff_result(ctx: Context, result: HandoffResult) -> int | None:
    if result.status == "done":
        return None
    ctx.out.write(
        {"status": result.status}, "Teams browser step " + result.status + "."
    )
    return 130 if result.status == "cancelled" else 1


def run(args: argparse.Namespace, ctx: Context) -> int:
    mutation = any(
        (
            args.connect,
            args.install,
            args.reinstall,
            args.uninstall,
            args.add_to_team,
            args.disconnect,
            args.link_account,
            args.unlink_account,
        )
    )
    if mutation and not args.yes:
        raise ValueError("Re-run with --yes to confirm")
    account = args.account or args.link_account or args.unlink_account
    bot_action = any(
        (
            args.connect,
            args.install,
            args.reinstall,
            args.uninstall,
            args.add_to_team,
            args.disconnect,
        )
    )
    if account and (args.bot or bot_action):
        raise ValueError("Account linking does not take BOT or bot actions.")
    if args.admin and not args.connect:
        raise ValueError("Use --admin with --connect.")
    if (args.team or args.no_personal) and not args.install:
        raise ValueError("Use --team and --no-personal with --install.")
    transport = ContextTransport(ctx)
    if account:
        if args.unlink_account:
            unlinked = teams.unlink_account(transport, args.unlink_account)
            ctx.out.write(
                {"unlinked": unlinked},
                "Account unlinked." if unlinked else "Account was not linked.",
            )
            return 0
        if args.link_account:
            before = teams.account_links(transport)
            url = teams.start_account_link(transport)
            result = run_handoff(
                url,
                teams.account_link_check(transport, before),
                err=sys.stderr,
                open_browser=not args.no_browser,
                timeout_s=120,
            )
            code = _handoff_result(ctx, result)
            if code is not None:
                return code
        links = teams.account_links(transport)
        ctx.out.write(
            [asdict(link) for link in links],
            "\n".join(
                f"{link.tenant_id}: linked at {link.linked_at_ms}" for link in links
            )
            or "No Teams account linked.",
        )
        return 0
    if not args.bot:
        raise ValueError("Specify BOT or --account.")
    bot_id, _ = resolve_bot(ctx, args.bot)
    if args.connect:
        url, admin_url, nonce = teams.start_connect(transport, bot_id, admin=args.admin)
        result = run_handoff(
            admin_url if args.admin else url,
            teams.connect_check(transport, bot_id, nonce),
            err=sys.stderr,
            open_browser=not args.no_browser,
        )
        code = _handoff_result(ctx, result)
        if code is not None:
            return code
        state = result.value
        if isinstance(state, teams.TeamsState):
            suggestion = (
                "\nInstall with: gbot teams " + args.bot + " --install --yes"
                if state.consent_result
                not in {"access_denied", "grant_conflict", "other"}
                and not state.failure_reason
                else ""
            )
            ctx.out.write(
                {**asdict(state), "messages": state.messages},
                "\n".join(state.messages) + suggestion,
            )
            return 0
    if args.disconnect:
        revoked, state, remaining = teams.disconnect(transport, bot_id, args.disconnect)
        ctx.out.write(
            {
                "revoked": revoked,
                "state": state,
                "still_installed_agent_ids": remaining,
            },
            teams.sentence(state)
            + "\nBots still installed: "
            + (", ".join(remaining) or "none"),
        )
        return 0
    if args.add_to_team:
        row = teams.add_to_team(transport, bot_id, args.add_to_team)
        failure = str(row.get("failureReason") or "")
        ctx.out.write(
            row, teams.sentence(failure) if failure else "Teams app added to team."
        )
        return 0
    if args.install:
        state = teams.install(
            transport,
            bot_id,
            team_ids=[team for group in args.team for team in group],
            personal=not args.no_personal,
        )
    elif args.reinstall:
        state = teams.reinstall(transport, bot_id)
    elif args.uninstall:
        state = teams.uninstall(transport, bot_id)
    else:
        state = teams.install_state(transport, bot_id)
    ctx.out.write(
        {**asdict(state), "messages": state.messages},
        "\n".join(
            (
                "State: " + state.state,
                "Tenant: " + (state.tenant_name or state.tenant_id or "none"),
                "Installed teams: "
                + (
                    ", ".join(
                        str(team.get("displayName") or team.get("teamId"))
                        for team in state.installed_teams
                    )
                    or "none"
                ),
                *state.messages,
            )
        ),
    )
    return 0
