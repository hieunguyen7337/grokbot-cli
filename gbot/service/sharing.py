"""Who has a bot and with what role: access list, team switches, invites, managers, in-place share and clone."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TypeVar
from urllib.parse import parse_qs, urlparse

from groken.client import ConnectError

from .errors import refusal
from .models import _record, _text
from .transport import Transport

RPCS = (
    "AcceptGrokBotAgentAccessInvite",
    "AddGrokBotAgentManager",
    "CloneGrokBotAgentToTeam",
    "CreateGrokBotAgentAccessInvite",
    "GetGrokBotAgentAccess",
    "GetGrokBotAgentInPlaceShareStatus",
    "GetGrokBotAgentLinkAccess",
    "ListGrokBotAgentAccessInvites",
    "ListGrokBotAgentManagers",
    "PreviewGrokBotAgentAccessInvite",
    "RemoveGrokBotAgentManager",
    "RevokeGrokBotAgentAccessInvite",
    "SetGrokBotAgentVisibility",
    "ShareGrokBotAgentInPlace",
    "UpdateGrokBotAgentAccess",
)

KINDS = ("team", "user", "group", "other_team", "organization")
ROLES = ("user", "manager")
POLL_DEADLINE_S = 45 * 60
_POLL_FIRST_S = 1.0
_POLL_FACTOR = 1.5
_POLL_CAP_S = 5.0

# Proto order: a number selects the name at that position.
_ROLE = ("unspecified", "user", "manager")
_LINK = ("unspecified", "allowed", "no_access", "not_found")
_VISIBILITY = ("unspecified", "updated", "unsupported_harness", "no_team", "busy")
_IN_PLACE = ("unspecified", "started", "unsupported", "ineligible")
_IN_PLACE_STATE = ("unspecified", "not_started", "running", "done", "failed")
_IN_PLACE_STEP = (
    "unspecified",
    "check",
    "mark",
    "memory",
    "files",
    "verify_files",
    "grants",
    "flip",
    "finish",
    "clear",
)
_CLONE = ("unspecified", "cloned", "unsupported", "no_team")
_MATCH = ("unspecified", "matches", "does_not_match", "unknown")
_INVITE_STATE = (
    "unspecified",
    "open",
    "accepted",
    "expired",
    "revoked",
    "unavailable",
    "not_shareable",
)
_REASON = (
    "unspecified",
    "no_subscription",
    "tier_not_eligible",
    "not_individual",
    "subscription_not_active",
)
_TIER = ("unspecified", "none", "plus", "premium", "super", "ultra")
_STATUS = (
    "unspecified",
    "redeemed",
    "invalid_code",
    "recipient_mismatch",
    "not_eligible",
    "try_again",
)
_OUTCOME = (
    "unspecified",
    "granted",
    "already_held",
    "already_accepted",
    "accepted_by_someone_else",
    "expired",
    "revoked",
    "not_in_code",
    "not_grantable",
    "try_again",
)
_ROLE_PREFIX = "GROK_BOT_ACCESS_ROLE_"
_ROW_KEYS = {
    "team": ("team", "team"),
    "user": ("userId", "user_id"),
    "group": ("groupId", "group_id"),
    "other_team": ("otherTeamId", "other_team_id"),
    "organization": ("organization", "organization"),
}
_KIND_LABELS = {
    "team": "Team",
    "user": "Person",
    "group": "Group",
    "other_team": "Other team",
    "organization": "Organization",
    "unknown": "Unknown",
}


def _enum(value: object, names: Sequence[str]) -> str:
    """The lowercase short name of an enum sent as a full name, a short name or a number, else `unknown`."""
    if isinstance(value, int) and not isinstance(value, bool):
        return names[value] if 0 <= value < len(names) else "unknown"
    if not isinstance(value, str):
        return "unknown"
    text = value.strip().lower()
    if text.isdecimal():
        return _enum(int(text), names)
    # Full names carry a type prefix that is not worth pinning: the value is the trailing name.
    for name in sorted(names, key=len, reverse=True):
        if text == name or text.endswith("_" + name):
            return name
    return "unknown"


def _int(value: object) -> int | None:
    """int32 arrive as numbers and int64 as decimal strings."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdecimal():
        return int(value)
    return None


