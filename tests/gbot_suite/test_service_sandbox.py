import json
from pathlib import Path

import pytest

from gbot.service import sandbox
from gbot.service.fake import load_fake
from gbot.service.transport import FakeTransport
from groken.client import ConnectError

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = {
    "settings": {
        "pinnedAgents": {"agentIds": ["a", "b"]},
        "autoReviewInstructions": {
            "isEnabled": True,
            "allowInstructions": ["allow this"],
            "blockInstructions": ["never this"],
        },
        "hasSeenOnboarding": True,
        "mainAgentId": "a",
        "emailProvider": "gmail",
        "updatedAtMs": "1800000000000",
    }
}


@pytest.fixture
def zones(monkeypatch):
    # Pin the zone list so validation does not depend on the machine's tzdata.
    monkeypatch.setattr(
        sandbox.zoneinfo, "available_timezones", lambda: {"UTC", "Europe/Paris"}
    )


def test_run_state_parses_all_forms():
    for number, name in enumerate(sandbox.RUN_STATES):
        for value in (number, name.upper(), "SAND_BOX_RUN_STATE_" + name.upper()):
            fake = FakeTransport(rpcs={"GetSandBoxRunState": {"state": value}})
            expected = "unknown" if name == "unspecified" else name
            assert sandbox.run_state(fake).state == expected
    assert sandbox._enum(999, sandbox.RUN_STATES, "SAND_BOX_RUN_STATE") == "unknown"
    assert sandbox._enum("future", sandbox.RUN_STATES, "SAND_BOX_RUN_STATE") == (
        "unknown"
    )


def test_schedule_states_parse_all_forms():
    for number, name in enumerate(sandbox.SCHEDULE_STATES):
        for value in (
            number,
            name.upper(),
            "SAND_BOX_UPGRADE_SCHEDULE_STATE_" + name.upper(),
        ):
            fake = FakeTransport(
                rpcs={"GetSandBoxUpgradeSchedule": {"schedule": {"state": value}}}
            )
            schedule = sandbox.upgrade_schedule(fake)
            assert schedule is not None and schedule.state == name
    assert len(sandbox.SCHEDULE_STATES) == 9


def test_run_state_fields_and_image():
    fake = FakeTransport(
        rpcs={
            "GetSandBoxRunState": {
                "state": "SAND_BOX_RUN_STATE_RUNNING",
                "image": {
                    "registryTag": "box:1",
                    "staticSnapshotPath": "snap/one",
                },
                "imageUpdateAvailable": True,
                "egressTunnelOwnership": True,
            }
        }
    )
    state = sandbox.run_state(fake)
    assert state == sandbox.RunState("running", "box:1", "snap/one", True, True)
    assert "snap/one" not in repr(state)
    assert fake.calls == [("rpc", "GetSandBoxRunState", {})]


def test_missing_and_odd_fields_get_defaults():
    fake = FakeTransport(
        rpcs={
            "GetSandBoxRunState": {
                "state": "SAND_BOX_RUN_STATE_HIBERNATED",
                "image": "odd",
                "imageUpdateAvailable": "yes",
            },
            "GetSandBoxUpgradeSchedule": {
                "schedule": {
                    "nextFireAtMs": {"odd": 1},
                    "recurring": "no",
                    "failureReason": 7,
                }
            },
        }
    )
    assert sandbox.run_state(fake) == sandbox.RunState("hibernated")
    assert sandbox.upgrade_schedule(fake) == sandbox.UpgradeSchedule(state="unknown")
    fake.rpcs["GetSandBoxUpgradeSchedule"] = {"schedule": {"state": 0}}
    schedule = sandbox.upgrade_schedule(fake)
    assert schedule is not None and schedule.state == "unspecified"


def test_absent_schedule_is_none():
    for reply in ({}, {"schedule": {}}, {"schedule": None}, {"schedule": "odd"}):
        fake = FakeTransport(rpcs={"GetSandBoxUpgradeSchedule": reply})
        assert sandbox.upgrade_schedule(fake) is None


def test_schedule_timestamps_are_int64_strings():
    fake = FakeTransport(
        rpcs={
            "GetSandBoxUpgradeSchedule": {
                "schedule": {
                    "timezone": "Europe/Paris",
                    "localTime": "03:30",
                    "recurring": True,
                    "targetImageTag": "box:2",
                    "nextFireAtMs": "1800086200000",
                    "state": 1,
                    "lastCompletedImageTag": "box:1",
                    "failureReason": "Image was missing.",
                }
            }
        }
    )
    schedule = sandbox.upgrade_schedule(fake)
    assert schedule == sandbox.UpgradeSchedule(
        "Europe/Paris",
        "03:30",
        True,
        "box:2",
        1800086200000,
        "scheduled",
        "box:1",
        "Image was missing.",
    )


