"""Where a bot's skills can be published, and skill and plugin listing changes."""

from collections.abc import Mapping
from dataclasses import dataclass

from .models import _record, _text
from .transport import Transport

COMMANDS = {
    "getSkillPublishTargets": "none",
    "publishSkill": "object",
    "resyncPublishedSkill": "object",
    "unpublishSkill": "object",
    "hasRestorablePluginListingCopy": "object",
    "unpublishPluginListing": "object",
}
DEMO_COMMANDS = {
    "getSkillPublishTargets": {
        "teams": [{"teamId": "demo-team", "name": "Demo team"}],
        "unavailableReason": "",
        "unavailableReasonKind": "",
    },
    "publishSkill": {"status": "published"},
    "resyncPublishedSkill": {"status": "synced"},
    "unpublishSkill": {"status": "unpublished"},
    "hasRestorablePluginListingCopy": True,
    "unpublishPluginListing": {"status": "unpublished"},
}
_STATE_KEYS = ("status", "state", "outcome", "kind")
# The reply shape is unknown, so a state word that says the change failed counts as a failure.
_FAILED_STATES = frozenset(
    {"failed", "failure", "error", "errored", "rejected", "denied"}
)


@dataclass(frozen=True)
class Target:
    team_id: str
    name: str


@dataclass(frozen=True)
class PublishTargets:
    teams: tuple[Target, ...]
    unavailable_reason: str = ""
    unavailable_kind: str = ""


@dataclass(frozen=True)
class ListingResult:
    ok: bool
    state: str = ""
    message: str = ""


def _target(value: object) -> Target | None:
    if isinstance(value, str):
        return Target(value, value) if value else None
    row = _record(value)
    team_id = row.get("teamId")
    if team_id is None or team_id == "":
        team_id = row.get("id")
    if isinstance(team_id, int) and not isinstance(team_id, bool):
        team_id = str(team_id)
    if not isinstance(team_id, str) or not team_id:
        return None
    return Target(team_id, _text(row.get("name")) or team_id)


def publish_targets(transport: Transport) -> PublishTargets:
    reply = _record(transport.command("getSkillPublishTargets"))
    teams = reply.get("teams")
    targets = [_target(item) for item in teams] if isinstance(teams, list) else []
    return PublishTargets(
        tuple(target for target in targets if target),
        _text(reply.get("unavailableReason")),
        _text(reply.get("unavailableReasonKind")),
    )


def _result(reply: object) -> ListingResult:
    if isinstance(reply, str):
        return ListingResult(True, "", reply.strip())
    if not isinstance(reply, Mapping):
        return ListingResult(True)
    state = next(
        (value for key in _STATE_KEYS if isinstance(value := reply.get(key), str)), ""
    )
    raw_error = reply.get("error")
    error = raw_error.get("message") if isinstance(raw_error, Mapping) else raw_error
    message = _text(reply.get("message")) or _text(error)
    failed = (
        bool(_text(error))
        or (isinstance(raw_error, Mapping) and bool(raw_error))
        or reply.get("ok") is False
        or state.strip().casefold().rsplit("_", 1)[-1] in _FAILED_STATES
    )
    return ListingResult(not failed, state.strip(), message.strip())


def publish_skill(
    transport: Transport, workflow_id: str, team_id: str | None = None
) -> ListingResult:
    payload: dict[str, object] = {"workflowId": workflow_id}
    if team_id is not None:
        payload["teamId"] = team_id
    return _result(transport.command("publishSkill", payload))


def resync_skill(transport: Transport, workflow_id: str) -> ListingResult:
    return _result(
        transport.command("resyncPublishedSkill", {"workflowId": workflow_id})
    )


def unpublish_skill(transport: Transport, workflow_id: str) -> ListingResult:
    return _result(transport.command("unpublishSkill", {"workflowId": workflow_id}))


def has_restorable_copy(transport: Transport, plugin_id: str) -> bool:
    reply = transport.command("hasRestorablePluginListingCopy", {"pluginId": plugin_id})
    return reply is True


def unpublish_plugin_listing(
    transport: Transport, plugin_id: str, team_id: str | None = None
) -> ListingResult:
    payload: dict[str, object] = {"pluginId": plugin_id}
    if team_id is not None:
        payload["teamId"] = team_id
    return _result(transport.command("unpublishPluginListing", payload))
