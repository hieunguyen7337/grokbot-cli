"""List a bot in the marketplace or take it off, and manage the bot's own template."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from groken.client import ConnectError

from . import templates
from .errors import refusal
from .models import Bot, _record, _text
from .transport import Transport

# Declared for parity only: the desktop maps both to the first two RPCs below, so this module calls the RPCs.
COMMANDS = {"publishBotTemplate": "object", "deleteBotTemplate": "object"}
RPCS = frozenset(
    (
        "ActivateGrokBotTemplateVersion",
        "DeleteGrokBotTemplate",
        "SetGrokBotTemplateVisibility",
        "PublishGrokBotAgent",
        "UnpublishGrokBotAgent",
    )
)
VISIBILITIES = ("unspecified", "public", "team")
POLICIES = ("all", "team_only", "none")
PUBLISH_OUTCOMES = (
    "unspecified",
    "published",
    "already_published",
    "not_shared",
    "unsupported_harness",
)
UNPUBLISH_OUTCOMES = (
    "unspecified",
    "unpublished",
    "not_published",
    "not_shared",
    "unsupported_harness",
)
_VISIBILITY_PREFIX = "GROK_BOT_TEMPLATE_VISIBILITY_"
_TEMPLATE = {
    "shareId": "demo-template",
    "name": "Helper",
    "description": "A helpful bot",
    "published": True,
    "activeVersion": 1,
    "visibility": "GROK_BOT_TEMPLATE_VISIBILITY_TEAM",
}
DEMO_RPCS = {
    "ActivateGrokBotTemplateVersion": lambda args: {
        "template": {**_TEMPLATE, "activeVersion": args.get("version", 1)}
    },
    "DeleteGrokBotTemplate": {},
    "SetGrokBotTemplateVisibility": lambda args: {
        "template": {**_TEMPLATE, "visibility": args["visibility"]}
    },
    "PublishGrokBotAgent": {
        "agent": {"publishedAt": "1800000000000"},
        "outcome": "GROK_BOT_PUBLISH_AGENT_OUTCOME_PUBLISHED",
    },
    "UnpublishGrokBotAgent": {
        "outcome": "GROK_BOT_UNPUBLISH_AGENT_OUTCOME_UNPUBLISHED"
    },
}

_POLICY_SENTENCES = {
    "all": "Templates can be shared publicly or with your team.",
    "team_only": "Templates can be shared with your team only.",
    "none": "Publishing templates is turned off for this account.",
    "unknown": "The template sharing policy is not known.",
}
_OUTCOME_SENTENCES = {
    "published": "The bot is listed in the Grok Bot marketplace.",
    "already_published": "The bot was already listed in the Grok Bot marketplace.",
    "unpublished": "The bot was taken off the Grok Bot marketplace.",
    "not_published": "The bot was not listed in the Grok Bot marketplace.",
    "not_shared": "Share the bot first, then list it in the marketplace.",
    "unsupported_harness": "This kind of bot cannot be listed in the marketplace.",
    "unknown": "The marketplace returned a result this version does not recognise.",
}


def _enum(value: object, names: Sequence[str]) -> str:
    """The lowercase short name of an enum sent as a full name, a short name or a number."""
    if isinstance(value, bool):
        return "unknown"
    if isinstance(value, int):
        name = names[value] if 0 <= value < len(names) else ""
    elif isinstance(value, str):
        text = value.strip().lower()
        if text.isdecimal():
            return _enum(int(text), names)
        # Full names carry a long prefix; the longest short name that ends the text wins.
        name = max(
            (item for item in names if text == item or text.endswith("_" + item)),
            key=len,
            default="",
        )
    else:
        name = ""
    return name if name and name != "unspecified" else "unknown"


def _int64(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdecimal():
        return int(value)
    return None


@dataclass(frozen=True)
class OwnTemplate:
    share_id: str
    name: str
    description: str
    published: bool
    active_version: int | None
    visibility: str
    source_agent_id: str
    created_at_ms: int | None
    updated_at_ms: int | None


@dataclass(frozen=True)
class PublishResult:
    outcome: str
    published_at_ms: int | None = None

    @property
    def sentence(self) -> str:
        return outcome_sentence(self.outcome)


@dataclass(frozen=True)
class Overview:
    """Everything the CLI and the panel show about one bot's publishing state."""

    listing: str
    published_at_ms: int | None
    template: OwnTemplate | None
    policy: str
    notes: tuple[str, ...] = ()


