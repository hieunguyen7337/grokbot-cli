"""Microsoft Teams bot installation and human account linking."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from groken.client import ConnectError

from .transport import Transport

RPCS = frozenset(
    (
        "GetGrokBotTeamsInstallState",
        "StartGrokBotTeamsConnect",
        "InstallGrokBotTeamsApp",
        "ReinstallGrokBotTeamsApp",
        "UninstallGrokBotTeamsApp",
        "ListGrokBotTeamsJoinedTeams",
        "AddGrokBotTeamsAppToTeam",
        "DisconnectGrokBotTeamsAccount",
        "GetMicrosoftTeamsAccountLinkStatus",
        "StartMicrosoftTeamsAccountLink",
        "UnlinkMicrosoftTeamsAccount",
    )
)

STATES = (
    "unspecified",
    "not_connected",
    "connected",
    "app_created",
    "pending_admin_approval",
    "installed",
    "update_pending",
    "removed_in_teams",
    "removed",
    "unsupported_harness",
    "not_published",
    "unavailable",
    "provisioning",
)
CONSENTS = (
    "unspecified",
    "consent_required",
    "access_denied",
    "other",
    "grant_conflict",
)
REASONS = (
    "unspecified",
    "setting_up",
    "admin_approval",
    "admin_consent",
    "team_owner",
    "admin_policy",
    "rejected",
    "removed",
    "not_set_up",
)


def _enum(value: object, names: Sequence[str], prefix: str) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        return names[value] if 0 <= value < len(names) else "unknown"
    name = str(value).lower().removeprefix(prefix.lower() + "_")
    if name.isdecimal():
        return _enum(int(name), names, prefix)
    return name if name in names else "unknown"


_SENTENCES = {
    "unspecified": "Teams status has not been reported.",
    "unknown": "Teams returned an unknown status.",
    "not_connected": "Connect this bot to Teams first.",
    "connected": "Connected to Teams; the app can be installed.",
    "app_created": "The Teams app is ready to install.",
    "pending_admin_approval": "Waiting for a Teams admin to approve the app.",
    "installed": "The Teams app is installed.",
    "update_pending": "The Teams app update is awaiting approval.",
    "removed_in_teams": "The app was removed in Teams.",
    "removed": "The Teams app was removed.",
    "unsupported_harness": "Teams is unavailable for this bot's harness.",
    "not_published": "The Teams app has not been published.",
    "unavailable": "Teams is currently unavailable.",
    "provisioning": "The Teams app is being set up.",
    "consent_required": "Microsoft consent is required.",
    "access_denied": "Microsoft consent was denied.",
    "other": "Microsoft consent did not complete successfully.",
    "grant_conflict": "Microsoft consent conflicts with an existing grant.",
    "setting_up": "The Teams bot is being set up.",
    "admin_approval": "Waiting for a Teams admin to approve the app.",
    "admin_consent": "A Teams admin must grant consent.",
    "team_owner": "A team owner must approve the installation.",
    "admin_policy": "A Teams admin policy blocks the app.",
    "rejected": "Teams rejected the app.",
    "not_set_up": "The Teams app has not been set up.",
}


def sentence(value: str) -> str:
    return _SENTENCES.get(
        value, "Teams could not complete the request: " + value.replace("_", " ") + "."
    )


def _rows(value: object) -> tuple[dict[str, object], ...]:
    return (
        tuple(dict(row) for row in value if isinstance(row, dict))
        if isinstance(value, list)
        else ()
    )


@dataclass(frozen=True)
class TeamsState:
    state: str
    tenant_id: str | None = None
    tenant_name: str | None = None
    manager_is_admin: bool = False
    installed_teams: tuple[dict[str, object], ...] = ()
    failure_reason: str = ""
    rejection_note: str = ""
    consent_result: str = ""
    connected_account: dict[str, object] | None = None
    terminal: bool = False
    poll_after_ms: int | None = None
    bot_status: dict[str, object] | None = None

    @property
    def messages(self) -> tuple[str, ...]:
        values = [self.state, self.failure_reason, self.consent_result]
        if self.bot_status and not self.bot_status.get("connected"):
            values.append(str(self.bot_status.get("reason", "unknown")))
        return tuple(dict.fromkeys(sentence(value) for value in values if value))


def _state(row: dict[str, object]) -> TeamsState:
    consent = _enum(
        row.get("consentResult", 0), CONSENTS, "GROK_BOT_TEAMS_CONSENT_RESULT"
    )
    status = row.get("botStatus")
    if isinstance(status, dict):
        # Browser URLs belong only in the handoff, never the status panel/output.
        status = {
            "connected": bool(status.get("connected")),
            "reason": _enum(
                status.get("reason", 0), REASONS, "GROK_BOT_TEAMS_BOT_STATUS_REASON"
            ),
        }
    account = row.get("connectedAccount")
    return TeamsState(
        _enum(row.get("state", 0), STATES, "GROK_BOT_TEAMS_INSTALL_STATE"),
        str(row["tenantId"]) if row.get("tenantId") else None,
        str(row["tenantDisplayName"]) if row.get("tenantDisplayName") else None,
        bool(row.get("managerIsAdmin")),
        _rows(row.get("installedTeams")),
        str(row.get("failureReason") or ""),
        str(row.get("rejectionNote") or ""),
        "" if consent == "unspecified" else consent,
        dict(account) if isinstance(account, dict) else None,
        bool(row.get("terminal")),
        int(str(row["pollAfterMs"])) if row.get("pollAfterMs") is not None else None,
        status if isinstance(status, dict) else None,
    )


def install_state(
    transport: Transport, bot_id: str, *, nonce: str | None = None
) -> TeamsState:
    payload: dict[str, object] = {"agentId": bot_id}
    if nonce is not None:
        payload["consentNonce"] = nonce
    try:
        return _state(transport.rpc("GetGrokBotTeamsInstallState", payload))
    except ConnectError as error:
        if error.status == 404 or '"not_found"' in error.body:
            return TeamsState("not_connected")
        raise


def start_connect(
    transport: Transport, bot_id: str, *, admin: bool = False
) -> tuple[str, str, str]:
    row = transport.rpc(
        "StartGrokBotTeamsConnect",
        {
            "agentId": bot_id,
            "requestAdminScopes": admin,
            "grantScopeTeam": False,
            "forceAccountSelection": False,
        },
    )
    urls = str(row.get("consentUrl") or ""), str(row.get("adminConsentUrl") or "")
    if not urls[1 if admin else 0]:
        raise ValueError("Teams did not return a sign-in link.")
    return (*urls, str(row.get("nonce") or ""))


def install(
    transport: Transport,
    bot_id: str,
    *,
    tenant_id: str | None = None,
    team_ids: Sequence[str] = (),
    personal: bool = True,
    nonce: str | None = None,
) -> TeamsState:
    payload: dict[str, object] = {
        "agentId": bot_id,
        "teamIds": list(team_ids),
        "installPersonal": personal,
    }
    if tenant_id is not None:
        payload["tenantId"] = tenant_id
    if nonce is not None:
        payload["consentNonce"] = nonce
    return _state(transport.rpc("InstallGrokBotTeamsApp", payload))


def reinstall(
    transport: Transport, bot_id: str, *, nonce: str | None = None
) -> TeamsState:
    payload: dict[str, object] = {"agentId": bot_id}
    if nonce is not None:
        payload["consentNonce"] = nonce
    return _state(transport.rpc("ReinstallGrokBotTeamsApp", payload))


def uninstall(transport: Transport, bot_id: str) -> TeamsState:
    return _state(transport.rpc("UninstallGrokBotTeamsApp", {"agentId": bot_id}))


def joined_teams(transport: Transport, bot_id: str) -> tuple[dict[str, object], ...]:
    try:
        return _rows(
            transport.rpc("ListGrokBotTeamsJoinedTeams", {"agentId": bot_id}).get(
                "teams"
            )
        )
    except ConnectError as error:
        if error.status == 404 or '"not_found"' in error.body:
            return ()
        raise


def add_to_team(
    transport: Transport, bot_id: str, team_id: str, *, nonce: str | None = None
) -> dict[str, object]:
    payload: dict[str, object] = {"agentId": bot_id, "teamId": team_id}
    if nonce is not None:
        payload["consentNonce"] = nonce
    return transport.rpc("AddGrokBotTeamsAppToTeam", payload)


def disconnect(
    transport: Transport, bot_id: str, tenant_id: str
) -> tuple[bool, str, tuple[str, ...]]:
    row = transport.rpc(
        "DisconnectGrokBotTeamsAccount", {"agentId": bot_id, "tenantId": tenant_id}
    )
    ids = row.get("stillInstalledAgentIds")
    return (
        bool(row.get("revoked")),
        _enum(row.get("state", 0), STATES, "GROK_BOT_TEAMS_INSTALL_STATE"),
        tuple(str(value) for value in ids) if isinstance(ids, list) else (),
    )


@dataclass(frozen=True)
class AccountLink:
    tenant_id: str
    aad_object_id: str
    linked_at_ms: int


def account_links(transport: Transport) -> tuple[AccountLink, ...]:
    return tuple(
        AccountLink(
            str(row.get("tenantId", "")),
            str(row.get("aadObjectId", "")),
            int(str(row.get("linkedAtMs", 0))),
        )
        for row in _rows(
            transport.rpc("GetMicrosoftTeamsAccountLinkStatus", {}).get("links")
        )
    )


def start_account_link(transport: Transport, tenant_hint: str | None = None) -> str:
    url = str(
        transport.rpc(
            "StartMicrosoftTeamsAccountLink",
            {"tenantHint": tenant_hint} if tenant_hint is not None else {},
        ).get("authorizationUrl")
        or ""
    )
    if not url:
        raise ValueError("Teams did not return a sign-in link.")
    return url


def unlink_account(transport: Transport, tenant_id: str) -> bool:
    return bool(
        transport.rpc("UnlinkMicrosoftTeamsAccount", {"tenantId": tenant_id}).get(
            "unlinked"
        )
    )


def connect_check(
    transport: Transport, bot_id: str, nonce: str
) -> Callable[[], TeamsState | None]:
    def check() -> TeamsState | None:
        state = install_state(transport, bot_id, nonce=nonce)
        return (
            state
            if state.consent_result
            or state.connected_account is not None
            or state.terminal
            else None
        )

    return check


def account_link_check(
    transport: Transport, before: Sequence[AccountLink]
) -> Callable[[], AccountLink | None]:
    old = set(before)

    def check() -> AccountLink | None:
        return next(
            (link for link in account_links(transport) if link not in old), None
        )

    return check


DEMO_RPCS: dict[str, object] = {name: {} for name in RPCS}
DEMO_RPCS.update(
    {
        "GetGrokBotTeamsInstallState": {"state": "NOT_CONNECTED"},
        "StartGrokBotTeamsConnect": {
            "consentUrl": "https://example.invalid/teams",
            "adminConsentUrl": "https://example.invalid/teams-admin",
            "nonce": "demo",
        },
        "StartMicrosoftTeamsAccountLink": {
            "authorizationUrl": "https://example.invalid/teams-account"
        },
    }
)
