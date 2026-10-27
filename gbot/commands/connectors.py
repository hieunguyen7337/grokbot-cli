import argparse

from gbot.bots import record
from gbot.context import Context
from groken.errors import explain_error


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "connectors", help="Show computer connectors (read-only)"
    )
    parser.add_argument("--tools", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def records(value: object) -> list[dict[str, object]]:
    return (
        [record(row) for row in value if isinstance(row, dict)]
        if isinstance(value, list)
        else []
    )


def aliases(server: dict[str, object]) -> set[str]:
    return {
        value
        for key in ("id", "serverIdentifier", "rowServerIdentifier", "name")
        if isinstance(value := server.get(key), str) and value
    }


def needs_sign_in(server: dict[str, object]) -> bool:
    kind = record(server.get("statusDetail")).get("kind")
    return (
        server.get("pendingSignIn") is True
        or server.get("status") in ("needsAuth", "needsGrant")
        or kind in ("authentication_required", "grant_required", "sign_in_pending")
    )


def merge_servers(
    state: object, box: object, plugins: object
) -> list[dict[str, object]]:
    servers = [dict(row) for row in records(record(state).get("servers"))]
    for server in servers:
        server["needs_sign_in"] = needs_sign_in(server)
    for row in records(record(box).get("servers")):
        matches = [server for server in servers if aliases(server) & aliases(row)]
        if matches:
            for server in matches:
                server.update(
                    {key: value for key, value in row.items() if value is not None}
                )
        else:
            servers.append(dict(row))
    for plugin in records(plugins):
        names = plugin.get("mcpServerNames")
        for name in names if isinstance(names, list) else []:
            if not isinstance(name, str):
                continue
            matches = [server for server in servers if name in aliases(server)]
            if not matches:
                matches = [{"name": name}]
                servers.extend(matches)
            for server in matches:
                server["enabled"] = plugin.get("isEnabled")
        for server in servers:
            if server.get("pluginId") is not None and server.get(
                "pluginId"
            ) == plugin.get("pluginId"):
                server["enabled"] = plugin.get("isEnabled")
    result = []
    for server in servers:
        status = server.get("status")
        needs_auth = server.get("needs_sign_in") is True or needs_sign_in(server)
        result.append(
            {
                "name": server.get("name"),
                "id": server.get("id")
                or server.get("rowServerIdentifier")
                or server.get("serverIdentifier"),
                "status": status,
                "auth": "needs sign-in"
                if needs_auth
                else ("connected" if status == "connected" else None),
                "tool_count": server.get("toolCount"),
                "enabled": server.get("enabled"),
            }
        )
    return result


def display(value: object) -> str:
    return "-" if value is None else str(value)


def run(args: argparse.Namespace, ctx: Context) -> int:
    manager = ctx.manager()
    servers = merge_servers(
        manager.command("getMcpState"),
        manager.command("listBoxMcpServers", {"serverIdentifiers": []}),
        manager.command("getEffectiveMcpPlugins"),
    )
    lines = []
    for server in servers:
        if args.tools:
            server["tools"] = []
            if isinstance(server["id"], str):
                try:
                    server["tools"] = [
                        {"name": tool.get("name")}
                        for tool in records(
                            manager.command(
                                "listMcpServerTools", {"serverId": server["id"]}
                            )
                        )
                    ]
                except Exception as exc:  # noqa: BLE001 - isolate each server failure
                    server["error"] = " ".join(
                        explain_error(exc, cli="gbot").splitlines()
                    )
            else:
                server["error"] = "Cannot list tools: missing server id"
        line = "  ".join(
            display(server[key]) for key in ("name", "id", "status", "auth")
        )
        line += f"  tools={display(server['tool_count'])}  enabled={display(server['enabled'])}"
        if server["auth"] == "needs sign-in":
            line += " — connect it in the Grok Bot app"
        if "error" in server:
            line += f"  error: {server['error']}"
        lines.append(line)
        lines.extend(
            f"  {display(tool.get('name'))}" for tool in records(server.get("tools"))
        )
    ctx.out.write(servers, "\n".join(lines) if lines else "No connectors.")
    return 0
