from dataclasses import asdict, replace
from threading import Event

import pytest

from gbot.service import connectors as c
from gbot.service.handoff import wait_until
from gbot.service.transport import FakeTransport


def fake():
    return FakeTransport(
        c.DEMO_COMMANDS, {**c.DEMO_RPCS, "GetGrokBotUserRuntimeSettings": {}}
    )


def test_safe_rows_and_find():
    t = fake()
    t.commands["getMcpState"] = {
        "servers": [
            {
                "id": "one",
                "name": "Mail",
                "serverIdentifier": "mail-id",
                "pluginDisplayName": "Email",
                "command": "SECRET-COMMAND",
                "url": "SECRET-URL",
                "statusDetail": {"kind": "authentication_required"},
            }
        ]
    }
    row = c.servers(t)[0]
    assert "SECRET" not in repr(row)
    assert "command" not in asdict(row) and "url" not in asdict(row)
    for query in ("ONE", "MAIL", "mail-ID", "EMAIL"):
        assert c.find([row], query) == row
    for rows, query in (([row], "missing"), ([row, replace(row, id="two")], "Mail")):
        with pytest.raises(ValueError, match="Mail"):
            c.find(rows, query)


@pytest.mark.parametrize("kind,sentence", c.STATUSES.items())
def test_status(kind, sentence):
    row = c.servers(fake())[0]
    assert c.status_sentence(replace(row, status_kind=kind)) == sentence
    assert (
        c.status_sentence(replace(row, status_kind="future", status="ready")) == "ready"
    )


def test_tools_policy_and_whole_map():
    t = fake()
    assert c.tools(t, "s")[0] == c.Tool(
        "search", "", False, True, "needs_approval", "auto_review"
    )
    t.rpcs["GetGrokBotUserRuntimeSettings"] = {
        "settings": {
            "toolPermissions": {
                "scopes": {
                    "s": {
                        "tools": {
                            "keep": 1,
                            "change": "GROK_BOT_TOOL_PERMISSION_BLOCKED",
                            "auto": 0,
                            "future": 99,
                        },
                        "reads": 0,
                        "writes": "GROK_BOT_TOOL_PERMISSION_NEEDS_APPROVAL",
                    }
                }
            }
        }
    }
    expected = c.Policy(
        {"keep": "always_allow", "change": "blocked", "future": "needs_approval"},
        None,
        "needs_approval",
    )
    assert c.policy(t, "s") == expected
    t.rpcs["SetGrokBotMcpToolPermissions"] = {
        "server": {"policy": {"tools": {"keep": 1}, "reads": 3}}
    }
    assert c.set_permission(t, "s", tool=("change", "auto")) == c.Policy(
        {"keep": "always_allow"}, "blocked"
    )
    assert t.calls[-1] == (
        "rpc",
        "SetGrokBotMcpToolPermissions",
        {"serverId": "s", "tools": {"keep": 1, "future": 2}, "writes": 2},
    )
    c.set_permission(t, "s", reads="block")
    assert t.calls[-1][2] == {
        "serverId": "s",
        "tools": {"keep": 1, "change": 3, "future": 2},
        "reads": 3,
        "writes": 2,
    }
    with pytest.raises(ValueError):
        c.normalize("wrong")