def test_recreate_payloads_for_keep_discard_and_acknowledge():
    fake = FakeTransport(
        rpcs={
            "RecreateSandBox": {"started": True, "reason": "ok", "operationId": "op-1"}
        }
    )
    assert sandbox.recreate(fake) == sandbox.RecreateResult(True, "ok", "op-1")
    sandbox.recreate(fake, preserve_data=False)
    sandbox.recreate(fake, acknowledge_terminal_upgrade_schedule=True)
    assert [payload for _, _, payload in fake.calls] == [
        {
            "preserveData": True,
            "force": False,
            "acknowledgeTerminalUpgradeSchedule": False,
        },
        {
            "preserveData": False,
            "force": False,
            "acknowledgeTerminalUpgradeSchedule": False,
        },
        {
            "preserveData": True,
            "force": False,
            "acknowledgeTerminalUpgradeSchedule": True,
        },
    ]


def test_force_recreate_sends_empty_request_and_reports_rejection():
    fake = FakeTransport(
        rpcs={"ForceRecreateSandBox": {"started": False, "reason": "Busy."}}
    )
    assert sandbox.force_recreate(fake) == sandbox.RecreateResult(False, "Busy.", "")
    assert fake.calls == [("rpc", "ForceRecreateSandBox", {})]


@pytest.mark.parametrize(
    "local_time", ["24:00", "9:05", "12:60", "12:5", "ab:cd", "03:30 ", "03:30\n", ""]
)
def test_bad_local_time_raises_before_any_call(local_time, zones):
    fake = FakeTransport()
    with pytest.raises(ValueError, match="24-hour"):
        sandbox.schedule_upgrade(fake, "UTC", local_time, False)
    with pytest.raises(ValueError, match="24-hour"):
        sandbox.reschedule_upgrade(fake, "UTC", local_time, False)
    assert fake.calls == []


@pytest.mark.parametrize("zone", ["Mars/Olympus", "", "utc", "Europe"])
def test_unknown_time_zone_raises_before_any_call(zone, zones):
    fake = FakeTransport()
    with pytest.raises(ValueError, match="Time zone"):
        sandbox.schedule_upgrade(fake, zone, "03:30", False)
    assert fake.calls == []


def test_time_zone_falls_back_to_shape_without_tzdata(monkeypatch):
    monkeypatch.setattr(sandbox.zoneinfo, "available_timezones", lambda: set())
    fake = FakeTransport(rpcs={"ScheduleSandBoxUpgrade": {}})
    sandbox.schedule_upgrade(fake, "UTC", "03:30", False)
    sandbox.schedule_upgrade(fake, "America/Argentina/Buenos_Aires", "03:30", False)
    with pytest.raises(ValueError, match="Time zone"):
        sandbox.schedule_upgrade(fake, "Europe", "03:30", False)
    assert len(fake.calls) == 2


def test_schedule_and_reschedule_send_exact_payloads(zones):
    fake = FakeTransport(
        rpcs={
            "ScheduleSandBoxUpgrade": {
                "schedule": {
                    "state": "SAND_BOX_UPGRADE_SCHEDULE_STATE_SCHEDULED",
                    "timezone": "Europe/Paris",
                    "localTime": "03:30",
                    "recurring": True,
                }
            },
            "RescheduleSandBoxUpgrade": {"schedule": {"state": 1}},
        }
    )
    result = sandbox.schedule_upgrade(fake, "Europe/Paris", "03:30", True)
    assert result.state == "scheduled" and result.recurring is True
    assert fake.calls[-1] == (
        "rpc",
        "ScheduleSandBoxUpgrade",
        {"timezone": "Europe/Paris", "localTime": "03:30", "recurring": True},
    )
    # A reply without a schedule keeps what was asked for.
    fake.rpcs["RescheduleSandBoxUpgrade"] = {}
    rescheduled = sandbox.reschedule_upgrade(fake, "UTC", "04:15", False)
    assert rescheduled == sandbox.UpgradeSchedule("UTC", "04:15", False)
    assert fake.calls[-1] == (
        "rpc",
        "RescheduleSandBoxUpgrade",
        {"timezone": "UTC", "localTime": "04:15", "recurring": False},
    )


def test_cancel_sends_dismiss_flag_and_returns_none_when_cleared():
    fake = FakeTransport(rpcs={"CancelSandBoxUpgrade": {}})
    assert sandbox.cancel_upgrade(fake) is None
    assert fake.calls[-1] == (
        "rpc",
        "CancelSandBoxUpgrade",
        {"dismissTerminalOutcome": False},
    )
    sandbox.cancel_upgrade(fake, dismiss_terminal_outcome=True)
    assert fake.calls[-1][2] == {"dismissTerminalOutcome": True}


def test_runtime_settings_read_hides_instruction_text():
    fake = FakeTransport(rpcs={"GetGrokBotUserRuntimeSettings": RUNTIME})
    current = sandbox.runtime_settings(fake)
    assert current.pinned_agent_ids == ("a", "b")
    assert current.auto_review_enabled is True
    assert current.has_seen_onboarding is True
    assert current.main_agent_id == "a"
    assert current.email_provider == "gmail"
    assert current.updated_at_ms == 1800000000000
    assert current.raw_auto_review["allowInstructions"] == ["allow this"]
    assert "allow this" not in repr(current)