def _count(value: object) -> int:
    parsed = _int(value)
    return parsed if parsed is not None else 0


def _rows(value: object) -> tuple[Mapping[str, object], ...]:
    return (
        tuple(row for row in value if isinstance(row, Mapping))
        if isinstance(value, list)
        else ()
    )


def _get(row: Mapping[str, object], *names: str) -> object:
    return next((row[name] for name in names if name in row), None)


def _role(value: object) -> str:
    role = _enum(value, _ROLE)
    return role if role in ROLES else "unknown"


_SENTENCES = {
    "unknown": "The server returned a result this version does not know.",
    "unspecified": "The server did not report a result.",
    # Visibility, in place and clone.
    "updated": "The bot is now visible to your team.",
    "unsupported_harness": "This bot's harness cannot be shared with a team.",
    "unsupported": "This is not supported for this bot.",
    "no_team": "You have no team to share this bot with.",
    "busy": "The bot is busy; try again when it is idle.",
    "started": "Sharing in place started; it keeps running on the server.",
    "ineligible": "This bot or account is not eligible to be shared in place.",
    "cloned": "Cloned the bot to your team.",
    # Link access.
    "allowed": "Link access is allowed.",
    "no_access": "Link access is not allowed.",
    "not_found": "No link access was found for this bot.",
    # Preview: recipient match.
    "matches": "This invite was sent to your email address.",
    "does_not_match": "This invite was sent to a different email address.",
    # Preview: item state.
    "open": "Ready to accept.",
    "accepted": "Already accepted.",
    "expired": "This invite has expired.",
    "revoked": "This invite was revoked.",
    "unavailable": "This bot is no longer available.",
    "not_shareable": "This bot can no longer be shared.",
    # Preview: eligibility.
    "no_subscription": "You need a Grok Bot subscription to accept invites.",
    "tier_not_eligible": "Your subscription tier cannot accept invites.",
    "not_individual": "Only individual subscriptions can accept invites.",
    "subscription_not_active": "Your subscription is not active.",
    # Accept: status.
    "redeemed": "Invite accepted.",
    "invalid_code": "That invite code is not valid.",
    "recipient_mismatch": "This invite was sent to a different email address.",
    "not_eligible": "Your account is not eligible to accept this invite.",
    "try_again": "The invite could not be accepted just now; try again in a moment.",
    # Accept: item outcome.
    "granted": "Access granted.",
    "already_held": "You already have access to this bot.",
    "already_accepted": "You already accepted this invite.",
    "accepted_by_someone_else": "Someone else already accepted this invite.",
    "not_in_code": "That bot is not part of this invite.",
    "not_grantable": "Access to this bot cannot be granted.",
    # In place: state.
    "not_started": "Sharing in place has not been started.",
    "running": "Sharing in place is running.",
    "done": "Sharing in place finished.",
    "failed": "Sharing in place failed.",
}


def sentence(value: str) -> str:
    """One plain sentence for a status, state, outcome or reason short name."""
    return _SENTENCES.get(value, _SENTENCES["unknown"])


T = TypeVar("T")


def attempt(call: Callable[[], T]) -> tuple[T | None, str | None]:
    """Run one read of a combined view: a server refusal becomes its message, anything else raises."""
    try:
        return call(), None
    except ConnectError as error:
        reason = refusal(error)
        if reason is None:
            raise
        return None, reason.message


def refused_message(error: BaseException) -> str | None:
    reason = refusal(error)
    return reason.message if reason else None


# Access ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    kind: str
    ref: str | None = None
    role: str = "user"
    invited_as_email: str | None = field(default=None, repr=False)

    @property
    def key(self) -> tuple[str, str | None]:
        return (self.kind, self.ref)

    @property
    def spec(self) -> str:
        """The `KIND[:ID]` form `gbot share --grant` and `--revoke` take."""
        return self.kind if self.ref is None else f"{self.kind}:{self.ref}"


