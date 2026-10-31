"""Read public templates and import them without fetching recipe blobs."""

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from groken.client import ConnectError

from . import conversation
from .models import Bot, _record, _strings, _text
from .transport import Transport

COMMANDS = {
    "createAgentFromTemplate": "object",
    "getBotTemplateForSourceAgent": "object",
    "getBotTemplateExportPolicy": "none",
}
RPCS = (
    "ListPublicGrokBotMarketplaceListings",
    "GetGrokBotTemplateImportDetails",
    "CreateGrokBotAgentFromTemplate",
    "GetGrokBotTemplateForSourceAgent",
    "GetGrokBotTemplateExportPolicy",
)
_TEMPLATE = {
    "shareId": "demo-template",
    "name": "Helper",
    "description": "A helpful bot",
    "avatarShape": "blob",
    "avatarColor": "blue",
}
DEMO_COMMANDS = {
    "createAgentFromTemplate": lambda args: {
        "agent": {"id": args["agentId"], "name": args["name"], "harness": "box"},
        "setup": {"kind": "unavailable"},
    },
    "getBotTemplateForSourceAgent": _TEMPLATE,
    "getBotTemplateExportPolicy": {"exportPolicy": "all"},
}
DEMO_RPCS = {
    "ListPublicGrokBotMarketplaceListings": {
        "featuredListings": [],
        "listings": [
            {
                **_TEMPLATE,
                "slug": "helper",
                "category": "Productivity",
                "categories": ["Productivity"],
                "creator": {"name": "Demo"},
            }
        ],
        "allCategoriesOrder": ["Productivity"],
    },
    "GetGrokBotTemplateImportDetails": {
        "template": _TEMPLATE,
        "expectedActiveVersion": 1,
        "creatorDisplayName": "Demo",
    },
    "CreateGrokBotAgentFromTemplate": lambda args: {
        "agent": {"agentId": args["agentId"], "name": "Helper", "harness": "TEMPORAL"},
        "setupHandledByServer": True,
    },
    "GetGrokBotTemplateForSourceAgent": {"template": _TEMPLATE},
    "GetGrokBotTemplateExportPolicy": {"exportPolicy": "all"},
}


@dataclass(frozen=True)
class Listing:
    slug: str
    name: str
    description: str
    category: str
    categories: tuple[str, ...]
    share_id: str
    creator_name: str
    default_avatar: Mapping[str, object]
    image_url: str = ""


@dataclass(frozen=True)
class Marketplace:
    featured_listings: tuple[Listing, ...]
    listings: tuple[Listing, ...]
    category_order: tuple[str, ...]


@dataclass(frozen=True)
class TemplateDetails:
    template: Mapping[str, object]
    expected_active_version: int
    creator_display_name: str


@dataclass(frozen=True)
class TemplateResult:
    bot: Bot
    setup_handled_by_server: bool
    note: str = ""


def marketplace(transport: Transport, category: str | None = None) -> Marketplace:
    featured: list[Listing] = []
    listings: list[Listing] = []
    categories: list[str] = []
    token = ""
    for _ in range(20):
        payload: dict[str, object] = {"pageSize": 100, "pageToken": token}
        if category is not None:
            payload["category"] = category
        reply = transport.rpc("ListPublicGrokBotMarketplaceListings", payload)
        for key, target in (("featuredListings", featured), ("listings", listings)):
            rows = reply.get(key)
            for row in rows if isinstance(rows, list) else []:
                data = _record(row)
                target.append(
                    Listing(
                        _text(data.get("slug")),
                        _text(data.get("name")),
                        _text(data.get("description")),
                        _text(data.get("category")),
                        _strings(data.get("categories")),
                        _text(data.get("shareId")),
                        _text(_record(data.get("creator")).get("name")),
                        dict(_record(data.get("defaultAvatar"))),
                        _text(data.get("imageUrl")),
                    )
                )
        for item in _strings(reply.get("allCategoriesOrder")):
            if item not in categories:
                categories.append(item)
        token = _text(reply.get("nextPageToken"))
        if not token:
            break
    return Marketplace(tuple(featured), tuple(listings), tuple(categories))


def details(transport: Transport, share_id: str) -> TemplateDetails:
    reply = transport.rpc("GetGrokBotTemplateImportDetails", {"shareId": share_id})
    template, version = (
        _record(reply.get("template")),
        reply.get("expectedActiveVersion"),
    )
    if not _text(template.get("shareId")) or type(version) is not int or version < 1:
        raise ValueError("Template is missing or has no active version.")
    return TemplateDetails(
        dict(template), version, _text(reply.get("creatorDisplayName"))
    )


def _unimplemented(exc: ConnectError) -> bool:
    try:
        body = json.loads(exc.body)
    except (ValueError, TypeError):
        return exc.body.strip().casefold() == "unimplemented"
    return isinstance(body, dict) and body.get("code") == "unimplemented"


def create_from_template(
    transport: Transport,
    details: TemplateDetails,
    *,
    agent_id: str | None = None,
    language: str | None = None,
) -> TemplateResult:
    agent_id = agent_id or str(uuid.uuid4())
    template = details.template
    payload: dict[str, object] = {
        "agentId": agent_id,
        "shareId": template["shareId"],
        "expectedActiveVersion": details.expected_active_version,
        "setupDelegationSupported": True,
    }
    if language is not None:
        payload["language"] = language
    backend = True
    try:
        reply = transport.rpc("CreateGrokBotAgentFromTemplate", payload)
    except ConnectError as exc:
        if not _unimplemented(exc):
            raise
        backend = False
        args = {
            key: value
            for key, value in payload.items()
            if key != "setupDelegationSupported"
        }
        args.update(
            {
                key: template.get(key, "")
                for key in ("name", "avatarShape", "avatarColor")
            }
        )
        reply = dict(_record(transport.command("createAgentFromTemplate", args)))
    row = dict(_record(reply.get("agent")))
    if backend:
        if row.get("agentId") != agent_id or row.get("harness") not in (
            "temporal",
            "TEMPORAL",
            2,
        ):
            raise ValueError(
                "Template import returned a different agent id or harness."
            )
        row = {
            **row,
            "serverId": row.get("id"),
            "id": row["agentId"],
            "harness": "temporal",
        }
    bot = Bot.from_row(row)
    if bot is None or bot.id != agent_id:
        raise ValueError("Template import returned a different or invalid agent id.")
    handled = backend and reply.get("setupHandledByServer") is True
    return TemplateResult(
        bot,
        handled,
        "" if handled else "Finish this template's setup in the Grok Bot app",
    )


def template_for_bot(transport: Transport, bot: Bot) -> object:
    args = {"sourceAgentId": bot.id}
    if bot.raw.get("harness") == "temporal":
        return transport.rpc("GetGrokBotTemplateForSourceAgent", args)
    return transport.command("getBotTemplateForSourceAgent", args)


def export_policy(transport: Transport) -> object:
    if any(
        bot.raw.get("harness") == "temporal" for bot in conversation.roster(transport)
    ):
        return transport.rpc("GetGrokBotTemplateExportPolicy", {})
    return transport.command("getBotTemplateExportPolicy")
