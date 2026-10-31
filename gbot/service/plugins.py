"""Catalog projection and write-only per-bot plugin settings."""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .models import _record, _strings, _text
from .transport import Transport

COMMANDS = {"getMcpCatalog": "none"}
RPCS = (
    "GetGrokBotAgentPlugins",
    "SetGrokBotAgentPlugins",
    "SetGrokBotAgentPluginVariables",
)
_DEMO = {
    "pluginId": "12",
    "name": "notes",
    "displayName": "Notes",
    "description": "Search and organize notes",
    "variableNames": ["api_token"],
    "mcpServerNames": ["Notes"],
    "skills": [{"name": "Find notes"}],
}
DEMO_COMMANDS = {
    "getMcpCatalog": [
        {
            "id": "12",
            "name": "notes",
            "displayName": "Notes",
            "description": "Search and organize notes",
            "category": "Productivity",
            "categoryKeys": ["productivity"],
            "publisher": {"displayName": "Demo"},
            "connectors": [{"name": "Notes"}],
            "fields": [{"key": "api_token", "label": "API token", "isSecret": True}],
        },
        {
            "id": "13",
            "name": "weather",
            "displayName": "Weather",
            "category": "Utilities",
            "publisher": {"displayName": "Demo"},
            "connectors": [{"name": "Weather"}],
        },
    ]
}
DEMO_RPCS = {name: {"plugins": [_DEMO]} for name in RPCS}


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    hint: str = ""
    type: str = "string"
    required: bool = False
    secret: bool = False
    options: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    name: str
    display_name: str
    description: str
    category: str
    category_keys: tuple[str, ...]
    publisher: str
    popularity_rank: int | None
    connector_names: tuple[str, ...]
    fields: tuple[Field, ...]


@dataclass(frozen=True)
class Plugin:
    plugin_id: int
    name: str
    display_name: str
    description: str
    install_mode: str
    variable_names: tuple[str, ...]
    is_deprecated: bool
    skill_names: tuple[str, ...]
    server_names: tuple[str, ...]
    is_bot_skills: bool
    has_configured_variables: bool
    credential_source: str
    owned_by_marketplace: bool
    variables_schema: Mapping[str, object] = field(repr=False)


def _secret(name: str) -> bool:
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    parts = re.sub(r"([a-z])([A-Z])", r"\1_\2", name).casefold()
    return bool(
        set(re.split(r"[^a-z0-9]+", parts))
        & {"credential", "key", "passphrase", "password", "secret", "token"}
    )


def _field(row: Mapping[str, object]) -> Field:
    key = _text(row.get("key"))
    return Field(
        key,
        _text(row.get("label")) or key,
        _text(row.get("hint")),
        _text(row.get("type")) or "string",
        bool(row.get("isRequired")),
        bool(row.get("isSecret")) or _secret(key),
        tuple(
            (_text(r.get("label")), _text(r.get("rawValue")))
            for r in _rows(row.get("options"))
        ),
    )


def _rows(value: object) -> list[Mapping[str, object]]:
    return [_record(row) for row in value] if isinstance(value, list) else []


def catalog(transport: Transport) -> list[CatalogEntry]:
    entries = []
    for row in _rows(transport.command("getMcpCatalog")):
        publisher = _record(row.get("publisher"))
        rank = row.get("popularityRank")
        entries.append(
            CatalogEntry(
                _text(row.get("id")),
                _text(row.get("name") or row.get("pluginName")),
                _text(row.get("displayName") or row.get("name")),
                _text(row.get("description")),
                _text(row.get("category")),
                tuple(
                    dict.fromkeys(
                        (
                            *_strings(row.get("categoryKeys")),
                            *_strings([row.get("categoryKey")]),
                        )
                    )
                ),
                _text(publisher.get("displayName") or publisher.get("name")),
                rank if type(rank) is int else None,
                tuple(_text(r.get("name")) for r in _rows(row.get("connectors"))),
                tuple(_field(r) for r in _rows(row.get("fields"))),
            )
        )
    return sorted(
        entries,
        key=lambda e: (
            e.popularity_rank is None,
            e.popularity_rank or 0,
            e.display_name.casefold(),
        ),
    )


def find_entry(entries: Sequence[CatalogEntry], query: str) -> CatalogEntry:
    matches = [
        e
        for e in entries
        if query.casefold()
        in {e.id.casefold(), e.name.casefold(), e.display_name.casefold()}
    ]
    if len(matches) != 1:
        raise ValueError(
            "Choose a catalog entry: "
            + ", ".join(f"{e.display_name} ({e.id})" for e in matches or entries)
        )
    return matches[0]