def test_update_sends_only_changed_field_and_keeps_allow_and_block_lists():
    fake = FakeTransport(
        rpcs={
            "GetGrokBotUserRuntimeSettings": RUNTIME,
            "UpdateGrokBotUserRuntimeSettings": RUNTIME,
        }
    )
    current = sandbox.runtime_settings(fake)
    sandbox.update_runtime_settings(fake, current, auto_review_enabled=False)
    assert fake.calls[-1] == (
        "rpc",
        "UpdateGrokBotUserRuntimeSettings",
        {
            "autoReviewInstructions": {
                "isEnabled": False,
                "allowInstructions": ["allow this"],
                "blockInstructions": ["never this"],
            }
        },
    )
    sandbox.update_runtime_settings(fake, current, pinned_agent_ids=["b"])
    assert fake.calls[-1] == (
        "rpc",
        "UpdateGrokBotUserRuntimeSettings",
        {"pinnedAgents": {"agentIds": ["b"]}},
    )
    with pytest.raises(ValueError, match="Nothing to change"):
        sandbox.update_runtime_settings(fake, current)


def test_update_without_settings_reply_applies_change_locally():
    fake = FakeTransport(
        rpcs={
            "GetGrokBotUserRuntimeSettings": RUNTIME,
            "UpdateGrokBotUserRuntimeSettings": {},
        }
    )
    current = sandbox.runtime_settings(fake)
    updated = sandbox.update_runtime_settings(
        fake, current, pinned_agent_ids=["a"], auto_review_enabled=False
    )
    assert updated.pinned_agent_ids == ("a",)
    assert updated.auto_review_enabled is False
    assert updated.main_agent_id == "a"


def test_overview_turns_refused_parts_into_notices():
    fake = FakeTransport(
        rpcs={
            "GetSandBoxRunState": {"state": "SAND_BOX_RUN_STATE_RUNNING"},
            "GetSandBoxUpgradeSchedule": ConnectError(
                400,
                '{"code":"invalid_argument","message":"Pick a schedule first."}',
            ),
        }
    )
    value = sandbox.overview(fake)
    assert value.run.state == "running"
    assert value.schedule is None
    assert value.notice == "Pick a schedule first."

    fake.rpcs["GetSandBoxRunState"] = ConnectError(
        403, '{"code":"permission_denied","message":"Not for you."}'
    )
    value = sandbox.overview(fake)
    assert value.run.state == "unknown"
    assert value.notice == "Not for you. Pick a schedule first."


def test_overview_raises_unrecognised_errors():
    fake = FakeTransport(rpcs={"GetSandBoxRunState": ConnectError(500, "boom")})
    with pytest.raises(ConnectError):
        sandbox.overview(fake)


def test_fields_and_settings_fields_show_plain_rows():
    empty = dict(sandbox.fields(sandbox.Overview()))
    assert empty["Upgrade"] == "none scheduled"
    value = sandbox.Overview(
        sandbox.RunState("running", "box:1", None, True),
        sandbox.UpgradeSchedule(
            "UTC", "03:30", True, None, 1800000000000, "scheduled", None, "Boom."
        ),
    )
    rows = dict(sandbox.fields(value))
    assert rows["State"] == "running"
    assert rows["Update available"] == "yes"
    assert rows["Recurring"] == "yes"
    assert rows["Next run"] == "2027-01-15 08:00 UTC"
    assert rows["Failure reason"] == "Boom."
    current = sandbox.RuntimeSettings(
        ("a", "b"), True, False, "a", "gmail", None, {"isEnabled": True}
    )
    settings = dict(sandbox.settings_fields(current, {"a": "Alpha"}))
    assert settings["Pinned bots"] == "Alpha, b"
    assert settings["Main bot"] == "Alpha"
    assert settings["Auto-review"] == "on"
    assert settings["Onboarding"] == "not seen"


def test_demo_replies_and_parity_entries():
    transport = load_fake().transport
    assert set(sandbox.RPCS) <= transport.rpcs.keys()
    value = sandbox.overview(transport)
    assert value.run.state == "running" and value.run.image_update_available
    assert value.schedule is not None and value.schedule.recurring
    assert value.schedule.state == "scheduled"
    assert sandbox.recreate(transport).started
    assert sandbox.force_recreate(transport).operation_id == "demo-force-operation"

    entries = json.loads((ROOT / "docs/parity.json").read_text(encoding="utf-8"))[
        "entries"
    ]
    index = {row["name"]: row for row in entries}
    for name in sandbox.RPCS:
        assert index[name]["status"] == "done"
        assert index[name]["milestone"] == "M5"
    assert index["getHostSettings"]["status"] == "declined"
    assert index["setHostSettings"]["status"] == "declined"
    assert index["isEgressTunnelAvailable"]["status"] == "declined"
    assert index["updateHostNow"]["status"] == "handoff"
