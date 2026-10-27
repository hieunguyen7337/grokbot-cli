import argparse
import os
import sys
from pathlib import Path

import httpx

from gbot import config
from gbot.bots import record
from gbot.context import Context
from gbot.protocol import USED_COMMANDS
from groken import app_archive, auth, client, winplat
from groken.errors import explain_error
from groken.inspect_contracts import extract_command_contracts


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "doctor", help="Check machine and gateway compatibility"
    )
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def find_app() -> Path | None:
    override = os.environ.get("GBOT_APP_DIR")
    candidates = (
        [Path(override)]
        if override
        else (
            winplat.app_install_dirs()
            if sys.platform == "win32"
            else [app_archive.DEFAULT_APP_PATH]
        )
    )
    return next((path for path in candidates if path.exists()), None)


def protocol_check(app: Path) -> tuple[str, str]:
    try:
        archive = app_archive.resolve_asar(app)
        header = app_archive.read_asar_header(archive)
        source = app_archive.read_asar_entry(
            archive, header, app_archive.COORDINATOR_MAIN
        )
        contracts = extract_command_contracts(source.decode("utf-8", "replace"))
    except (app_archive.AsarError, OSError, ValueError):
        return "warn", "could not read the command table"
    if not contracts:
        return "warn", "could not read the command table"
    found = {contract.name: contract.args for contract in contracts}
    drift = [
        f"{name}: missing"
        if name not in found
        else f"{name}: args {expected} -> {found[name]}"
        for name, expected in USED_COMMANDS.items()
        if found.get(name) != expected
    ]
    return (
        ("warn", "; ".join(drift))
        if drift
        else (
            "pass",
            f"{len(found)} commands; all {len(USED_COMMANDS)} used commands present",
        )
    )


def is_auth_error(exc: Exception) -> bool:
    return (isinstance(exc, client.ConnectError) and exc.status == 401) or (
        isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 401
    )


def run(args: argparse.Namespace, ctx: Context) -> int:
    checks: list[dict[str, str]] = []
    auth_failed = False

    def add(check: str, status: str, detail: str) -> None:
        checks.append(
            {"check": check, "status": status, "detail": " ".join(detail.splitlines())}
        )

    app = find_app()
    if app is None:
        add("app", "warn", "not found; set GBOT_APP_DIR")
    else:
        version = app_archive.read_bundle_version(app)
        add("app", "pass" if version else "warn", f"{app}; version {version or '-'}")
    try:
        version = client.detect_client_version()
        source = (
            "env override (SAND_CLIENT_VERSION)"
            if os.environ.get("SAND_CLIENT_VERSION")
            else ("app" if app is not None else "cached version or fallback")
        )
        add("client_version", "pass", f"{version} ({source})")
    except Exception as exc:  # noqa: BLE001 - diagnostics continue after failed checks
        add("client_version", "fail", explain_error(exc, cli="gbot"))
    try:
        tokens = auth.load_tokens()
        signed_in = bool(tokens and tokens.get("accessToken"))
        auth_failed = not signed_in
        add(
            "token",
            "pass" if signed_in else "fail",
            "Access token present" if signed_in else "Not signed in. Run: gbot login",
        )
    except (OSError, ValueError, auth.TokenStateError):
        signed_in = False
        auth_failed = True
        add("token", "fail", "Cannot read sign-in state. Run: gbot login")
    if not signed_in or args.offline:
        reason = "Not signed in" if not signed_in else "Offline"
        for name in ("gateway", "default_bot", "host"):
            add(name, "skip", reason)
    else:
        bots: list[object] | None = None
        try:
            value = ctx.manager().command("listAgents")
            if not isinstance(value, list):
                raise TypeError("Invalid listAgents response: expected a list")
            bots = value
            add("gateway", "pass", f"{len(bots)} bots")
        except Exception as exc:  # noqa: BLE001 - diagnostics continue after failed checks
            auth_failed = is_auth_error(exc)
            add("gateway", "fail", explain_error(exc, cli="gbot"))
        if bots is None:
            add("default_bot", "skip", "Gateway unavailable")
            add("host", "skip", "Gateway unavailable")
        else:
            default = config.default_bot()
            if default is None:
                add("default_bot", "warn", "No bot selected. Run: gbot use <name>")
            elif any(record(bot).get("id") == default["id"] for bot in bots):
                add("default_bot", "pass", f"{default['name']} ({default['id']})")
            else:
                add(
                    "default_bot",
                    "warn",
                    f"Selected bot {default['name']} ({default['id']}) no longer exists. Run: gbot use <name>",
                )
            try:
                host = record(ctx.manager().command("getHostStatus"))
                update = host.get("hostUpdateAvailable") is True
                add(
                    "host",
                    "warn" if update else "pass",
                    f"version {host.get('hostVersion') or '-'}"
                    + ("; update available" if update else ""),
                )
            except Exception as exc:  # noqa: BLE001 - diagnostics continue after failed checks
                auth_failed = auth_failed or is_auth_error(exc)
                add("host", "fail", explain_error(exc, cli="gbot"))
    if app is None:
        add("protocol", "skip", "App not found")
    else:
        status, detail = protocol_check(app)
        add("protocol", status, detail)
    ctx.out.write(
        checks,
        "\n".join(
            f"[{row['status'].upper()}] {row['check']}  {row['detail']}"
            for row in checks
        ),
    )
    if auth_failed:
        return 3
    if any(row["status"] == "fail" for row in checks):
        return 1
    return 2 if any(row["status"] == "warn" for row in checks) else 0