@dataclass(frozen=True)
class Group:
    name: str
    member_count: int = 0


@dataclass(frozen=True)
class AccessState:
    creator_user_id: int | None = None
    viewer_user_id: int | None = None
    principals: tuple[Principal, ...] = ()
    available_roles: tuple[str, ...] = ROLES
    expected_state_token: str = field(default="", repr=False)
    team_row_on: bool = False
    team_row_off_allowed: bool = False
    groups_enabled: bool = False
    cross_team_sharing_enabled: bool = False
    caller_may_edit_cross_team_rows: bool = False
    people: Mapping[int, str] = field(default_factory=dict, repr=False)
    groups: Mapping[str, Group] = field(default_factory=dict, repr=False)
    organization_name: str = field(default="", repr=False)

    def team_row(self) -> Principal | None:
        return next((p for p in self.principals if p.kind == "team"), None)

    def describe(self, principal: Principal) -> str:
        """A readable name for a row, from the directory when it knows one."""
        kind, ref = principal.kind, principal.ref
        if kind == "team":
            return "Everyone in the team"
        if kind == "organization":
            return f"Everyone in {self.organization_name or 'the organization'}"
        if kind == "user":
            return self.person(ref, principal.invited_as_email)
        if kind == "group":
            group = self.groups.get(ref or "")
            return group.name if group else f"Group #{ref}"
        if kind == "other_team":
            return f"Team #{ref}"
        return "Unknown access row"

    def owner_label(self) -> str:
        if self.creator_user_id is None:
            return "unknown"
        name = self.people.get(self.creator_user_id)
        if self.viewer_user_id == self.creator_user_id:
            return f"{name} (you)" if name else "you"
        return name or f"User #{self.creator_user_id}"

    def person(self, ref: str | int | None, invited_as_email: str | None = None) -> str:
        user_id = _int(ref)
        name = self.people.get(user_id) if user_id is not None else None
        if name:
            return name
        label = f"User #{ref}"
        return f"{label} (invited as {invited_as_email})" if invited_as_email else label


def kind_label(kind: str) -> str:
    return _KIND_LABELS.get(kind, _KIND_LABELS["unknown"])


def _principal(row: Mapping[str, object]) -> Principal:
    kind, ref = "unknown", None
    for name, (camel, snake) in _ROW_KEYS.items():
        value = _get(row, camel, snake)
        if value is None:
            continue
        if name in ("team", "organization"):
            kind = name
        elif (parsed := _int(value)) is not None:
            kind, ref = name, str(parsed)
        break
    email = _get(row, "invitedAsEmail", "invited_as_email")
    return Principal(
        kind,
        ref,
        _role(row.get("role")),
        email if isinstance(email, str) and email else None,
    )


def _people(*sources: object) -> dict[int, str]:
    people: dict[int, str] = {}
    for source in sources:
        for row in _rows(source):
            user_id = _int(_get(row, "userId", "user_id", "id"))
            name = _text(_get(row, "name", "displayName", "display_name"))
            if user_id is not None and name:
                people.setdefault(user_id, name)
    return people


def _groups(*sources: object) -> dict[str, Group]:
    groups: dict[str, Group] = {}
    for source in sources:
        for row in _rows(source):
            group_id = _int(_get(row, "groupId", "group_id", "id"))
            name = _text(_get(row, "name", "displayName", "display_name"))
            if group_id is not None and name:
                count = _count(_get(row, "memberCount", "member_count"))
                groups.setdefault(str(group_id), Group(name, count))
    return groups


def _scopes(directory: Mapping[str, object]) -> list[Mapping[str, object]]:
    """The directory itself, its `team` entry and each of its `teams`: the shape is not settled."""
    scopes = [directory, _record(directory.get("team"))]
    scopes.extend(_rows(directory.get("teams")))
    return scopes


