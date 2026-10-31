import json

import pytest

from gbot import cli, context
from gbot.service import sandbox
from gbot.service.transport import FakeTransport
from groken.client import ConnectError

READS = {
    "GetSandBoxRunState",
    "GetSandBoxUpgradeSchedule",
    "GetGrokBotUserRuntimeSettings",
    "listAgents",
}
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


def setup_cli(monkeypatch, rpcs=None):
    monkeypatch.setattr(
        sandbox.zoneinfo, "available_timezones", lambda: {"UTC", "Europe/Paris"}
    )
    fake = FakeTransport(
        {"listAgents": [{"id": "gateway", "name": "Alpha"}]},
        {
            **sandbox.DEMO_RPCS,
            "GetGrokBotUserRuntimeSettings": RUNTIME,
            **(rpcs or {}),
        },
    )
    monkeypatch.setattr(context, "manager_factory", lambda: fake)

    class Backend:
        def unary(self, service, name, payload):
            return fake.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    return fake


def changes(fake):
    return [call for call in fake.calls if call[1] not in READS]


CHANGES = [
    ["sandbox", "--recreate"],
    ["sandbox", "--recreate", "--discard-data"],
    ["sandbox", "--force-recreate"],
    ["sandbox", "--schedule-upgrade", "03:30"],
    ["sandbox", "--reschedule-upgrade", "03:30"],
    ["sandbox", "--cancel-upgrade"],
    ["settings", "--pin", "Alpha"],
    ["settings", "--unpin", "a"],
    ["settings", "--auto-review", "off"],
]


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("argv", [["sandbox"], ["settings"]])
def test_reads_in_text_and_json(monkeypatch, capsys, argv, json_mode):
    fake = setup_cli(monkeypatch)
    assert cli.main([*argv, *(["--json"] if json_mode else [])]) == 0
    output = capsys.readouterr().out
    if json_mode:
        json.loads(output)
    else:
        assert output.strip()
    assert not changes(fake)


