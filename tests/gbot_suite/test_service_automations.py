import json
import struct
from dataclasses import replace
from threading import Event

import pytest

from gbot.service import automations as a
from gbot.service.models import Bot
from gbot.service.transport import FakeTransport


def record(**changes):
    return {**a._DEMO, **changes}


def wrapped(**changes):
    return {
        "automationId": "outer",
        "recordJson": json.dumps(record(**changes)),
        "viewerPermissions": {
            "allowedActions": [
                "GROK_BOT_AUTOMATION_ACTION_" + action
                for action in ("OPEN", "EDIT", "TOGGLE", "DELETE")
            ]
        },
    }


def transport():
    return FakeTransport(a.DEMO_COMMANDS, a.DEMO_RPCS)


@pytest.mark.parametrize("harness", ["box", "temporal"])
def test_routes_and_ids(harness):
    t = transport()
    bot = Bot("gateway", "Alpha", raw={"harness": harness, "serverId": "backend"})
    item = a.list_for_bot(t, bot)[0]
    assert t.calls[-1] == (
        ("rpc", "ListGrokBotAgentAutomations", {"agentId": "gateway"})
        if harness == "temporal"
        else ("command", "getAgentAutomations", {"id": "gateway"})
    )
    a.set_enabled(t, bot, item, False)
    assert t.calls[-1] == (
        (
            "rpc",
            "SetGrokBotAgentAutomationEnabled",
            {"agentId": "gateway", "automationId": item.id, "isEnabled": False},
        )
        if harness == "temporal"
        else (
            "command",
            "setAgentAutomationEnabled",
            {"id": "gateway", "automationId": item.id, "isEnabled": False},
        )
    )
    a.delete(t, bot, item)
    assert t.calls[-1][1] == (
        "DeleteGrokBotAgentAutomation"
        if harness == "temporal"
        else "deleteAgentAutomation"
    )
    a.run_now(t, bot, item)
    assert t.calls[-1] == (
        "command",
        "runAgentAutomationNow",
        {"id": "gateway", "automationId": item.id},
    )


def test_account_batches():
    t = transport()

    def account(args):
        return {
            "agents": [
                {"agentId": agent, "automations": [wrapped()]}
                for agent in args["agentIds"]
            ]
        }

    t.rpcs["ListGrokBotAccountAutomations"] = account
    bots = [Bot(str(i), str(i), raw={"harness": "temporal"}) for i in range(401)]
    bots.append(Bot("demo-helper", "Helper"))
    assert len(a.list_for_account(t, bots)) == 402
    assert [
        len(ids)
        for kind, _, args in t.calls
        if kind == "rpc" and isinstance(ids := args["agentIds"], list)
    ] == [
        200,
        200,
        1,
    ]
    assert t.calls[-1] == ("command", "listAllAutomations", {})


@pytest.mark.parametrize(
    "key,value",
    [
        ("id", None),
        ("name", 1),
        ("prompt", []),
        ("schedule", False),
        ("triggerDescription", {}),
        ("filePath", None),
        ("isEnabled", 1),
        ("createdAt", True),
        ("runs", {}),
    ],
)
def test_invalid_records(key, value):
    assert a._parse(wrapped(**{key: value}), "b") is None
    assert a._parse({"recordJson": "{"}, "b") is None


