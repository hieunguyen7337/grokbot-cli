import argparse
import sys
from collections.abc import Callable

from gbot.bots import record
from gbot.context import Context
from groken.client import ConnectError
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


def needs_sign_in(status: object, gateway: dict[str, object]) -> bool:
    kind = record(gateway.get("statusDetail")).get("kind")
    return status in ("needsAuth", "needsGrant") or kind in (
        "authentication_required",
        "grant_required",
        "sign_in_pending",
    )


def display(value: object) -> str:
    return "-" if value is None or value == "" else str(value)


def merge_servers(
    backend: object, state: object, box: object, plugins: object
) -> tuple[list[dict[str, object]], list[str], dict[str, dict[str, object]]]:
    by_id: dict[str, dict[str, dict[str, object]]] = {}
    for source, value in (
        ("backend", backend),
        ("getMcpState", state),
        ("listBoxMcpServers", box),
    ):
        for server in records(record(value).get("servers")):
            identifier = server.get("serverIdentifier")
            if isinstance(identifier, str) and identifier:
                by_id.setdefault(identifier, {})[source] = server

    plugin_rows = records(plugins)
    matched_plugins: set[str] = set()
    rows: list[dict[str, object]] = []
    gateway_by_id: dict[str, dict[str, object]] = {}
    for identifier, sources in by_id.items():
        account = sources.get("backend", {})
        gateway = sources.get("getMcpState", {})
        box_server = sources.get("listBoxMcpServers", {})
        gateway_by_id[identifier] = gateway
        plugin_id = gateway.get("pluginId")
        plugin = next(
            (
                p
                for p in plugin_rows
                if isinstance(plugin_id, str)
                and plugin_id
                and p.get("pluginId") == plugin_id
            ),
            None,
        )
        if plugin is not None:
            matched_plugins.add(str(plugin_id))
        status = (
            account.get("status") or gateway.get("status") or box_server.get("status")
        )
        tools = account.get("tools")
        enabled = plugin.get("isEnabled") if plugin is not None else None
        served_by = (
            account.get("servedBy")
            or gateway.get("servedBy")
            or box_server.get("servedBy")
        )
        row: dict[str, object] = {
            "name": gateway.get("name")
            or gateway.get("pluginDisplayName")
            or identifier.removeprefix("user-"),
            "server_identifier": identifier,
            "account": account.get("accountLabel") or "-",
            "status": status,
            "auth": "needs sign-in"
            if needs_sign_in(status, gateway)
            else "connected"
            if status == "connected"
            else None,
            "tool_count": len(tools)
            if isinstance(tools, list)
            else gateway.get("toolCount", box_server.get("toolCount")),
            "plugin": "on" if enabled is True else "off" if enabled is False else "-",
            "served_by": {
                "MCP_SERVED_BY_GROK": "grok",
                "MCP_SERVED_BY_CURSOR": "cursor",
            }.get(str(served_by), "-"),
            "sources": [
                *sources,
                *(["getEffectiveMcpPlugins"] if plugin is not None else []),
            ],
        }
        rows.append(row)
    rows.sort(
        key=lambda row: (str(row["name"]).casefold(), str(row["account"]).casefold())
    )
    unmatched = [
        str(p.get("displayName") or p.get("name"))
        for p in plugin_rows
        if p.get("pluginId") not in matched_plugins
        and (p.get("displayName") or p.get("name"))
    ]
    return rows, unmatched, gateway_by_id


def run(args: argparse.Namespace, ctx: Context) -> int:
    warnings: list[str] = []
    failures: list[Exception] = []
    values: dict[str, object] = {}
    sources: list[tuple[str, Callable[[], object]]] = [
        ("backend", lambda: ctx.backend().list_sand_mcp_tools()),
        ("getMcpState", lambda: ctx.manager().command("getMcpState")),
        (
            "getEffectiveMcpPlugins",
            lambda: ctx.manager().command("getEffectiveMcpPlugins"),
        ),
        (
            "listBoxMcpServers",
            lambda: ctx.manager().command(
                "listBoxMcpServers", {"serverIdentifiers": []}
            ),
        ),
    ]
    for name, fetch in sources:
        try:
            values[name] = fetch()
        except Exception as exc:  # noqa: BLE001 - each independent source can fail
            failures.append(exc)
            warning = f"warning: {name} unavailable: {' '.join(explain_error(exc, cli='gbot').splitlines())}"
            warnings.append(warning)
            print(warning, file=sys.stderr)

    if not values:
        return (
            3
            if any(
                isinstance(exc, ConnectError) and exc.status == 401 for exc in failures
            )
            else 1
        )

    rows, unmatched, gateways = merge_servers(
        values.get("backend"),
        values.get("getMcpState"),
        values.get("listBoxMcpServers"),
        values.get("getEffectiveMcpPlugins"),
    )
    backend_rows = {
        row.get("serverIdentifier"): row
        for row in records(record(values.get("backend")).get("servers"))
        if isinstance(row.get("serverIdentifier"), str)
    }
    if args.tools:
        for row in rows:
            identifier = str(row["server_identifier"])
            backend_tools = backend_rows.get(identifier, {}).get("tools")
            row["tools"] = []
            if isinstance(backend_tools, list):
                row["tools"] = [
                    tool.get("name")
                    for tool in records(backend_tools)
                    if isinstance(tool.get("name"), str)
                ]
            elif isinstance(gateways[identifier].get("id"), str):
                try:
                    result = ctx.manager().command(
                        "listMcpServerTools", {"serverId": gateways[identifier]["id"]}
                    )
                    row["tools"] = [
                        tool.get("name")
                        for tool in records(result)
                        if isinstance(tool.get("name"), str)
                    ]
                except Exception as exc:  # noqa: BLE001 - isolate each server failure
                    row["error"] = " ".join(explain_error(exc, cli="gbot").splitlines())

    columns = [
        ("NAME", "name"),
        ("ACCOUNT", "account"),
        ("STATUS", "status"),
        ("TOOLS", "tool_count"),
        ("PLUGIN", "plugin"),
    ]
    widths = [
        max([len(title), *(len(display(row[key])) for row in rows)])
        for title, key in columns
    ]
    lines = [
        "  ".join(
            title.ljust(width) for (title, _), width in zip(columns, widths)
        ).rstrip()
    ]
    for row in rows:
        line = "  ".join(
            display(row[key]).ljust(width) for (_, key), width in zip(columns, widths)
        ).rstrip()
        if row["auth"] == "needs sign-in":
            line += " - connect it in the Grok Bot app"
        lines.append(line)
        if "error" in row:
            lines.append(f"  error: {row['error']}")
        if isinstance(row.get("tools"), list):
            lines.extend(f"  {tool}" for tool in row["tools"])
    if unmatched:
        lines.append("Plugins without a connector: " + ", ".join(unmatched))
    ctx.out.write(
        {
            "connectors": rows,
            "plugins_without_connector": unmatched,
            "warnings": warnings,
        },
        "\n".join(lines),
    )
    return 0
