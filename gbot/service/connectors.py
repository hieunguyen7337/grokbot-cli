"""Account connector settings, with credential-free display models."""

import re
from collections.abc import Callable
from dataclasses import dataclass

from .models import _record
from .transport import Transport

COMMANDS = {
    "getMcpState": "none",
    **dict.fromkeys(
        (
            "listMcpServerTools",
            "toggleMcpToolDisabled",
            "setMcpCustomInstructions",
            "renameMcpAccount",
            "removeMcpAccount",
            "removeMcpServer",
            "authenticateMcpServer",
        ),
        "object",
    ),
}
RPCS = (
    "GetGrokBotUserRuntimeSettings",
    "SetGrokBotMcpToolPermissions",
    "GetGrokBotConnectorSharedSpaceAllowlist",
    "UpdateGrokBotConnectorSharedSpaceAllowlist",
    "ClearGrokBotConnectorAlwaysAllow",
)
LABELS = ("auto_review", "always_allow", "needs_approval", "blocked")
TIMEOUT = "If the browser asked to open the Grok Bot app, finish there; gbot cannot receive that callback."
STATUSES = {
    "sign_in_pending": "Sign-in is pending.",
    "authentication_required": "Sign in to use this connector.",
    "failed_to_load": "This connector failed to load.",
    "not_reported_by_backend": "The backend has not reported this connector.",
    "bot_computer_unreachable": "The bot computer is unreachable.",
    "not_reported_by_bot_computer": "The bot computer has not reported this connector.",
    "disabled_by_team_admin": "Your team admin disabled this connector.",
    "grant_required": "This connector needs an access grant.",
    "runs_on_bot_computer": "This connector runs on the bot computer.",
}


@dataclass(frozen=True)
class Server:
    id: str
    name: str
    server_identifier: str
    plugin_id: str
    plugin_name: str
    is_team: bool
    account_key: str
    status: str
    status_kind: str
    status_message: str
    tool_count: int
    transport: str
    custom_instructions: str


def servers(transport: Transport) -> list[Server]:
    rows = _record(transport.command("getMcpState")).get("servers", [])
    result = []
    for value in rows if isinstance(rows, list) else []:
        row = _record(value)
        detail = _record(row.get("statusDetail"))
        result.append(
            Server(
                str(row.get("id", "")),
                str(row.get("name", "")),
                str(row.get("serverIdentifier", "")),
                str(row.get("pluginId") or ""),
                str(row.get("pluginDisplayName") or ""),
                row.get("isTeamServer") is True,
                str(row.get("accountKey") or ""),
                str(row.get("status") or ""),
                str(detail.get("kind") or ""),
                str(detail.get("message") or detail.get("reason") or ""),
                int(str(row.get("toolCount") or 0)),
                str(row.get("transport") or ""),
                str(row.get("customInstructions") or ""),
            )
        )
    return result


def find(rows: list[Server], query: str) -> Server:
    matches = [
        s
        for s in rows
        if query.casefold()
        in {
            s.id.casefold(),
            s.server_identifier.casefold(),
            s.name.casefold(),
            s.plugin_name.casefold(),
        }
    ]
    if len(matches) != 1:
        choices = matches or rows
        raise ValueError(
            "Connector match must be unique. Choices: "
            + ", ".join(f"{s.name} ({s.id})" for s in choices)
        )
    return matches[0]


def status_sentence(server: Server) -> str:
    return STATUSES.get(server.status_kind, server.status)


def _label(value: object) -> str:
    if isinstance(value, int) and 0 <= value < 4:
        return LABELS[value]
    text = str(value).lower().removeprefix("grok_bot_tool_permission_")
    return (
        "auto_review"
        if text == "unspecified"
        else text
        if text in LABELS
        else "needs_approval"
    )


def normalize(value: str) -> str:
    text = {
        "auto": "auto_review",
        "allow": "always_allow",
        "ask": "needs_approval",
        "block": "blocked",
    }.get(value, value)
    if text not in LABELS:
        raise ValueError("Permission must be auto, allow, ask or block.")
    return text


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    is_disabled: bool
    is_read_only: bool
    permission: str
    group_permission: str


