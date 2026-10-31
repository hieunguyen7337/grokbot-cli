import json

import pytest

from gbot import cli, context
from gbot.service import team_bots
from gbot.service.transport import FakeTransport
from groken.client import ConnectError

REFUSED = json.dumps(
    {"code": "permission_denied", "message": "Only a team manager can see this."}
)


def setup_cli(monkeypatch):
    fake = FakeTransport(
        {"listAgents": [{"id": "gateway", "name": "Alpha"}]},
        {**team_bots.DEMO_RPCS},
    )
    monkeypatch.setattr(context, "manager_factory", lambda: fake)

    class Backend:
        def unary(self, service, name, payload):
            return fake.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    return fake


def rpc_calls(fake, name):
    return [payload for _, method, payload in fake.calls if method == name]


def refuse(fake, name):
    fake.rpcs[name] = ConnectError(403, REFUSED)


CHANGES = [
    (["Alpha", "--approve", "item-1"], "ResolveGrokBotTeamReviewItem"),
    (["Alpha", "--reject", "item-1"], "ResolveGrokBotTeamReviewItem"),
    (["Alpha", "--promote", "fact-1", "fact-2"], "PromoteGrokBotMemoriesToTeam"),
    (["--link-preview", "42", "--set", "on"], "SetGrokBotTeamLinkPreview"),
]


@pytest.mark.parametrize("argv,rpc", CHANGES)
def test_changes_need_yes_without_a_terminal(monkeypatch, capsys, argv, rpc):
    fake = setup_cli(monkeypatch)
    assert cli.main(["team", *argv]) == 1
    assert "--yes" in capsys.readouterr().err
    assert not fake.calls


@pytest.mark.parametrize("argv,rpc", CHANGES)
def test_changes_with_yes_send_one_call(monkeypatch, capsys, argv, rpc):
    fake = setup_cli(monkeypatch)
    assert cli.main(["team", *argv, "--yes"]) == 0
    assert [name for _, name, _ in fake.calls if name == rpc] == [rpc]
    assert capsys.readouterr().out.strip()


@pytest.mark.parametrize("argv,rpc", CHANGES)
def test_a_declined_prompt_sends_nothing(monkeypatch, capsys, argv, rpc):
    fake = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert cli.main(["team", *argv]) == 1
    assert "Cancelled." in capsys.readouterr().err
    assert not fake.calls


