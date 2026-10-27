import argparse

from gbot import config
from gbot.bots import record, resolve_bot
from gbot.context import Context
from groken import auth
from groken.client import detect_client_version


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "status", help="Show session and selected computer status"
    )
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    tokens = auth.load_tokens()
    signed_in = bool(tokens and tokens.get("accessToken"))
    default = config.default_bot()
    result: dict[str, object] = {
        "signed_in": signed_in,
        "client_version": detect_client_version(),
        "default_bot": default,
    }
    lines = [
        "Signed in." if signed_in else "Not signed in. Run: gbot login",
        f"Client version: {result['client_version']}",
        f"Default bot: {default['name']} ({default['id']})"
        if default
        else "No bot selected.",
    ]
    if signed_in and default:
        bot_id, name = resolve_bot(ctx, None)
        result["default_bot"] = {"id": bot_id, "name": name}
        lines[2] = f"Default bot: {name} ({bot_id})"
        manager = ctx.manager()
        computer = record(manager.command("getForeverBoxStatus", {"id": bot_id}))
        host = record(manager.command("getHostStatus"))
        secrets = record(manager.command("getBoxSecretsStatus"))
        mcp = record(manager.command("listBoxMcpServers", {"serverIdentifiers": []}))
        rows = mcp.get("servers", [])
        servers = (
            [
                {
                    "id": record(row).get("serverIdentifier"),
                    "status": record(row).get("status"),
                    "tool_count": record(row).get("toolCount"),
                }
                for row in rows
            ]
            if isinstance(rows, list)
            else []
        )
        result.update(
            {
                "bot": {"id": bot_id, "name": name, "state": computer.get("state")},
                "host": {
                    "version": host.get("hostVersion"),
                    "latest_version": host.get("latestHostVersion"),
                    "update_available": host.get("hostUpdateAvailable") is True,
                    "busy": host.get("isBusy") is True,
                },
                "secrets": {"is_applied": secrets.get("isApplied") is True},
                "mcp": {"servers": servers},
            }
        )
        lines.extend(
            [
                f"Computer: {computer.get('state')}",
                f"Host: {host.get('hostVersion')}; update available={host.get('hostUpdateAvailable') is True}; busy={host.get('isBusy') is True}",
                f"Secrets: applied={secrets.get('isApplied') is True}",
            ]
        )
        lines.extend(
            f"MCP: {server['id']} {server['status']} tools={server['tool_count']}"
            for server in servers
        )
    ctx.out.write(result, "\n".join(lines))
    return 0 if signed_in else 3