def tools(transport: Transport, server_id: str) -> list[Tool]:
    rows = transport.command("listMcpServerTools", {"serverId": server_id})
    return (
        [
            Tool(
                str(r.get("name", "")),
                str(r.get("description", "")),
                r.get("isDisabled") is True,
                r.get("isReadOnly") is True,
                _label(r.get("permission", 0)),
                _label(r.get("groupPermission", 0)),
            )
            for value in rows
            if (r := _record(value))
        ]
        if isinstance(rows, list)
        else []
    )


@dataclass(frozen=True)
class Policy:
    tools: dict[str, str]
    reads: str | None = None
    writes: str | None = None


def _policy(value: object) -> Policy:
    row = _record(value)

    def optional(value: object) -> str | None:
        label = _label(value)
        return None if value is None or label == "auto_review" else label

    return Policy(
        {
            str(k): label
            for k, v in _record(row.get("tools")).items()
            if (label := _label(v)) != "auto_review"
        },
        optional(row.get("reads")),
        optional(row.get("writes")),
    )


def policy(transport: Transport, server_id: str) -> Policy:
    reply = transport.rpc("GetGrokBotUserRuntimeSettings", {})
    scopes = _record(
        _record(_record(reply.get("settings")).get("toolPermissions")).get("scopes")
    )
    return _policy(scopes.get(server_id))


def set_permission(
    transport: Transport,
    server_id: str,
    *,
    tool: tuple[str, str] | None = None,
    reads: str | None = None,
    writes: str | None = None,
) -> Policy:
    changes = sum(v is not None for v in (tool, reads, writes))
    if not changes:
        raise ValueError("Specify a tool, read default or write default.")
    current = policy(transport, server_id)
    mapping = dict(current.tools)
    if tool is not None:
        name, value = tool
        label = normalize(value)
        if label == "auto_review":
            mapping.pop(name, None)
        else:
            mapping[name] = label
    payload: dict[str, object] = {
        "serverId": server_id,
        "tools": {k: LABELS.index(v) for k, v in mapping.items()},
    }
    for key, value, old in (
        ("reads", reads, current.reads),
        ("writes", writes, current.writes),
    ):
        if value is not None or old is not None:
            payload[key] = LABELS.index(
                normalize(value if value is not None else str(old))
            )
    reply = transport.rpc("SetGrokBotMcpToolPermissions", payload)
    return _policy(_record(reply.get("server")).get("policy"))


def set_tool_disabled(
    transport: Transport, server_id: str, tool_name: str, disabled: bool
) -> None:
    found = next((t for t in tools(transport, server_id) if t.name == tool_name), None)
    if found is None:
        raise ValueError(f"Unknown tool: {tool_name}")
    if found.is_disabled != disabled:
        transport.command(
            "toggleMcpToolDisabled", {"serverId": server_id, "toolName": tool_name}
        )


def set_instructions(transport: Transport, server_id: str, text: str) -> None:
    transport.command(
        "setMcpCustomInstructions",
        {"serverId": server_id, "instructions": text.strip()},
    )


def rename_account(
    transport: Transport, server_id: str, account_key: str, new_key: str
) -> object:
    return transport.command(
        "renameMcpAccount",
        {"serverId": server_id, "accountKey": account_key, "newAccountKey": new_key},
    )


def remove_account(transport: Transport, server_id: str, account_key: str) -> object:
    return transport.command(
        "removeMcpAccount", {"serverId": server_id, "accountKey": account_key}
    )


def remove_server(transport: Transport, server_id: str) -> object:
    if find(servers(transport), server_id).is_team:
        raise ValueError("Your team admin manages this connector.")
    return transport.command("removeMcpServer", {"serverId": server_id})