def _organization(directory: Mapping[str, object]) -> str:
    for scope in _scopes(directory):
        for key in ("organizationName", "organization_name", "organization", "name"):
            value = scope.get(key)
            if isinstance(value, Mapping):
                value = value.get("name")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _directories(
    reply: Mapping[str, object],
) -> tuple[dict[int, str], dict[str, Group], str]:
    team = _record(_get(reply, "botTeamDirectory", "bot_team_directory"))
    cross = _record(_get(reply, "crossTierDirectory", "cross_tier_directory"))
    scopes = [*_scopes(team), *_scopes(cross)]
    people = _people(
        _get(reply, "personalBotPeople", "personal_bot_people"),
        *(scope.get("people") for scope in scopes),
    )
    groups = _groups(*(scope.get("groups") for scope in scopes))
    return people, groups, _organization(cross)


def _flag(row: Mapping[str, object], camel: str, snake: str) -> bool:
    return _get(row, camel, snake) is True


def _access(reply: Mapping[str, object]) -> AccessState:
    state = _record(reply.get("state"))
    listed = _get(state, "availableRoles", "available_roles")
    roles = tuple(
        dict.fromkeys(
            role
            for role in (
                _role(value) for value in (listed if isinstance(listed, list) else [])
            )
            if role in ROLES
        )
    )
    people, groups, organization = _directories(reply)
    return AccessState(
        creator_user_id=_int(_get(reply, "creatorUserId", "creator_user_id")),
        viewer_user_id=_int(_get(reply, "viewerUserId", "viewer_user_id")),
        principals=tuple(_principal(row) for row in _rows(state.get("principals"))),
        available_roles=roles or ROLES,
        expected_state_token=_text(
            _get(state, "expectedStateToken", "expected_state_token")
        ),
        team_row_on=_flag(state, "teamRowOn", "team_row_on"),
        team_row_off_allowed=_flag(state, "teamRowOffAllowed", "team_row_off_allowed"),
        groups_enabled=_flag(state, "groupsEnabled", "groups_enabled"),
        cross_team_sharing_enabled=_flag(
            state, "crossTeamSharingEnabled", "cross_team_sharing_enabled"
        ),
        caller_may_edit_cross_team_rows=_flag(
            state, "callerMayEditCrossTeamRows", "caller_may_edit_cross_team_rows"
        ),
        people=people,
        groups=groups,
        organization_name=organization,
    )


def access(transport: Transport, bot_id: str) -> AccessState:
    return _access(
        transport.rpc(
            "GetGrokBotAgentAccess",
            {"agentId": bot_id, "listsCrossTierPrincipals": True},
        )
    )


def _encode(principal: Principal) -> dict[str, object]:
    if principal.kind not in _ROW_KEYS:
        raise ValueError(
            "This bot has an access row this version cannot change; use the Grok Bot app."
        )
    if principal.role not in ROLES:
        raise ValueError(
            "This bot has an access row with a role this version cannot change; use the Grok Bot app."
        )
    key = _ROW_KEYS[principal.kind][0]
    row: dict[str, object] = {}
    if principal.kind in ("team", "organization"):
        row[key] = {}
    else:
        value = _int(principal.ref)
        if value is None:
            raise ValueError("An access row needs an id.")
        # int32 ids are numbers; the int64 group id is a decimal string.
        row[key] = str(value) if principal.kind == "group" else value
    row["role"] = _ROLE_PREFIX + principal.role.upper()
    if principal.invited_as_email:
        row["invitedAsEmail"] = principal.invited_as_email
    return row


def update_access(
    transport: Transport,
    bot_id: str,
    principals: Sequence[Principal],
    expected_state_token: str,
) -> AccessState:
    """Replace the whole access list; the owner is implicit and never sent."""
    update: dict[str, object] = {
        "principals": [_encode(principal) for principal in principals],
        "expectedStateToken": expected_state_token,
        "listsCrossTierPrincipals": True,
    }
    return _access(
        transport.rpc("UpdateGrokBotAgentAccess", {"agentId": bot_id, "update": update})
    )


def with_principal(
    principals: Sequence[Principal], principal: Principal
) -> tuple[Principal, ...]:
    """Add a row, or set the role of the row that already has this kind and id."""
    if not any(p.key == principal.key for p in principals):
        return (*principals, principal)
    return tuple(
        replace(
            p,
            role=principal.role,
            invited_as_email=principal.invited_as_email or p.invited_as_email,
        )
        if p.key == principal.key
        else p
        for p in principals
    )