def test_team_bots_list_text_json_and_role(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    assert cli.main(["team"]) == 0
    assert capsys.readouterr().out.strip() == "No team bots."
    fake.rpcs["ListGrokBotTeamAgents"] = {
        "entries": [
            {
                "agent": {"agentId": "a1", "name": "Ops"},
                "userTurns": 3,
                "teammateTurns": "1",
                "lastTurnAtMs": "86400000",
            }
        ]
    }
    assert cli.main(["team", "--role", "admin"]) == 0
    assert rpc_calls(fake, "ListGrokBotTeamAgents")[-1] == {"role": "admin"}
    text = capsys.readouterr().out
    assert "Ops" in text and "3 user turns, 1 teammate turns" in text
    assert "1970-01-02" in text
    assert cli.main(["team", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows == [
        {
            "agent_id": "a1",
            "name": "Ops",
            "user_turns": 3,
            "teammate_turns": 1,
            "last_turn_at_ms": 86_400_000,
        }
    ]


def test_summary_text_and_json(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    fake.rpcs["GetGrokBotTeamContextSummary"] = {
        "summary": {"prose": "Handles billing.", "memoryVersion": 4},
        "stale": True,
        "skills": [{"name": "triage"}],
        "learned": [{"factId": "f1", "text": "Likes tea", "learnedAtMs": "9"}],
        "memoryCount": 2,
    }
    assert cli.main(["team", "Alpha", "--summary"]) == 0
    text = capsys.readouterr().out
    assert "Handles billing." in text
    assert "Memories: 2 (stale)" in text
    assert "Skills: triage" in text
    assert "Learned: Likes tea" in text
    assert rpc_calls(fake, "GetGrokBotTeamContextSummary")[-1] == {"agentId": "gateway"}
    assert cli.main(["team", "Alpha", "--summary", "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["memory_version"] == 4
    assert summary["learned"] == [
        {"fact_id": "f1", "text": "Likes tea", "learned_at_ms": 9}
    ]


def test_review_payload_and_output(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    fake.rpcs["ListGrokBotTeamReviewItems"] = {
        "items": [
            {
                "itemId": "item-1",
                "status": "GROK_BOT_TEAM_REVIEW_ITEM_STATUS_PENDING",
                "change": {
                    "memory": {"action": "WRITE", "text": "Prefers mornings"},
                    "summary": "Remember mornings",
                },
            }
        ]
    }
    assert cli.main(["team", "Alpha", "--review"]) == 0
    assert rpc_calls(fake, "ListGrokBotTeamReviewItems")[-1] == {
        "agentId": "gateway",
        "statuses": ["GROK_BOT_TEAM_REVIEW_ITEM_STATUS_PENDING"],
        "limit": 100,
    }
    assert capsys.readouterr().out.strip() == (
        "item-1  pending  memory write  Remember mornings"
    )
    assert (
        cli.main(
            [
                "team",
                "Alpha",
                "--review",
                "--status",
                "approved",
                "--status",
                "rejected",
                "--limit",
                "5",
                "--json",
            ]
        )
        == 0
    )
    assert rpc_calls(fake, "ListGrokBotTeamReviewItems")[-1] == {
        "agentId": "gateway",
        "statuses": [
            "GROK_BOT_TEAM_REVIEW_ITEM_STATUS_APPROVED",
            "GROK_BOT_TEAM_REVIEW_ITEM_STATUS_REJECTED",
        ],
        "limit": 5,
    }
    assert json.loads(capsys.readouterr().out)[0]["change"]["kind"] == "memory"


def test_memories_and_empty_review(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    assert cli.main(["team", "Alpha", "--memories"]) == 0
    assert capsys.readouterr().out.strip() == "No memories to share."
    fake.rpcs["ListGrokBotUserBotMemories"] = {
        "memories": [{"factId": "f1", "text": "Likes tea", "learnedAtMs": "1"}]
    }
    assert cli.main(["team", "Alpha", "--memories"]) == 0
    assert capsys.readouterr().out.strip() == "f1  Likes tea"
    assert cli.main(["team", "Alpha", "--review"]) == 0
    assert capsys.readouterr().out.strip() == "No review items."


def test_approve_and_reject_report_the_item(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    assert cli.main(["team", "Alpha", "--reject", "item-2", "--yes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["item_id"] == "item-2"
    assert rpc_calls(fake, "ResolveGrokBotTeamReviewItem")[-1] == {
        "agentId": "gateway",
        "itemId": "item-2",
        "decision": "GROK_BOT_TEAM_REVIEW_DECISION_REJECT",
    }
    assert cli.main(["team", "Alpha", "--approve", "item-3", "--yes"]) == 0
    assert capsys.readouterr().out.strip() == "Approved review item item-3."
    assert rpc_calls(fake, "ResolveGrokBotTeamReviewItem")[-1]["decision"] == (
        "GROK_BOT_TEAM_REVIEW_DECISION_APPROVE"
    )


def test_promote_reports_the_sentence(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    fake.rpcs["PromoteGrokBotMemoriesToTeam"] = {
        "created": [{"factId": "f1", "text": "A"}],
        "keptPrivateCount": 1,
    }
    assert cli.main(["team", "Alpha", "--promote", "f1", "f2", "--yes"]) == 0
    assert capsys.readouterr().out.strip() == (
        "Shared with the team: 1 created, 0 already in the team, 1 kept private."
    )
    assert rpc_calls(fake, "PromoteGrokBotMemoriesToTeam")[-1] == {
        "agentId": "gateway",
        "factIds": ["f1", "f2"],
    }


def test_link_preview_reads_and_sets(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    fake.rpcs["GetGrokBotTeamLinkPreview"] = {"setting": {"enabled": True}}
    assert cli.main(["team", "--link-preview", "42", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"team_id": 42, "enabled": True}
    assert rpc_calls(fake, "GetGrokBotTeamLinkPreview")[-1] == {"teamId": 42}
    assert type(rpc_calls(fake, "GetGrokBotTeamLinkPreview")[-1]["teamId"]) is int
    fake.rpcs["SetGrokBotTeamLinkPreview"] = {"setting": {"enabled": False}}
    assert cli.main(["team", "--link-preview", "42", "--set", "off", "--yes"]) == 0
    assert capsys.readouterr().out.strip() == "Link previews are off for team 42."
    assert rpc_calls(fake, "SetGrokBotTeamLinkPreview")[-1] == {
        "teamId": 42,
        "enabled": False,
    }


@pytest.mark.parametrize(
    "argv",
    [
        ["team", "Alpha"],
        ["team", "Alpha", "--summary", "--review"],
        ["team", "--summary"],
        ["team", "--role", "admin", "Alpha", "--summary"],
        ["team", "Alpha", "--status", "approved", "--summary"],
        ["team", "Alpha", "--review", "--limit", "0"],
        ["team", "--set", "on"],
        ["team", "--link-preview", "abc"],
        ["team", "--link-preview", "42", "--set", "on", "Alpha"],
        ["team", "--link-preview", "42", "--summary"],
        ["team", "Alpha", "--approve", ""],
    ],
)
def test_invalid_combinations_send_nothing(monkeypatch, capsys, argv):
    fake = setup_cli(monkeypatch)
    assert cli.main([*argv, "--yes"]) == 1
    assert capsys.readouterr().err.strip()
    assert not any(name != "listAgents" for _, name, _ in fake.calls)


@pytest.mark.parametrize(
    "argv,rpc",
    [
        (["Alpha", "--summary"], "GetGrokBotTeamContextSummary"),
        (["Alpha", "--review"], "ListGrokBotTeamReviewItems"),
        (["Alpha", "--memories"], "ListGrokBotUserBotMemories"),
        (["--link-preview", "42"], "GetGrokBotTeamLinkPreview"),
    ],
)
def test_refused_reads_exit_one_with_the_server_message(monkeypatch, capsys, argv, rpc):
    fake = setup_cli(monkeypatch)
    refuse(fake, rpc)
    assert cli.main(["team", *argv]) == 1
    assert capsys.readouterr().err.strip() == ("Only a team manager can see this.")
    assert cli.main(["team", *argv, "--json"]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert error["message"] == "Only a team manager can see this."
    assert error["exit_code"] == 1


def test_refused_change_exits_one_with_the_server_message(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    refuse(fake, "ResolveGrokBotTeamReviewItem")
    assert cli.main(["team", "Alpha", "--approve", "item-1", "--yes"]) == 1
    assert capsys.readouterr().err.strip() == ("Only a team manager can see this.")


def test_team_list_refusal_is_a_notice(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    refuse(fake, "ListGrokBotTeamAgents")
    assert cli.main(["team"]) == 1
    assert capsys.readouterr().err.strip() == "Only a team manager can see this."