def shared_spaces(transport: Transport) -> set[str]:
    rows = transport.rpc("GetGrokBotConnectorSharedSpaceAllowlist", {}).get(
        "serverIds", []
    )
    return {str(x) for x in rows} if isinstance(rows, list) else set()


def set_shared_space(transport: Transport, server_id: str, allowed: bool) -> None:
    transport.rpc(
        "UpdateGrokBotConnectorSharedSpaceAllowlist",
        {"addServerIds" if allowed else "removeServerIds": [server_id]},
    )


def clear_always_allow(transport: Transport) -> int:
    return int(
        str(
            transport.rpc("ClearGrokBotConnectorAlwaysAllow", {}).get("clearedCount", 0)
        )
    )


def _auth_message(value: object, *secrets: object) -> str:
    text = str(value or "")
    for secret in secrets:
        if isinstance(secret, str) and secret:
            text = text.replace(secret, "[redacted]")
    return re.sub(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s]+", "[redacted]", text)


def start_sign_in(
    transport: Transport,
    server_id: str,
    *,
    account_key: str | None = None,
    reauth: bool = False,
) -> tuple[str, str | None, str]:
    payload: dict[str, object] = {"serverId": server_id, "entryPoint": "settings"}
    if account_key is not None:
        payload["accountKey"] = account_key
    if reauth:
        payload["forceReauth"] = True
    try:
        row = _record(transport.command("authenticateMcpServer", payload))
    except Exception:  # noqa: BLE001 - authentication errors can contain credentials
        raise ValueError("Could not start connector sign-in.") from None
    outcome = str(
        row.get("status") or row.get("outcome") or row.get("kind") or "unknown"
    ).replace("-", "_")
    sentences = {
        "started": "Finish signing in in your browser.",
        "already_authenticated": "This account is already signed in.",
        "not_configured": "This connector is not configured.",
        "unreachable": "This connector is unreachable.",
        "not_supported": "This connector does not support browser sign-in.",
    }
    if outcome not in sentences:
        outcome = "unknown"
    url = row.get("authorizationUrl") or row.get("url")
    if outcome == "started" and not (isinstance(url, str) and url):
        raise ValueError("The connector did not return a sign-in link.")
    reason = _auth_message(
        row.get("reason"), row.get("authorizationUrl"), row.get("url")
    )
    sentence = sentences.get(outcome, "The sign-in outcome is unknown.")
    return (
        outcome,
        url if isinstance(url, str) and url else None,
        f"{sentence} {reason}" if reason else sentence,
    )


def sign_in_check(
    transport: Transport,
    before: Server,
    auth_events: list[dict[str, object]] | None = None,
) -> Callable[[], object]:
    def check() -> object:
        matching = next(
            (e for e in auth_events or [] if e.get("serverId") == before.id), None
        )
        if matching and matching.get("outcome") == "cancelled":
            return _auth_message(
                matching.get("failureDetail") or "Sign-in was cancelled."
            )
        try:
            after = next((s for s in servers(transport) if s.id == before.id), None)
        except Exception:  # noqa: BLE001 - status errors can contain sign-in URLs
            raise ValueError("Could not check connector sign-in status.") from None
        if after and (
            matching is not None
            or (
                (after.status, after.status_kind) != (before.status, before.status_kind)
                and after.status_kind
                not in {"authentication_required", "sign_in_pending"}
            )
        ):
            return after
        return None

    return check


DEMO_COMMANDS: dict[str, object] = {name: {} for name in COMMANDS}
DEMO_COMMANDS.update(
    {
        "getMcpState": {
            "servers": [
                {
                    "id": "demo-connector",
                    "name": "Documents",
                    "pluginDisplayName": "Documents",
                    "accountKey": "Personal",
                    "status": "connected",
                    "transport": "http",
                    "toolCount": 1,
                }
            ]
        },
        "listMcpServerTools": [
            {"name": "search", "isReadOnly": True, "permission": "needs_approval"}
        ],
    }
)
DEMO_RPCS: dict[str, object] = {
    name: {} for name in RPCS if name != "GetGrokBotUserRuntimeSettings"
}