def without_principal(
    principals: Sequence[Principal], kind: str, ref: str | None = None
) -> tuple[Principal, ...]:
    if not any(p.key == (kind, ref) for p in principals):
        raise ValueError("That access row does not exist.")
    return tuple(p for p in principals if p.key != (kind, ref))


def with_role(
    principals: Sequence[Principal], kind: str, ref: str | None, role: str
) -> tuple[Principal, ...]:
    if role not in ROLES:
        raise ValueError("The role must be user or manager.")
    if not any(p.key == (kind, ref) for p in principals):
        raise ValueError("That access row does not exist.")
    return tuple(
        replace(p, role=role) if p.key == (kind, ref) else p for p in principals
    )


def with_team_row(
    state: AccessState, on: bool, role: str = "user"
) -> tuple[Principal, ...]:
    if role not in ROLES:
        raise ValueError("The role must be user or manager.")
    others = tuple(p for p in state.principals if p.kind != "team")
    if not on:
        if not state.team_row_off_allowed and not others:
            raise ValueError(
                "The team row cannot be turned off while nobody else has access to this bot."
            )
        return others
    existing = state.team_row()
    if existing is None:
        return (*state.principals, Principal("team", None, role))
    return tuple(
        replace(p, role=role) if p.kind == "team" else p for p in state.principals
    )


# Link access and visibility ---------------------------------------------------------------------------------


def link_access(transport: Transport, bot_id: str) -> str:
    reply = transport.rpc("GetGrokBotAgentLinkAccess", {"agentId": bot_id})
    value = _enum(reply.get("access"), _LINK)
    return "unknown" if value == "unspecified" else value


def make_team_visible(
    transport: Transport, bot_id: str, personal_secret_names: Sequence[str] = ()
) -> str:
    payload: dict[str, object] = {
        "agentId": bot_id,
        "visibility": "GROK_BOT_AGENT_VISIBILITY_TEAM",
    }
    if personal_secret_names:
        payload["personalSecretNames"] = list(personal_secret_names)
    outcome = _enum(
        transport.rpc("SetGrokBotAgentVisibility", payload).get("outcome"), _VISIBILITY
    )
    return "unknown" if outcome == "unspecified" else outcome


# Invites you send -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Invite:
    email: str = field(default="", repr=False)
    expires_at_ms: int = 0
    last_shared_at_ms: int = 0
    created_at_ms: int = 0


@dataclass(frozen=True)
class CapUsage:
    used: int = 0
    limit: int = 0


@dataclass(frozen=True)
class InviteResult:
    invite: Invite
    created: bool = False
    email_sent: bool = False
    grace_ms: int = 0
    cap_usage: CapUsage | None = None
    url: str = field(default="", repr=False)


def _invite(row: Mapping[str, object]) -> Invite:
    return Invite(
        _text(row.get("email")),
        _count(_get(row, "expiresAtMs", "expires_at_ms")),
        _count(_get(row, "lastSharedAtMs", "last_shared_at_ms")),
        _count(_get(row, "createdAtMs", "created_at_ms")),
    )


def _cap(value: object) -> CapUsage | None:
    if not isinstance(value, Mapping):
        return None
    return CapUsage(_count(value.get("used")), _count(value.get("limit")))


def invites(
    transport: Transport, bot_id: str
) -> tuple[tuple[Invite, ...], CapUsage | None]:
    reply = transport.rpc("ListGrokBotAgentAccessInvites", {"agentId": bot_id})
    return (
        tuple(_invite(row) for row in _rows(reply.get("invites"))),
        _cap(_get(reply, "capUsage", "cap_usage")),
    )


def check_email(email: str) -> str:
    email = email.strip()
    local, _, domain = email.partition("@")
    if not local or "." not in domain or any(c.isspace() for c in email):
        raise ValueError("Enter a valid email address.")
    return email