def test_mutations():
    t = fake()
    c.set_tool_disabled(t, "s", "search", False)
    assert [name for _, name, _ in t.calls] == ["listMcpServerTools"]
    c.set_tool_disabled(t, "s", "search", True)
    assert t.calls[-1] == (
        "command",
        "toggleMcpToolDisabled",
        {"serverId": "s", "toolName": "search"},
    )
    with pytest.raises(ValueError, match="Unknown tool"):
        c.set_tool_disabled(t, "s", "missing", True)
    c.set_instructions(t, "s", "  text \n")
    assert t.calls[-1][2] == {"serverId": "s", "instructions": "text"}
    c.set_instructions(t, "s", " \n")
    assert t.calls[-1][2]["instructions"] == ""
    c.rename_account(t, "s", "old", "new")
    assert t.calls[-1][2] == {
        "serverId": "s",
        "accountKey": "old",
        "newAccountKey": "new",
    }
    c.remove_account(t, "s", "old")
    assert t.calls[-1][2] == {"serverId": "s", "accountKey": "old"}
    t.commands["getMcpState"] = {"servers": [{"id": "s", "isTeamServer": True}]}
    with pytest.raises(ValueError, match="Your team admin manages this connector."):
        c.remove_server(t, "s")
    assert not any(name == "removeMcpServer" for _, name, _ in t.calls)
    assert c.shared_spaces(t) == set()
    for allowed, field in ((True, "addServerIds"), (False, "removeServerIds")):
        c.set_shared_space(t, "s", allowed)
        assert t.calls[-1][2] == {field: ["s"]}
    t.rpcs["ClearGrokBotConnectorAlwaysAllow"] = {"clearedCount": "42"}
    assert c.clear_always_allow(t) == 42


@pytest.mark.parametrize("field", ["status", "outcome", "kind"])
@pytest.mark.parametrize(
    "outcome",
    [
        "started",
        "already_authenticated",
        "not_configured",
        "unreachable",
        "not_supported",
        "unknown",
    ],
)
def test_sign_in(field, outcome):
    t = fake()
    t.commands["authenticateMcpServer"] = {
        field: outcome,
        "authorizationUrl": "PRIVATE",
        "reason": "PRIVATE",
    }
    result, url, sentence = c.start_sign_in(t, "s")
    assert result == outcome and url == "PRIVATE" and "PRIVATE" not in sentence
    assert t.calls[-1][2] == {"serverId": "s", "entryPoint": "settings"}
    c.start_sign_in(t, "s", account_key="key", reauth=True)
    assert t.calls[-1][2] == {
        "serverId": "s",
        "entryPoint": "settings",
        "accountKey": "key",
        "forceReauth": True,
    }


def test_completion_and_cancel():
    t = fake()
    before = c.servers(t)[0]
    events: list[dict[str, object]] = [{"serverId": "other"}]
    check = c.sign_in_check(t, before, events)
    assert check() is None
    events.append({"serverId": before.id})
    assert check() == before
    events[:] = [
        {
            "serverId": before.id,
            "outcome": "cancelled",
            "failureDetail": "Provider refused",
        }
    ]
    assert check() == "Provider refused"
    events.clear()
    t.commands["getMcpState"] = {
        "servers": [
            {
                "id": before.id,
                "status": "ready",
                "statusDetail": {"kind": "authentication_required"},
            }
        ]
    }
    assert check() is None
    t.commands["getMcpState"] = {"servers": [{"id": before.id, "status": "ready"}]}
    result = check()
    assert isinstance(result, c.Server) and result.status == "ready"
    cancel = Event()
    cancel.set()
    t.calls.clear()
    assert wait_until(check, cancel=cancel, wake=None).status == "cancelled"
    assert t.calls == []


def test_auth_reason_and_errors_are_redacted():
    t = fake()
    t.commands["authenticateMcpServer"] = {
        "status": "unreachable",
        "url": "PRIVATE",
        "reason": "Try PRIVATE or https://auth.test/secret",
    }
    sentence = c.start_sign_in(t, "s")[2]
    assert (
        "Try" in sentence and "PRIVATE" not in sentence and "auth.test" not in sentence
    )
    before = c.servers(t)[0]
    t.commands["getMcpState"] = ValueError("https://auth.test/secret")
    with pytest.raises(
        ValueError, match="Could not check connector sign-in status"
    ) as error:
        c.sign_in_check(t, before)()
    assert "auth.test" not in str(error.value)
    t.commands["authenticateMcpServer"] = ValueError("https://auth.test/secret")
    with pytest.raises(ValueError, match="Could not start connector sign-in"):
        c.start_sign_in(t, "s")


def test_started_sign_in_without_link_refuses():
    t = fake()
    t.commands["authenticateMcpServer"] = {"status": "started"}
    with pytest.raises(ValueError, match="sign-in link"):
        c.start_sign_in(t, "s")
