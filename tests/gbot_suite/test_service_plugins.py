import json
from dataclasses import asdict, replace

import pytest

from gbot.service import plugins as p
from gbot.service.transport import FakeTransport


def fake():
    return FakeTransport(p.DEMO_COMMANDS, p.DEMO_RPCS)


def test_catalog_order_and_lookup():
    transport = fake()
    rows = p.catalog(transport)
    assert [r.display_name for r in rows] == ["Notes", "Weather"]
    assert rows[0].publisher == "Demo"
    assert rows[0].connector_names == ("Notes",)
    assert rows[0].fields[0].secret
    for query in ("12", "NOTES", "Notes"):
        assert p.find_entry(rows, query) == rows[0]
    with pytest.raises(ValueError, match="Notes.*Weather"):
        p.find_entry(rows, "absent")
    with pytest.raises(ValueError, match="Notes"):
        p.find_entry([*rows, rows[0]], "notes")
    transport.commands["getMcpCatalog"] = [
        {"id": "2", "displayName": "Z", "popularityRank": 2},
        {"id": "3", "displayName": "B", "popularityRank": 1},
        {"id": "4", "displayName": "A", "popularityRank": 1},
        {"id": "5", "displayName": "Missing"},
    ]
    assert [r.id for r in p.catalog(transport)] == ["4", "3", "2", "5"]


def test_projection_and_replace_preserves_hidden_plugins():
    transport = fake()
    transport.rpcs["GetGrokBotAgentPlugins"] = {
        "plugins": [
            {
                **p._DEMO,
                "mcpConfigJson": "private-test",
                "delegatedCredential": "private-test",
            },
            {"pluginId": "99", "isBotSkills": True},
        ]
    }
    rows = p.bot_plugins(transport, "gateway")
    assert "private-test" not in repr(rows) + str(asdict(rows[0]))
    assert transport.calls[-1][2] == {"agentId": "gateway", "includeMcpConfig": False}
    p.add_plugin(transport, "gateway", "13")
    assert transport.calls[-1][2] == {
        "agentId": "gateway",
        "plugins": [{"pluginId": "12"}, {"pluginId": "99"}, {"pluginId": "13"}],
    }
    p.remove_plugin(transport, "gateway", 12)
    assert transport.calls[-1][2]["plugins"] == [{"pluginId": "99"}]
    with pytest.raises(ValueError, match="Unknown"):
        p.remove_plugin(transport, "gateway", 888)
    for value in ("abc", "0", "-1", "1.2", True):
        count = len(transport.calls)
        with pytest.raises(ValueError, match="Grok Bot app"):
            p.add_plugin(transport, "gateway", value)
        assert len(transport.calls) == count
    with pytest.raises(ValueError, match="already"):
        p.add_plugin(transport, "gateway", "12")
    assert transport.calls[-1][1] == "GetGrokBotAgentPlugins"
    transport.rpcs["GetGrokBotAgentPlugins"] = {"serviceAccountsEnabled": True}
    assert p.bot_plugins(transport, "gateway") == []


def test_fields_and_write_only_values():
    transport = fake()
    plugin = p.bot_plugins(transport, "b")[0]
    assert p.variable_fields(plugin)[0].secret
    entry = p.catalog(transport)[0]
    assert p.variable_fields(plugin, entry)[0].label == "API token"
    schema = {
        "required": ["account"],
        "properties": {
            "account": {
                "title": "Account",
                "type": "string",
                "default": "private-test",
            },
            "one": {"writeOnly": True},
            "two": {"format": "password"},
            "three": {"isSecret": True},
            "apiKey": {},
            "APIKey": {},
            "access-token": {},
        },
    }
    transport.rpcs["GetGrokBotAgentPlugins"] = {
        "plugins": [{**p._DEMO, "variablesJson": json.dumps(schema)}]
    }
    plugin = p.bot_plugins(transport, "b")[0]
    fields = p.variable_fields(plugin, entry)
    assert fields[0].required and fields[0].label == "Account"
    assert all(f.secret for f in fields[1:])
    assert "private-test" not in repr(plugin) + str(asdict(plugin))
    names = replace(
        plugin,
        variables_schema={},
        variable_names=(
            "credential",
            "passphrase",
            "password",
            "secret",
            "token",
            "key",
            "monkey",
        ),
    )
    assert [f.secret for f in p.variable_fields(names)] == [True] * 6 + [False]
    with pytest.raises(ValueError, match="at least one"):
        p.set_variables(transport, "b", 12, {"blank": ""})
    result = p.set_variables(
        transport, "b", 12, {"api_token": "private-test", "blank": ""}
    )
    assert transport.calls[-1][2] == {
        "agentId": "b",
        "pluginId": "12",
        "variables": {"api_token": "private-test"},
        "mergeWithStored": True,
    }
    assert "private-test" not in repr(result)
    assert all(
        "private-test" not in repr(call)
        for call in transport.calls
        if call[1] != "SetGrokBotAgentPluginVariables"
    )
    transport.rpcs["SetGrokBotAgentPluginVariables"] = RuntimeError("private-test")
    with pytest.raises(ValueError) as error:
        p.set_variables(transport, "b", 12, {"token": "private-test"})
    assert "private-test" not in str(error.value)


def test_plugin_without_catalog_id_blocks_list_rewrite():
    t = fake()
    t.rpcs["GetGrokBotAgentPlugins"] = {"plugins": [{"name": "inline"}]}
    with pytest.raises(ValueError, match="Grok Bot app"):
        p.add_plugin(t, "bot", "12")
    assert all(name != "SetGrokBotAgentPlugins" for _, name, _ in t.calls)