def create_invite(
    transport: Transport, bot_id: str, email: str, *, language: str | None = None
) -> InviteResult:
    """Invite by email; the server sends the message and the link is never shown."""
    payload: dict[str, object] = {
        "agentId": bot_id,
        "email": check_email(email),
        "sendEmail": True,
    }
    if language:
        payload["language"] = language
    reply = transport.rpc("CreateGrokBotAgentAccessInvite", payload)
    return InviteResult(
        _invite(_record(reply.get("invite"))),
        _get(reply, "inviteCreated", "invite_created") is True,
        _get(reply, "inviteEmailSent", "invite_email_sent") is True,
        _count(_get(reply, "graceMs", "grace_ms")),
        _cap(_get(reply, "capUsage", "cap_usage")),
        _text(_get(reply, "inviteUrl", "invite_url")),
    )


def revoke_invite(
    transport: Transport, bot_id: str, email: str
) -> tuple[int, CapUsage | None]:
    email = email.strip()
    if not email:
        raise ValueError("Name the invite's email address.")
    reply = transport.rpc(
        "RevokeGrokBotAgentAccessInvite", {"agentId": bot_id, "email": email}
    )
    return (
        _count(_get(reply, "revokedCount", "revoked_count")),
        _cap(_get(reply, "capUsage", "cap_usage")),
    )


# Invites you received -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class InviteItem:
    bot_id: str = ""
    bot_name: str = ""
    role: str = "unknown"
    state: str = ""
    outcome: str = ""
    expires_at_ms: int = 0


@dataclass(frozen=True)
class Eligibility:
    eligible: bool = False
    reason: str = ""
    current_tier: str = ""


@dataclass(frozen=True)
class InvitePreview:
    found: bool = False
    recipient_match: str = "unknown"
    sender_name: str = field(default="", repr=False)
    items: tuple[InviteItem, ...] = ()
    eligibility: Eligibility | None = None


@dataclass(frozen=True)
class AcceptResult:
    status: str = "unknown"
    items: tuple[InviteItem, ...] = ()


def invite_code(text: str) -> str:
    """The code from a pasted invite link (its `token` query parameter), else the trimmed text."""
    text = text.strip()
    if "://" in text:
        tokens = parse_qs(urlparse(text).query).get("token", [])
        token = next((value.strip() for value in tokens if value.strip()), "")
        if token:
            return token
    return text


def _known(value: str) -> str:
    return "" if value == "unspecified" else value


def _item(row: Mapping[str, object]) -> InviteItem:
    bot = _record(row.get("bot"))
    state = _enum(row.get("state"), _INVITE_STATE) if "state" in row else ""
    outcome = _enum(row.get("outcome"), _OUTCOME) if "outcome" in row else ""
    return InviteItem(
        _text(_get(bot, "agentId", "agent_id", "id")),
        _text(bot.get("name")),
        _role(row.get("role")),
        _known(state),
        _known(outcome),
        _count(_get(row, "expiresAtMs", "expires_at_ms")),
    )


def _eligibility(value: object) -> Eligibility | None:
    if not isinstance(value, Mapping):
        return None
    return Eligibility(
        value.get("eligible") is True,
        _known(_enum(value.get("reason"), _REASON)) if "reason" in value else "",
        _known(_enum(_get(value, "currentTier", "current_tier"), _TIER))
        if _get(value, "currentTier", "current_tier") is not None
        else "",
    )


def preview_invite(transport: Transport, code: str) -> InvitePreview:
    """Read what a code would grant. The request carries only the code, which is a secret."""
    reply = transport.rpc("PreviewGrokBotAgentAccessInvite", {"code": code})
    match = _enum(_get(reply, "recipientMatch", "recipient_match"), _MATCH)
    sender = _record(reply.get("sender"))
    return InvitePreview(
        reply.get("found") is True,
        "unknown" if match == "unspecified" else match,
        _text(_get(sender, "displayName", "display_name", "name")),
        tuple(_item(row) for row in _rows(reply.get("invites"))),
        _eligibility(reply.get("eligibility")),
    )


