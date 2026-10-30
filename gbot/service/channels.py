"""Slack app installation, account texting and listener connections."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from groken.client import ConnectError

from .models import _record, _text
from .transport import Transport

COMMANDS = {"getListenerIntegrations": "none", "getListenerConnectUrl": "object"}
RPCS = (
    "GetGrokBotSlackInstallState",
    "StartGrokBotSlackConnect",
    "InstallGrokBotSlackApp",
    "ReinstallGrokBotSlackApp",
    "UninstallGrokBotSlackApp",
    "GetGrokBotMessagingLinkStatus",
    "IssueGrokBotMessagingLinkCode",
    "ListGrokBotMessagingLinkedPhones",
    "UnlinkGrokBotMessagingPhone",
)
_ENUMS = {
    "INSTALL_STATUS": "unspecified not_connected app_created connected unsupported_harness",
    "CONNECT_OUTCOME": "unspecified started unsupported_harness not_published",
    "INSTALL_OUTCOME": "unspecified installed pending_admin_approval not_connected workspace_required manager_reauth_required insufficient_scopes install_conflict ratelimited slack_rejected unsupported_harness not_published workspace_not_allowed",
    "REINSTALL_OUTCOME": "unspecified updated up_to_date recreate_required pending_admin_approval not_connected manager_reauth_required insufficient_scopes ratelimited slack_rejected unsupported_harness throttled",
    "UNINSTALL_OUTCOME": "unspecified removed not_connected manager_reauth_required ratelimited slack_rejected unsupported_harness",
}
CALLBACK_HINT = "If the browser asked to open the Grok Bot app, finish there; gbot cannot receive that callback."


def _enum(value: object, kind: str) -> str:
    names = _ENUMS[kind].split()
    if isinstance(value, int) and not isinstance(value, bool):
        return names[value] if 0 <= value < len(names) else "unknown"
    name = str(value).upper().removeprefix(f"GROK_BOT_SLACK_{kind}_").lower()
    return name if name in names else "unknown"


def _error(error: ConnectError) -> dict[str, object]:
    try:
        return dict(_record(json.loads(error.body)))
    except ValueError:
        return {}


def _rows(value: object) -> list[dict[str, object]]:
    return (
        [dict(row) for row in value if isinstance(row, Mapping)]
        if isinstance(value, list)
        else []
    )


def _number(value: object) -> int:
    try:
        return int(str(value))
    except ValueError:
        return 0


@dataclass(frozen=True)
class SlackState:
    status: str
    workspace_name: str = ""
    workspaces: tuple[dict[str, object], ...] = ()
    needs_manifest_update: bool = False
    pending_reinstall_approval: bool = False
    app_unreachable: bool = False
    removed_in_slack: bool = False
    authorize_url: str | None = field(default=None, repr=False)


def slack_state(transport: Transport, bot_id: str) -> SlackState:
    try:
        row = transport.rpc(RPCS[0], {"agentId": bot_id})
    except ConnectError as error:
        if error.status == 404 or _error(error).get("code") == "not_found":
            return SlackState("not_connected")
        raise
    return SlackState(
        _enum(row.get("status"), "INSTALL_STATUS"),
        _text(row.get("workspaceName")),
        tuple(_rows(row.get("workspaces"))),
        row.get("needsManifestUpdate") is True,
        row.get("pendingReinstallApproval") is True,
        row.get("appUnreachable") is True,
        row.get("removedInSlack") is True,
        _text(row.get("oauthAuthorizeUrl")) or None,
    )


def slack_check(
    transport: Transport, bot_id: str, before: SlackState
) -> Callable[[], SlackState | None]:
    def check() -> SlackState | None:
        state = slack_state(transport, bot_id)
        return (
            state
            if (
                state.status != before.status
                or state.workspaces != before.workspaces
                or state.pending_reinstall_approval != before.pending_reinstall_approval
            )
            else None
        )

    return check


def _outcome(row: dict[str, object], kind: str) -> tuple[str, str | None, str]:
    outcome = _enum(row.get("outcome"), kind + "_OUTCOME")
    messages = {
        "pending_admin_approval": "Waiting for a Slack admin to approve the app.",
        "manager_reauth_required": "Reconnect your Slack account first.",
        "unsupported_harness": "This bot does not support Slack.",
        "not_published": "Publish this bot before connecting Slack.",
        "not_connected": "Connect your Slack account first.",
        "workspace_required": "Choose a Slack workspace first.",
        "insufficient_scopes": "Reconnect Slack to grant the required permissions.",
        "install_conflict": "A Slack app is already installed in another workspace.",
        "workspace_not_allowed": "This Slack workspace is not allowed.",
        "recreate_required": "Recreate the Slack app by installing it again.",
        "throttled": "Slack app updates are temporarily throttled. Try again later.",
        "ratelimited": f"Slack rate limit reached. Try again in {row.get('retryAfterSeconds', 0)} seconds.",
        "slack_rejected": f"Slack rejected the request: {_text(row.get('slackError')) or 'unknown error'}.",
    }
    success = outcome in {"started", "installed", "updated", "up_to_date", "removed"}
    return (
        outcome,
        _text(row.get("url")) or _text(row.get("oauthAuthorizeUrl")) or None,
        "" if success else messages.get(outcome, "Slack did not complete the request."),
    )


def start_slack_connect(
    transport: Transport, bot_id: str
) -> tuple[str, str | None, str]:
    return _outcome(
        transport.rpc(RPCS[1], {"agentId": bot_id, "returnToMobileApp": False}),
        "CONNECT",
    )


def install_slack(
    transport: Transport, bot_id: str, slack_team_id: str | None = None
) -> tuple[str, str | None, str]:
    payload: dict[str, object] = {
        "agentId": bot_id,
        "replaceExistingApp": False,
        "approvalRequestResubmitted": False,
    }
    if slack_team_id is not None:
        payload["slackTeamId"] = slack_team_id
    return _outcome(transport.rpc(RPCS[2], payload), "INSTALL")


def reinstall_slack(transport: Transport, bot_id: str) -> tuple[str, str | None, str]:
    return _outcome(
        transport.rpc(RPCS[3], {"agentId": bot_id, "automatic": False}), "REINSTALL"
    )


def uninstall_slack(transport: Transport, bot_id: str) -> tuple[str, str | None, str]:
    return _outcome(
        transport.rpc(RPCS[4], {"agentId": bot_id, "forgetIfUnreachable": False}),
        "UNINSTALL",
    )


@dataclass(frozen=True)
class MessagingLink:
    available: bool
    unavailable_reason: str = ""
    line_number: str = ""
    pending_code: tuple[str, int, str, str] | None = None


def _code(row: Mapping[str, object]) -> tuple[str, int, str, str]:
    return (
        _text(row.get("code")),
        _number(row.get("expiresAtMs")),
        _text(row.get("linkMessage")),
        _text(row.get("smsUri")),
    )


def messaging_link(transport: Transport) -> MessagingLink:
    try:
        row = transport.rpc(RPCS[5], {})
    except ConnectError as error:
        body = _error(error)
        if error.status == 403 or body.get("code") == "permission_denied":
            return MessagingLink(
                False, _text(body.get("message")) or "Texting is not available yet."
            )
        raise
    pending = _record(row.get("pendingCode"))
    return MessagingLink(
        True,
        line_number=_text(row.get("lineNumber")),
        pending_code=_code(pending) if pending else None,
    )


@dataclass(frozen=True)
class LinkedPhone:
    handle_id: str
    address: str
    linked_at_ms: int
    last_seen_at_ms: int


def linked_phones(transport: Transport) -> tuple[LinkedPhone, ...]:
    try:
        row = transport.rpc(RPCS[7], {})
    except ConnectError as error:
        if error.status == 403 or _error(error).get("code") == "permission_denied":
            return ()
        raise
    return tuple(
        LinkedPhone(
            _text(p.get("handleId")),
            _text(p.get("address")),
            _number(p.get("linkedAtMs")),
            _number(p.get("lastSeenAtMs")),
        )
        for p in _rows(row.get("phones"))
    )


def issue_link_code(transport: Transport) -> MessagingLink:
    row = transport.rpc(RPCS[6], {})
    return MessagingLink(
        True, line_number=_text(row.get("lineNumber")), pending_code=_code(row)
    )


def unlink_phone(transport: Transport, handle_id: str) -> None:
    transport.rpc(RPCS[8], {"handleId": handle_id})


@dataclass(frozen=True)
class Integration:
    platform: str
    is_connected: bool
    needed_by_count: int
    state: str
    detail: str
    granted_repos: tuple[str, ...]
    scope_issues: tuple[dict[str, object], ...]


def listener_integrations(transport: Transport) -> tuple[Integration, ...]:
    reply = _record(transport.command("getListenerIntegrations"))
    return tuple(
        Integration(
            _text(r.get("platform")),
            r.get("isConnected") is True,
            _number(r.get("neededByCount")),
            _text(r.get("state")),
            _text(r.get("detail")),
            tuple(str(s) for s in repos)
            if isinstance(repos := r.get("grantedRepos"), list)
            else (),
            tuple(_rows(r.get("scopeIssues"))),
        )
        for r in _rows(reply.get("integrations"))
    )


def listener_connect_url(transport: Transport, platform: str) -> str:
    return _text(
        _record(transport.command("getListenerConnectUrl", {"platform": platform})).get(
            "url"
        )
    )


def listener_check(
    transport: Transport, platform: str
) -> Callable[[], Integration | None]:
    def check() -> Integration | None:
        return next(
            (
                row
                for row in listener_integrations(transport)
                if row.platform == platform and row.is_connected
            ),
            None,
        )

    return check


DEMO_COMMANDS = {
    "getListenerIntegrations": {
        "integrations": [
            {"platform": p, "isConnected": False, "state": "idle", "neededByCount": 0}
            for p in (
                "azure-devops",
                "bitbucket",
                "github",
                "gitlab",
                "origin",
                "slack",
            )
        ]
    },
    "getListenerConnectUrl": {"url": "https://example.test/listener"},
}
DEMO_RPCS = {
    RPCS[0]: {
        "status": "not_connected",
        "workspaces": [{"slackTeamId": "demo", "slackTeamName": "Demo workspace"}],
    },
    RPCS[1]: {"outcome": "started"},
    RPCS[2]: {"outcome": "installed"},
    RPCS[3]: {"outcome": "up_to_date"},
    RPCS[4]: {"outcome": "removed"},
    RPCS[5]: {"lineNumber": "+15550100"},
    RPCS[6]: {
        "code": "DEMO",
        "expiresAtMs": "1800000600000",
        "lineNumber": "+15550100",
        "linkMessage": "Link DEMO",
        "smsUri": "sms:+15550100?body=Link%20DEMO",
    },
    RPCS[7]: {"phones": []},
    RPCS[8]: {},
}