def test_parsing_sort_and_permissions():
    t = transport()
    rows = [
        wrapped(id="last", nextRunAt=None),
        wrapped(id="second", nextRunAt=10, createdAt=4),
        wrapped(
            id="first",
            nextRunAt=10,
            createdAt=2,
            extra={"future": True},
            viewerCapabilities={"canEdit": True},
            runs=[None, {}, {"id": "run", "status": "running", "startedAt": 7}],
        ),
    ]
    t.rpcs["ListGrokBotAgentAutomations"] = {"automations": rows}
    bot = Bot("b", "B", raw={"harness": "temporal"})
    items = a.list_for_bot(t, bot)
    assert [item.id for item in items] == ["first", "second", "last"]
    item = items[0]
    assert item.allowed is not None
    assert item.server_id == "outer" and item.raw["extra"] == {"future": True}
    assert "viewerCapabilities" not in item.raw
    assert item.runs == (a.Run("run", "running", 7),)
    for action, call in [
        ("EDIT", lambda x: a.update(t, bot, x, name="new")),
        ("TOGGLE", lambda x: a.set_enabled(t, bot, x, False)),
        ("DELETE", lambda x: a.delete(t, bot, x)),
        ("OPEN", lambda x: a.run_now(t, bot, x)),
    ]:
        before = len(t.calls)
        with pytest.raises(ValueError, match="permission"):
            call(replace(item, allowed=frozenset(item.allowed - {action})))
        assert len(t.calls) == before
    rows[0]["viewerPermissions"] = {"allowedActions": []}
    with pytest.raises(ValueError, match="permission"):
        a.get(t, bot, "last")


@pytest.mark.parametrize(
    "schedule",
    [
        "* * * * *",
        "0,15,30 9-17/2 1-31 1,12 0-7",
        "*/5 * * * *",
        "@hourly",
        "@daily",
        "@midnight",
        "@weekly",
        "@monthly",
        "@yearly",
        "@annually",
        "@every 1ms",
        "@every 1.5h30m",
        "@every 1d/2h",
        "TZ=UTC @daily",
        "CRON_TZ=Australia/Brisbane 0 9 * * 1-5",
    ],
)
def test_schedules(schedule, tmp_path, monkeypatch):
    if schedule.startswith(("TZ=", "CRON_TZ=")):
        # Windows has no system IANA database. Supply a tiny TZif fixture so the
        # test exercises ZoneInfo without depending on an installed tzdata wheel.
        from zoneinfo import ZoneInfo

        zone = schedule.split()[0].split("=", 1)[1]
        path = tmp_path / "zone"
        path.write_bytes(
            b"TZif\0"
            + b"\0" * 15
            + struct.pack(">6l", 0, 0, 0, 0, 1, 4)
            + struct.pack(">lbb", 0, 0, 0)
            + b"UTC\0"
        )

        def timezone(key):
            assert key == zone
            with path.open("rb") as stream:
                return ZoneInfo.from_file(stream, key=key)

        monkeypatch.setattr(a, "ZoneInfo", timezone)
    assert a.check_schedule(schedule) == schedule


@pytest.mark.parametrize(
    "schedule,field",
    [
        ("60 * * * *", "minute"),
        ("* 24 * * *", "hour"),
        ("* * 0 * *", "day"),
        ("* * * 13 *", "month"),
        ("* * * * 8", "weekday"),
        ("*/0 * * * *", "minute"),
        ("5-1 * * * *", "minute"),
        ("1, * * * *", "minute"),
        ("* * * JAN *", "month"),
        ("* * * * * *", "fields"),
        ("@every 0m", "positive"),
        ("@every -1s", "duration"),
        ("@every 1h/1h", "Phase"),
        ("TZ=../bad @daily", "timezone"),
        ("@sometimes", "fields"),
    ],
)
def test_bad_schedules(schedule, field):
    with pytest.raises(ValueError, match=field):
        a.check_schedule(schedule)


@pytest.mark.parametrize(
    "trigger,key",
    [
        ({"type": "cron", "schedule": "@daily"}, "@daily"),
        (
            {
                "type": "slack",
                "channel": "general",
                "match": {"kind": "keyword", "keyword": "hi"},
            },
            "hi",
        ),
        ({"type": "github", "repo": "org/repo", "events": ["ci-passed"]}, "ci-passed"),
        ({"type": "origin", "repo": "origin-repo"}, "origin-repo"),
        ({"type": "microsoftTeams", "tenantId": "tenant"}, "tenant"),
        (
            {
                "type": "linear",
                "event": {"case": "statusChanged", "statusIds": ["done"]},
            },
            "done",
        ),
        ({"type": "sentry", "event": {"case": "issueCreated"}}, "issueCreated"),
        ({"type": "pagerduty", "serviceIds": ["service"]}, "service"),
        ({"type": "email", "inbox": "inbox"}, "inbox"),
        ({"type": "webhook"}, "webhook"),
        (
            {
                "type": "group",
                "listeners": [
                    {"type": "cron", "schedule": "@daily"},
                    {"type": "webhook"},
                ],
            },
            "@daily",
        ),
    ],
)
def test_descriptions(trigger, key):
    assert key in a.describe_trigger(trigger)
    assert "\n" not in a.describe_trigger(trigger)