def accept_invite(transport: Transport, code: str) -> AcceptResult:
    reply = transport.rpc("AcceptGrokBotAgentAccessInvite", {"code": code})
    status = _enum(reply.get("status"), _STATUS)
    return AcceptResult(
        "unknown" if status == "unspecified" else status,
        tuple(_item(row) for row in _rows(reply.get("items"))),
    )


# Managers -----------------------------------------------------------------------------------------------------


def managers(transport: Transport, bot_id: str) -> tuple[int, ...]:
    reply = transport.rpc("ListGrokBotAgentManagers", {"agentId": bot_id})
    ids = _get(reply, "managerUserIds", "manager_user_ids")
    return tuple(
        user_id
        for user_id in (_int(value) for value in (ids if isinstance(ids, list) else []))
        if user_id is not None
    )


def _user_id(user_id: int) -> int:
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
        raise ValueError("A user id is a positive whole number.")
    return user_id


def add_manager(transport: Transport, bot_id: str, user_id: int) -> None:
    transport.rpc(
        "AddGrokBotAgentManager", {"agentId": bot_id, "userId": _user_id(user_id)}
    )


def remove_manager(transport: Transport, bot_id: str, user_id: int) -> None:
    transport.rpc(
        "RemoveGrokBotAgentManager", {"agentId": bot_id, "userId": _user_id(user_id)}
    )


# In place and clone ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class InPlaceStatus:
    state: str = "unknown"
    step: str = ""
    failure_reason: str = ""
    shared: bool = False


@dataclass(frozen=True)
class CloneResult:
    outcome: str = "unknown"
    agent_id: str = ""


def share_in_place(transport: Transport, bot_id: str) -> str:
    reply = transport.rpc("ShareGrokBotAgentInPlace", {"agentId": bot_id})
    outcome = _enum(reply.get("outcome"), _IN_PLACE)
    return "unknown" if outcome == "unspecified" else outcome


def in_place_status(transport: Transport, bot_id: str) -> InPlaceStatus:
    try:
        reply = transport.rpc("GetGrokBotAgentInPlaceShareStatus", {"agentId": bot_id})
    except ConnectError as error:
        reason = refusal(error)
        if reason is not None and reason.code == "not_found":
            return InPlaceStatus("not_started")
        raise
    state = _enum(reply.get("state"), _IN_PLACE_STATE)
    step = _enum(reply.get("step"), _IN_PLACE_STEP) if "step" in reply else ""
    return InPlaceStatus(
        "unknown" if state == "unspecified" else state,
        "" if step == "unspecified" else step,
        _text(_get(reply, "failureReason", "failure_reason")),
        reply.get("shared") is True,
    )


def next_poll_delay(previous: float | None) -> float:
    """Seconds before the next status read: 1, then 1.5 times the last, never more than 5."""
    if previous is None:
        return _POLL_FIRST_S
    return min(previous * _POLL_FACTOR, _POLL_CAP_S)


def clone_to_team(
    transport: Transport, bot_id: str, personal_secret_names: Sequence[str] = ()
) -> CloneResult:
    payload: dict[str, object] = {"agentId": bot_id}
    if personal_secret_names:
        payload["personalSecretNames"] = list(personal_secret_names)
    reply = transport.rpc("CloneGrokBotAgentToTeam", payload)
    outcome = _enum(reply.get("outcome"), _CLONE)
    agent = _record(reply.get("agent"))
    return CloneResult(
        "unknown" if outcome == "unspecified" else outcome,
        _text(_get(agent, "agentId", "agent_id", "id")),
    )


# One read for the CLI and the panel ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Overview:
    """Everything `gbot share BOT` and `/share` show; a refused part holds its message in `refused`."""

    access: AccessState | None = None
    link_access: str | None = None
    managers: tuple[int, ...] | None = None
    invites: tuple[Invite, ...] | None = None
    cap_usage: CapUsage | None = None
    refused: Mapping[str, str] = field(default_factory=dict)


