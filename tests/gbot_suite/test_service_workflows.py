from dataclasses import replace

import pytest

from gbot.service import workflows as w
from gbot.service.models import _record
from gbot.service.transport import FakeTransport
from groken.client import ConnectError


def fake():
    return FakeTransport(w.DEMO_COMMANDS, w.DEMO_RPCS)


def test_parse_merge_and_find():
    transport = fake()
    transport.commands["getAgentWorkflows"] = [
        {"id": "abcdef-one", "name": "Zebra", "source": "managed"},
        {"id": "abcdef-two", "name": "Beta", "source": "template"},
        {"id": "plugin", "name": "Plugin", "pluginId": 0},
        {"id": "third", "name": "Third", "source": "plugin"},
        {
            "id": "timer",
            "name": "Timer",
            "sourceRef": "ref",
            "createdAt": 10,
            "lastRunAt": 20,
            "nextRunAt": 30,
            "trigger": {"schedule": "daily", "isEnabled": True},
            "scheduleDescription": "Every day",
        },
    ]
    transport.rpcs["ListGrokBotAgentSkills"] = {
        "skills": [
            {
                "id": "abcdef-one",
                "name": "Alpha",
                "body": "server",
                "source": "managed",
            },
            {"id": "extra", "name": "Extra", "source": "user"},
        ]
    }
    rows = w.skills(transport, "gateway-id")
    assert [row.name for row in rows] == [
        "Extra",
        "Timer",
        "Alpha",
        "Beta",
        "Plugin",
        "Third",
    ]
    assert rows[2].body == "server"
    timer = rows[1]
    assert (
        timer.source_ref,
        timer.schedule,
        timer.schedule_enabled,
        timer.schedule_description,
    ) == ("ref", "daily", True, "Every day")
    assert (timer.created_at_ms, timer.last_run_at_ms, timer.next_run_at_ms) == (
        10,
        20,
        30,
    )
    assert transport.calls[-1] == (
        "rpc",
        "ListGrokBotAgentSkills",
        {"agentId": "gateway-id"},
    )
    assert w.find(rows, "aLPHa") is rows[2]
    assert w.find(rows, "abcdef-o") is rows[2]
    assert w.find(rows, "timer") is timer
    for query in ("abcde", "abcdef", "unknown"):
        with pytest.raises(ValueError, match="Choose:.*Alpha"):
            w.find(rows, query)
    with pytest.raises(ValueError):
        w.find([timer, replace(timer, id="other")], "Timer")


@pytest.mark.parametrize(
    "reply",
    [{}, ConnectError(404, '{"code":"not_found"}'), ConnectError(404, "not_found")],
)
def test_empty_server(reply):
    transport = fake()
    transport.rpcs["ListGrokBotAgentSkills"] = reply
    assert len(w.skills(transport, "bot")) == 3


def test_server_errors_propagate():
    transport = fake()
    transport.rpcs["ListGrokBotAgentSkills"] = ConnectError(
        403, '{"code":"permission_denied"}'
    )
    with pytest.raises(ConnectError):
        w.skills(transport, "bot")


def test_create_update_delete_and_run():
    transport = fake()
    skill = replace(w.skills(transport, "bot")[0], source_ref="origin")
    transport.calls.clear()
    w.create(
        transport,
        "bot",
        name=" Name ",
        description=" Description ",
        body="# Body\n",
        schedule=" daily ",
    )
    assert transport.calls[-1] == (
        "command",
        "createAgentWorkflow",
        {
            "id": "bot",
            "spec": {
                "name": "Name",
                "description": "Description",
                "body": "# Body\n",
                "trigger": {"schedule": "daily", "isEnabled": True},
            },
        },
    )
    w.update(transport, "bot", skill, name="New")
    spec = transport.calls[-1][2]["spec"]
    assert spec == {
        "name": "New",
        "description": skill.description,
        "body": skill.body,
        "trigger": None,
        "sourceRef": "origin",
    }
    w.update(transport, "bot", skill, schedule=" hourly ", schedule_enabled=False)
    assert _record(transport.calls[-1][2]["spec"])["trigger"] == {
        "schedule": "hourly",
        "isEnabled": False,
    }
    timer = replace(skill, schedule="daily", schedule_enabled=False)
    w.update(transport, "bot", timer, schedule_enabled=True)
    assert _record(transport.calls[-1][2]["spec"])["trigger"] == {
        "schedule": "daily",
        "isEnabled": True,
    }
    w.update(transport, "bot", timer, schedule=None)
    assert _record(transport.calls[-1][2]["spec"])["trigger"] is None
    w.run_now(transport, "bot", timer)
    assert transport.calls[-1] == (
        "command",
        "runAgentWorkflowNow",
        {"id": "bot", "workflowId": skill.id},
    )
    w.delete(transport, "bot", skill)
    assert transport.calls[-1][1] == "deleteAgentWorkflow"


def test_refusals_send_nothing():
    transport = fake()
    rows = w.skills(transport, "bot")
    transport.calls.clear()
    for operation in (w.update, w.delete):
        with pytest.raises(
            ValueError,
            match="This skill is managed by Grok Bot; copy it to make your own.",
        ):
            operation(transport, "bot", rows[-1])
    with pytest.raises(ValueError, match="no schedule"):
        w.run_now(transport, "bot", rows[0])
    with pytest.raises(ValueError, match="no schedule"):
        w.update(transport, "bot", rows[0], schedule_enabled=False)
    for field in ("name", "description", "body", "schedule"):
        values = {"name": "N", "description": "D", "body": "B", field: "  "}
        with pytest.raises(ValueError, match="blank"):
            w.create(transport, "bot", **values)
        with pytest.raises(ValueError, match="blank"):
            w.update(transport, "bot", rows[0], **{field: " "})  # type: ignore[arg-type]
    assert transport.calls == []


def test_imports_catalog_and_unknown_kind():
    transport = fake()
    transport.commands["importAgentWorkflowText"] = {
        "workflows": [*w.DEMO_COMMANDS["getAgentWorkflows"], {"id": "new"}],
        "result": {"secret": "not interpreted"},
    }
    count, rows = w.import_text(transport, "bot", "# Markdown", "Named")
    assert count == 1 and len(rows) == 4
    assert transport.calls[-1][2] == {
        "id": "bot",
        "markdown": "# Markdown",
        "name": "Named",
    }
    w.import_url(transport, "bot", " https://example.test/skill ", "URL")
    assert transport.calls[-1][2] == {
        "id": "bot",
        "url": "https://example.test/skill",
        "name": "URL",
    }
    entry = w.catalog(transport)[0]
    assert (entry.name, entry.publisher, entry.install_kind) == (
        "Weekly review",
        "Demo",
        "content",
    )
    w.install(transport, "bot", entry)
    assert transport.calls[-1][1] == "importAgentWorkflowText"
    w.install(
        transport,
        "bot",
        replace(
            entry, install_kind="url", install={"url": "http://example.test/skill"}
        ),
    )
    assert transport.calls[-1][1] == "importAgentWorkflowUrl"
    transport.calls.clear()
    for url in (
        "file:///tmp/skill",
        "ftp://example.test/a",
        "https:",
        "javascript:bad",
    ):
        with pytest.raises(ValueError, match="http or https"):
            w.import_url(transport, "bot", url)
    with pytest.raises(ValueError, match="Add this skill in the Grok Bot app."):
        w.install(transport, "bot", replace(entry, install_kind="unknown"))
    assert not transport.calls