def _schema(value: object) -> Mapping[str, object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    # Project schema metadata only: defaults/examples may contain stored values.
    row = _record(value)
    return (
        {
            "required": _strings(row.get("required")),
            "properties": {
                key: {
                    k: v
                    for k, v in _record(prop).items()
                    if k
                    in {
                        "title",
                        "description",
                        "type",
                        "writeOnly",
                        "format",
                        "isSecret",
                    }
                }
                for key, prop in _record(row.get("properties")).items()
            },
        }
        if row
        else {}
    )


def _plugins(reply: Mapping[str, object]) -> list[Plugin]:
    result = []
    for row in _rows(reply.get("plugins")):
        result.append(
            Plugin(
                int(str(row.get("pluginId", 0))),
                _text(row.get("name")),
                _text(row.get("displayName") or row.get("name")),
                _text(row.get("description")),
                _text(row.get("installMode")),
                _strings(row.get("variableNames")),
                bool(row.get("isDeprecated")),
                tuple(_text(r.get("name")) for r in _rows(row.get("skills"))),
                _strings(row.get("mcpServerNames")),
                bool(row.get("isBotSkills")),
                bool(row.get("hasConfiguredVariables")),
                _text(row.get("credentialSource")),
                bool(row.get("ownedByMarketplace")),
                _schema(row.get("variablesJson")),
            )
        )
    return result


def bot_plugins(transport: Transport, bot_id: str) -> list[Plugin]:
    return _plugins(
        transport.rpc(
            "GetGrokBotAgentPlugins",
            {
                "agentId": bot_id,
                "includeMcpConfig": False,
            },
        )
    )


def _id(value: object) -> int:
    text = str(value)
    if not text.isascii() or not text.isdecimal() or int(text) <= 0:
        raise ValueError("Add this plugin in the Grok Bot app.")
    return int(text)


def add_plugin(
    transport: Transport, bot_id: str, entry_or_id: CatalogEntry | str | int
) -> list[Plugin]:
    plugin_id = _id(
        entry_or_id.id if isinstance(entry_or_id, CatalogEntry) else entry_or_id
    )
    current = bot_plugins(transport, bot_id)
    if any(p.plugin_id == plugin_id for p in current):
        raise ValueError("Bot already has this plugin.")
    return _replace(transport, bot_id, [p.plugin_id for p in current] + [plugin_id])


def _replace(transport: Transport, bot_id: str, ids: list[int]) -> list[Plugin]:
    # The list is resent whole; a plugin without a catalog id cannot be resent as one.
    if any(i <= 0 for i in ids):
        raise ValueError("Change this bot's plugins in the Grok Bot app.")
    return _plugins(
        transport.rpc(
            "SetGrokBotAgentPlugins",
            {
                "agentId": bot_id,
                "plugins": [{"pluginId": str(i)} for i in ids],
            },
        )
    )


def remove_plugin(transport: Transport, bot_id: str, plugin_id: int) -> list[Plugin]:
    current = bot_plugins(transport, bot_id)
    if not any(p.plugin_id == plugin_id for p in current):
        raise ValueError("Unknown plugin id.")
    return _replace(
        transport, bot_id, [p.plugin_id for p in current if p.plugin_id != plugin_id]
    )


def variable_fields(plugin: Plugin, entry: CatalogEntry | None = None) -> list[Field]:
    properties = _record(plugin.variables_schema.get("properties"))
    if properties:
        raw_required = plugin.variables_schema.get("required", ())
        required = raw_required if isinstance(raw_required, (list, tuple)) else ()
        return [
            Field(
                key,
                _text(_record(prop).get("title")) or key,
                _text(_record(prop).get("description")),
                _text(_record(prop).get("type")) or "string",
                key in required,
                _secret(key)
                or bool(_record(prop).get("writeOnly"))
                or bool(_record(prop).get("isSecret"))
                or _record(prop).get("format") == "password",
            )
            for key, prop in properties.items()
        ]
    if entry and entry.fields:
        return list(entry.fields)
    return [Field(name, name, secret=_secret(name)) for name in plugin.variable_names]


def set_variables(
    transport: Transport, bot_id: str, plugin_id: int, values: Mapping[str, object]
) -> Plugin:
    filled = {key: value for key, value in values.items() if value not in ("", None)}
    if not filled:
        raise ValueError("Fill in at least one setting.")
    try:
        reply = transport.rpc(
            "SetGrokBotAgentPluginVariables",
            {
                "agentId": bot_id,
                "pluginId": str(plugin_id),
                "variables": filled,
                "mergeWithStored": True,
            },
        )
        return next(p for p in _plugins(reply) if p.plugin_id == plugin_id)
    except Exception:  # noqa: BLE001 - settings are a secret redaction boundary
        raise ValueError(
            "Plugin settings were not saved successfully; no values are displayed."
        ) from None
    finally:
        filled = {}