def test_create_update():
    t, bot = transport(), Bot("b", "B")
    a.create(t, bot, name="Name", prompt="Prompt", schedule="@daily", enabled=False)
    assert t.calls[-1] == (
        "command",
        "createAgentAutomation",
        {
            "id": "b",
            "spec": {
                "name": "Name",
                "prompt": "Prompt",
                "trigger": {"type": "cron", "schedule": "@daily"},
                "isEnabled": False,
            },
        },
    )
    item = a.list_for_bot(t, bot)[0]
    trigger = {
        "type": "slack",
        "channel": "general",
        "match": {"kind": "message"},
        "future": True,
    }
    item = replace(item, trigger=trigger)
    a.update(t, bot, item, name="Changed")
    assert t.calls[-1][2]["spec"] == {
        "name": "Changed",
        "prompt": item.prompt,
        "trigger": trigger,
        "isEnabled": True,
    }
    before = len(t.calls)
    for fields, error in [
        ({"schedule": "@daily"}, "Change this trigger"),
        ({"name": " "}, "blank"),
        ({"prompt": " "}, "blank"),
    ]:
        with pytest.raises(ValueError, match=error):
            a.update(
                t,
                bot,
                item,
                name=fields.get("name"),
                prompt=fields.get("prompt"),
                schedule=fields.get("schedule"),
            )
    assert len(t.calls) == before


def test_wait_new_run_and_cancel(monkeypatch):
    t, bot = transport(), Bot("b", "B")
    item = a.list_for_bot(t, bot)[0]
    replies = iter(
        [
            [record()],
            [record(runs=[{"id": "new", "status": "running", "startedAt": 9}])],
        ]
    )
    t.commands["getAgentAutomations"] = lambda args: next(replies)
    from gbot.service.handoff import wait_until

    class Clock:
        value = 0

        def __call__(self):
            self.value += 10
            return self.value

    monkeypatch.setattr(
        a, "wait_until", lambda check, **kw: wait_until(check, **kw, clock=Clock())
    )
    result = a.wait_for_run(t, bot, item, cancel=Event())
    assert result == a.Run("new", "running", 9)
    cancel = Event()
    cancel.set()
    before = len(t.calls)
    assert a.wait_for_run(t, bot, item, cancel=cancel) is None
    assert len(t.calls) == before


def test_get_prefix_name_and_empty():
    t, bot = transport(), Bot("b", "B")
    assert a.get(t, bot, "demo-a").id == "demo-automation"
    assert a.get(t, bot, "Morning briefing").id == "demo-automation"
    with pytest.raises(ValueError):
        a.get(t, bot, "demo")
    t.commands["getAgentAutomations"] = [record(id="abcdef1"), record(id="abcdef2")]
    with pytest.raises(ValueError):
        a.get(t, bot, "abcdef")
    t.rpcs["ListGrokBotAgentAutomations"] = {}
    assert a.list_for_bot(t, replace(bot, raw={"harness": "temporal"})) == []


def test_zone_without_database(monkeypatch):
    # No time-zone database (Windows without tzdata): a well-formed zone passes.
    monkeypatch.setattr(a, "available_timezones", set)
    assert a.check_schedule("CRON_TZ=America/Los_Angeles 0 9 * * 1")
    with pytest.raises(ValueError, match="timezone"):
        a.check_schedule("CRON_TZ=../x 0 9 * * 1")


def test_unknown_zone_with_database(monkeypatch):
    monkeypatch.setattr(a, "available_timezones", lambda: {"UTC"})
    with pytest.raises(ValueError, match="timezone"):
        a.check_schedule("TZ=Unknown/Bad @daily")