def test_sandbox_read_fields(monkeypatch, capsys):
    setup_cli(monkeypatch)
    assert cli.main(["sandbox", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["state"] == "running"
    assert data["image_tag"] == "grok-bot-box:2026.10"
    assert data["image_update_available"] is True
    assert data["upgrade_schedule"]["local_time"] == "03:30"
    assert data["upgrade_schedule"]["recurring"] is True
    assert data["notice"] == ""
    assert "snapshots/demo" not in json.dumps(data)


def test_refused_read_part_is_a_notice_and_still_succeeds(monkeypatch, capsys):
    setup_cli(
        monkeypatch,
        {
            "GetSandBoxUpgradeSchedule": ConnectError(
                400,
                '{"code":"invalid_argument","message":"Pick a schedule first."}',
            )
        },
    )
    assert cli.main(["sandbox"]) == 0
    assert "Pick a schedule first." in capsys.readouterr().out
    assert cli.main(["sandbox", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["notice"] == "Pick a schedule first."


@pytest.mark.parametrize("argv", CHANGES)
def test_changes_need_yes_and_send_nothing(monkeypatch, capsys, argv):
    fake = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(argv) == 1
    assert "--yes" in capsys.readouterr().err
    assert not changes(fake)


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize(
    "argv,rpc,payload",
    [
        (
            ["sandbox", "--recreate"],
            "RecreateSandBox",
            {
                "preserveData": True,
                "force": False,
                "acknowledgeTerminalUpgradeSchedule": False,
            },
        ),
        (
            ["sandbox", "--recreate", "--discard-data", "--acknowledge-schedule"],
            "RecreateSandBox",
            {
                "preserveData": False,
                "force": False,
                "acknowledgeTerminalUpgradeSchedule": True,
            },
        ),
        (["sandbox", "--force-recreate"], "ForceRecreateSandBox", {}),
        (
            [
                "sandbox",
                "--schedule-upgrade",
                "03:30",
                "--timezone",
                "Europe/Paris",
                "--recurring",
            ],
            "ScheduleSandBoxUpgrade",
            {"timezone": "Europe/Paris", "localTime": "03:30", "recurring": True},
        ),
        (
            ["sandbox", "--reschedule-upgrade", "04:15"],
            "RescheduleSandBoxUpgrade",
            {"timezone": "UTC", "localTime": "04:15", "recurring": False},
        ),
        (
            ["sandbox", "--cancel-upgrade", "--dismiss-outcome"],
            "CancelSandBoxUpgrade",
            {"dismissTerminalOutcome": True},
        ),
    ],
)
def test_changes_send_exact_payloads(
    monkeypatch, capsys, argv, rpc, payload, json_mode
):
    fake = setup_cli(monkeypatch)
    assert cli.main([*argv, "--yes", *(["--json"] if json_mode else [])]) == 0
    assert ("rpc", rpc, payload) in fake.calls
    output = capsys.readouterr().out
    if json_mode:
        json.loads(output)
    else:
        assert output.strip()


def test_recreate_reports_started_reason_and_operation(monkeypatch, capsys):
    setup_cli(monkeypatch)
    assert cli.main(["sandbox", "--recreate", "--yes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "started": True,
        "reason": "",
        "operation_id": "demo-operation",
    }
    assert cli.main(["sandbox", "--recreate", "--yes"]) == 0
    text = capsys.readouterr().out
    assert "Started: yes" in text and "Operation: demo-operation" in text


def test_recreate_not_started_prints_report_and_exits_one(monkeypatch, capsys):
    setup_cli(
        monkeypatch,
        {"RecreateSandBox": {"started": False, "reason": "Update in progress."}},
    )
    assert cli.main(["sandbox", "--recreate", "--yes"]) == 1
    output = capsys.readouterr().out
    assert "Started: no" in output
    assert "Update in progress." in output


def test_discard_and_force_need_typed_recreate_in_a_terminal(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "recreate")
    assert cli.main(["sandbox", "--force-recreate"]) == 0
    assert ("rpc", "ForceRecreateSandBox", {}) in fake.calls
    assert cli.main(["sandbox", "--recreate", "--discard-data"]) == 0
    assert fake.calls[-1][2]["preserveData"] is False


@pytest.mark.parametrize(
    "argv,rpc",
    [
        (["sandbox", "--force-recreate"], "ForceRecreateSandBox"),
        (["sandbox", "--recreate", "--discard-data"], "RecreateSandBox"),
    ],
)
def test_typed_confirm_rejects_anything_but_recreate(monkeypatch, capsys, argv, rpc):
    fake = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "yes")
    assert cli.main(argv) == 1
    assert "Cancelled." in capsys.readouterr().err
    assert not any(call[1] == rpc for call in fake.calls)


def test_keep_recreate_uses_plain_yes_prompt(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert cli.main(["sandbox", "--recreate"]) == 0
    assert fake.calls[-1] == (
        "rpc",
        "RecreateSandBox",
        {
            "preserveData": True,
            "force": False,
            "acknowledgeTerminalUpgradeSchedule": False,
        },
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert cli.main(["sandbox", "--cancel-upgrade"]) == 1
    assert not any(call[1] == "CancelSandBoxUpgrade" for call in fake.calls)


@pytest.mark.parametrize(
    "argv",
    [
        ["sandbox", "--schedule-upgrade", "25:00"],
        ["sandbox", "--schedule-upgrade", "9:05"],
        ["sandbox", "--schedule-upgrade", "03:30", "--timezone", "Mars/Olympus"],
        ["sandbox", "--reschedule-upgrade", "03:30", "--timezone", "utc"],
    ],
)
def test_bad_schedule_fails_before_any_call(monkeypatch, capsys, argv):
    fake = setup_cli(monkeypatch)
    assert cli.main([*argv, "--yes"]) == 1
    error = capsys.readouterr().err
    assert "Local time" in error or "Time zone" in error
    assert fake.calls == []


@pytest.mark.parametrize(
    "argv",
    [
        ["sandbox", "--discard-data"],
        ["sandbox", "--acknowledge-schedule"],
        ["sandbox", "--timezone", "UTC"],
        ["sandbox", "--recreate", "--recurring"],
        ["sandbox", "--dismiss-outcome"],
        ["sandbox", "--recreate", "--schedule-upgrade", "03:30"],
    ],
)
def test_flags_must_match_their_action(monkeypatch, argv):
    fake = setup_cli(monkeypatch)
    assert cli.main([*argv, "--yes"]) == 1
    assert not changes(fake)


def test_refused_change_exits_one_with_the_server_message(monkeypatch, capsys):
    fake = setup_cli(
        monkeypatch,
        {
            "CancelSandBoxUpgrade": ConnectError(
                403,
                '{"code":"permission_denied","message":"Only the owner can cancel."}',
            )
        },
    )
    assert cli.main(["sandbox", "--cancel-upgrade", "--yes"]) == 1
    assert "Only the owner can cancel." in capsys.readouterr().err
    assert changes(fake)[-1][1] == "CancelSandBoxUpgrade"


def test_settings_pin_unpin_and_auto_review_send_changed_fields(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    assert cli.main(["settings", "--pin", "Alpha", "--yes"]) == 0
    assert (
        "rpc",
        "UpdateGrokBotUserRuntimeSettings",
        {"pinnedAgents": {"agentIds": ["a", "b", "gateway"]}},
    ) in fake.calls
    capsys.readouterr()
    assert cli.main(["settings", "--unpin", "a", "--yes", "--json"]) == 0
    assert fake.calls[-1] == (
        "rpc",
        "UpdateGrokBotUserRuntimeSettings",
        {"pinnedAgents": {"agentIds": ["b"]}},
    )
    assert [
        bot["id"] for bot in json.loads(capsys.readouterr().out)["pinned_bots"]
    ] == ["b"]
    assert cli.main(["settings", "--auto-review", "off", "--yes"]) == 0
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


def test_settings_no_op_sends_nothing(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    assert cli.main(["settings", "--pin", "a", "--yes"]) == 0
    assert cli.main(["settings", "--auto-review", "on", "--yes"]) == 0
    assert not any(call[1] == "UpdateGrokBotUserRuntimeSettings" for call in fake.calls)
    assert "Auto-review: on" in capsys.readouterr().out


def test_settings_show_names_and_defaults(monkeypatch, capsys):
    setup_cli(monkeypatch)
    assert cli.main(["settings", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["pinned_bots"] == [
        {"id": "a", "name": "a"},
        {"id": "b", "name": "b"},
    ]
    assert data["main_bot"] == {"id": "a", "name": "a"}
    assert data["auto_review_enabled"] is True
    assert data["email_provider"] == "gmail"
    assert "allow this" not in json.dumps(data)


def test_settings_read_refusal_exits_one(monkeypatch, capsys):
    setup_cli(
        monkeypatch,
        {
            "GetGrokBotUserRuntimeSettings": ConnectError(
                403, '{"code":"permission_denied","message":"Team only."}'
            )
        },
    )
    assert cli.main(["settings"]) == 1
    assert "Team only." in capsys.readouterr().err


def test_refused_schedule_read_prints_no_default_row(monkeypatch, capsys):
    setup_cli(
        monkeypatch,
        {
            "GetSandBoxUpgradeSchedule": ConnectError(
                400,
                '{"code":"invalid_argument","message":"Pick a schedule first."}',
            )
        },
    )
    assert cli.main(["sandbox"]) == 0
    output = capsys.readouterr().out
    assert "Upgrade: none scheduled" not in output
    assert "Pick a schedule first." in output


def test_empty_timezone_is_rejected_not_replaced_with_utc(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    argv = ["sandbox", "--schedule-upgrade", "03:30", "--timezone", "", "--yes"]
    assert cli.main([*argv, "--json"]) == 1
    assert "Time zone" in capsys.readouterr().err
    assert changes(fake) == []