def overview(transport: Transport, bot_id: str) -> Overview:
    refused: dict[str, str] = {}
    state, message = attempt(lambda: access(transport, bot_id))
    if message:
        refused["access"] = message
    link, message = attempt(lambda: link_access(transport, bot_id))
    if message:
        refused["link_access"] = message
    ids, message = attempt(lambda: managers(transport, bot_id))
    if message:
        refused["managers"] = message
    pending, message = attempt(lambda: invites(transport, bot_id))
    if message:
        refused["invites"] = message
    return Overview(
        state,
        link,
        ids,
        pending[0] if pending else None,
        pending[1] if pending else None,
        refused,
    )


_DEMO_PEOPLE = [
    {"userId": 2, "name": "Avery Chen"},
    {"userId": 3, "name": "Jordan Lee"},
]
_DEMO_ACCESS = {
    "creatorUserId": 1,
    "viewerUserId": 1,
    "state": {
        "availableRoles": [
            "GROK_BOT_ACCESS_ROLE_USER",
            "GROK_BOT_ACCESS_ROLE_MANAGER",
        ],
        "expectedStateToken": "demo-token",
        "principals": [
            {"team": {}, "role": "GROK_BOT_ACCESS_ROLE_USER"},
            {"userId": 2, "role": "GROK_BOT_ACCESS_ROLE_USER"},
            {"groupId": "7", "role": "GROK_BOT_ACCESS_ROLE_MANAGER"},
        ],
        "teamRowOn": True,
        "teamRowOffAllowed": True,
        "groupsEnabled": True,
    },
    "personalBotPeople": [{"userId": 1, "name": "Sam Rivera"}, *_DEMO_PEOPLE],
    "botTeamDirectory": {
        "people": _DEMO_PEOPLE,
        "groups": [{"groupId": "7", "name": "Design", "memberCount": 4}],
    },
}
DEMO_RPCS: dict[str, object] = {
    "GetGrokBotAgentAccess": _DEMO_ACCESS,
    "UpdateGrokBotAgentAccess": _DEMO_ACCESS,
    "GetGrokBotAgentLinkAccess": {"access": "GROK_BOT_AGENT_LINK_ACCESS_ALLOWED"},
    "SetGrokBotAgentVisibility": {"outcome": "NO_TEAM"},
    "ListGrokBotAgentManagers": {"managerUserIds": [3]},
    "AddGrokBotAgentManager": {},
    "RemoveGrokBotAgentManager": {},
    "ListGrokBotAgentAccessInvites": {
        "invites": [
            {
                "email": "invitee@example.invalid",
                "expiresAtMs": "1802592000000",
                "lastSharedAtMs": "1800000000000",
                "createdAtMs": "1800000000000",
            }
        ],
        "capUsage": {"used": 1, "limit": 10},
    },
    "CreateGrokBotAgentAccessInvite": lambda args: {
        "invite": {"email": args["email"], "expiresAtMs": "1802592000000"},
        "inviteCreated": True,
        "inviteEmailSent": True,
        "capUsage": {"used": 2, "limit": 10},
    },
    "RevokeGrokBotAgentAccessInvite": {
        "revokedCount": 1,
        "capUsage": {"used": 0, "limit": 10},
    },
    "PreviewGrokBotAgentAccessInvite": {
        "found": True,
        "recipientMatch": "MATCHES",
        "sender": {"displayName": "Avery Chen"},
        "invites": [
            {
                "bot": {"agentId": "demo-shared", "name": "Shared helper"},
                "role": "user",
                "state": "OPEN",
                "expiresAtMs": "1802592000000",
            }
        ],
        "eligibility": {"eligible": True},
    },
    "AcceptGrokBotAgentAccessInvite": {
        "status": "REDEEMED",
        "items": [
            {
                "bot": {"agentId": "demo-shared", "name": "Shared helper"},
                "role": "user",
                "outcome": "GRANTED",
            }
        ],
    },
    "ShareGrokBotAgentInPlace": {"outcome": "INELIGIBLE"},
    "GetGrokBotAgentInPlaceShareStatus": {"state": "NOT_STARTED"},
    "CloneGrokBotAgentToTeam": {"outcome": "NO_TEAM"},
}