def policy_sentence(policy: str) -> str:
    return _POLICY_SENTENCES.get(policy, _POLICY_SENTENCES["unknown"])


def outcome_sentence(outcome: str) -> str:
    return _OUTCOME_SENTENCES.get(outcome, _OUTCOME_SENTENCES["unknown"])


def _template(value: object) -> OwnTemplate | None:
    data = _record(value)
    share_id = _text(data.get("shareId"))
    if not share_id:
        return None
    version = _int64(data.get("activeVersion"))
    return OwnTemplate(
        share_id,
        _text(data.get("name")),
        _text(data.get("description")),
        data.get("published") is True,
        version if version else None,
        _enum(data.get("visibility"), VISIBILITIES),
        _text(data.get("sourceAgentId")),
        _int64(data.get("createdAtMs")),
        _int64(data.get("updatedAtMs")),
    )


def _own(reply: object) -> OwnTemplate | None:
    """A template reply is either {template: {...}} or the template itself."""
    data = _record(reply)
    return _template(data.get("template")) or _template(data)


def _template_reply(reply: object, share_id: str) -> OwnTemplate:
    found = _own(reply)
    if found is not None:
        return found
    return OwnTemplate(share_id, "", "", False, None, "unknown", "", None, None)


def listing_state(bot: Bot) -> tuple[str, int | None]:
    """The roster's marketplace state: published, unpublished or unknown, and the published-at time."""
    for key in ("publishedAtMs", "publishedAt"):
        if key in bot.raw:
            stamp = _int64(bot.raw[key])
            return ("published", stamp) if stamp else ("unpublished", None)
    return "unknown", None


def _policy(reply: object) -> str:
    return _enum(_record(reply).get("exportPolicy"), POLICIES)


def bot_template(transport: Transport, bot: Bot) -> tuple[OwnTemplate | None, str]:
    """The bot's template and the account's export policy (all, team_only, none or unknown)."""
    found = _own(templates.template_for_bot(transport, bot))
    return found, _policy(templates.export_policy(transport))


def overview(transport: Transport, bot: Bot) -> Overview:
    """Read the bot's publishing state; a refused part becomes a note and the read still succeeds."""
    notes: list[str] = []
    found: OwnTemplate | None = None
    policy = "unknown"
    try:
        found = _own(templates.template_for_bot(transport, bot))
    except ConnectError as error:
        refused = refusal(error)
        if refused is None:
            raise
        notes.append(refused.message)
    try:
        policy = _policy(templates.export_policy(transport))
    except ConnectError as error:
        refused = refusal(error)
        if refused is None:
            raise
        notes.append(refused.message)
    state, stamp = listing_state(bot)
    return Overview(state, stamp, found, policy, tuple(notes))


def publish_template(
    transport: Transport, share_id: str, version: int | None = None
) -> OwnTemplate:
    payload: dict[str, object] = {"shareId": share_id}
    if version is not None:
        payload["version"] = version
    return _template_reply(
        transport.rpc("ActivateGrokBotTemplateVersion", payload), share_id
    )


def set_template_visibility(
    transport: Transport, share_id: str, visibility: str
) -> OwnTemplate:
    name = visibility.strip().lower().removeprefix(_VISIBILITY_PREFIX.lower())
    if name not in ("public", "team"):
        raise ValueError("Visibility must be public or team.")
    reply = transport.rpc(
        "SetGrokBotTemplateVisibility",
        {"shareId": share_id, "visibility": _VISIBILITY_PREFIX + name.upper()},
    )
    return _template_reply(reply, share_id)


def delete_template(transport: Transport, share_id: str) -> None:
    transport.rpc("DeleteGrokBotTemplate", {"shareId": share_id})


def _result(reply: Mapping[str, object], names: Sequence[str]) -> PublishResult:
    stamp = _int64(_record(reply.get("agent")).get("publishedAt"))
    if stamp is None:
        stamp = _int64(_record(reply.get("agent")).get("publishedAtMs"))
    return PublishResult(_enum(reply.get("outcome"), names), stamp or None)


def publish_bot(transport: Transport, bot_id: str) -> PublishResult:
    return _result(
        transport.rpc("PublishGrokBotAgent", {"agentId": bot_id}), PUBLISH_OUTCOMES
    )


def unpublish_bot(transport: Transport, bot_id: str) -> PublishResult:
    return _result(
        transport.rpc("UnpublishGrokBotAgent", {"agentId": bot_id}),
        UNPUBLISH_OUTCOMES,
    )
