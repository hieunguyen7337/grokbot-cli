import json
from dataclasses import asdict

import pytest

from gbot.service import team_bots
from gbot.service.errors import refusal
from gbot.service.fake import load_fake
from gbot.service.transport import FakeTransport
from groken.client import ConnectError

REFUSED = json.dumps(
    {"code": "permission_denied", "message": "Only a team manager can see this."}
)


def sent(fake: FakeTransport, name: str) -> dict[str, object]:
    return [payload for _, method, payload in fake.calls if method == name][-1]


def test_requests_send_gateway_ids_and_full_names():
    fake = FakeTransport(rpcs=team_bots.DEMO_RPCS)
    team_bots.team_agents(fake)
    assert sent(fake, "ListGrokBotTeamAgents") == {}
    team_bots.team_agents(fake, role="admin")
    assert sent(fake, "ListGrokBotTeamAgents") == {"role": "admin"}
    team_bots.context_summary(fake, "gateway")
    assert sent(fake, "GetGrokBotTeamContextSummary") == {"agentId": "gateway"}
    team_bots.review_items(fake, "gateway")
    assert sent(fake, "ListGrokBotTeamReviewItems") == {
        "agentId": "gateway",
        "statuses": ["GROK_BOT_TEAM_REVIEW_ITEM_STATUS_PENDING"],
        "limit": 100,
    }
    team_bots.review_items(fake, "gateway", ("approved", "rejected"), limit=20)
    assert sent(fake, "ListGrokBotTeamReviewItems") == {
        "agentId": "gateway",
        "statuses": [
            "GROK_BOT_TEAM_REVIEW_ITEM_STATUS_APPROVED",
            "GROK_BOT_TEAM_REVIEW_ITEM_STATUS_REJECTED",
        ],
        "limit": 20,
    }
    team_bots.review_items(fake, "gateway", ())
    assert sent(fake, "ListGrokBotTeamReviewItems")["statuses"] == [
        "GROK_BOT_TEAM_REVIEW_ITEM_STATUS_PENDING"
    ]
    with pytest.raises(ValueError, match="pending, approved or rejected"):
        team_bots.review_items(fake, "gateway", ("unspecified",))
    team_bots.resolve_review_item(fake, "gateway", "item-1", approve=True)
    assert sent(fake, "ResolveGrokBotTeamReviewItem") == {
        "agentId": "gateway",
        "itemId": "item-1",
        "decision": "GROK_BOT_TEAM_REVIEW_DECISION_APPROVE",
    }
    team_bots.resolve_review_item(fake, "gateway", "item-1", approve=False)
    assert sent(fake, "ResolveGrokBotTeamReviewItem")["decision"] == (
        "GROK_BOT_TEAM_REVIEW_DECISION_REJECT"
    )
    team_bots.bot_memories(fake, "gateway")
    assert sent(fake, "ListGrokBotUserBotMemories") == {"agentId": "gateway"}
    team_bots.promote_memories(fake, "gateway", ["fact-1", "fact-2"])
    assert sent(fake, "PromoteGrokBotMemoriesToTeam") == {
        "agentId": "gateway",
        "factIds": ["fact-1", "fact-2"],
    }
    team_bots.link_preview(fake, 42)
    assert sent(fake, "GetGrokBotTeamLinkPreview") == {"teamId": 42}
    assert type(sent(fake, "GetGrokBotTeamLinkPreview")["teamId"]) is int
    team_bots.set_link_preview(fake, 42, False)
    assert sent(fake, "SetGrokBotTeamLinkPreview") == {"teamId": 42, "enabled": False}


@pytest.mark.parametrize(
    "names,field",
    [
        (team_bots.ITEM_STATUSES, "status"),
        (team_bots.MEMORY_ACTIONS, "memory-action"),
        (team_bots.SKILL_ACTIONS, "skill-action"),
    ],
)
def test_enums_in_all_three_forms(names, field):
    prefix = "GROK_BOT_TEAM_REVIEW_ITEM_STATUS_"
    for number, name in enumerate(names):
        for value in (number, name.upper(), prefix + name.upper(), name):
            if field == "status":
                fake = FakeTransport(
                    rpcs={"ListGrokBotTeamReviewItems": {"items": [{"status": value}]}}
                )
                (item,) = team_bots.review_items(fake, "gateway")
                assert item.status == name
            else:
                change = {"action": value}
                kind = "skill" if field == "skill-action" else "memory"
                item = {"change": {kind: change}}
                fake = FakeTransport(
                    rpcs={"ListGrokBotTeamReviewItems": {"items": [item]}}
                )
                (parsed,) = team_bots.review_items(fake, "gateway")
                assert parsed.change.action == name
    assert team_bots._enum(999, names) == "unknown"
    assert team_bots._enum(-1, names) == "unknown"
    assert team_bots._enum("future", names) == "unknown"
    assert team_bots._enum("GROK_BOT_TEAM_FUTURE", names) == "unknown"
    assert team_bots._enum(True, names) == "unknown"
    assert team_bots._enum(None, names) == "unknown"


def test_change_kinds():
    items = [
        {
            "itemId": "m",
            "status": "GROK_BOT_TEAM_REVIEW_ITEM_STATUS_PENDING",
            "proposedByUserId": "7",
            "createdAtMs": "1800000000000",
            "change": {
                "memory": {
                    "action": "WRITE",
                    "text": "Prefers short replies",
                    "memoryType": "preference",
                },
                "method": "from chat",
                "summary": "Remember a preference",
            },
        },
        {
            "itemId": "s",
            "status": 1,
            "change": {
                "skill": {
                    "action": "UPDATE",
                    "name": "triage",
                    "description": "Sort tickets",
                    "content": "Steps",
                }
            },
        },
        {
            "itemId": "f",
            "status": 2,
            "reviewedByUserId": "8",
            "reviewedAtMs": "5",
            "change": {
                "folderMemory": {
                    "action": "forget",
                    "memoryType": "project",
                    "text": "Old note",
                    "path": "notes/old.md",
                    "metaJson": "{}",
                }
            },
        },
        {"itemId": "u", "change": {"summary": "Something new"}},
    ]
    fake = FakeTransport(rpcs={"ListGrokBotTeamReviewItems": {"items": items}})
    memory, skill, folder, unknown = team_bots.review_items(fake, "gateway")
    assert memory == team_bots.ReviewItem(
        "m",
        "pending",
        proposed_by_user_id=7,
        created_at_ms=1_800_000_000_000,
        change=team_bots.ReviewChange(
            "memory",
            "write",
            text="Prefers short replies",
            memory_type="preference",
            method="from chat",
            summary="Remember a preference",
        ),
    )
    assert skill.status == "pending"
    assert skill.change == team_bots.ReviewChange(
        "skill",
        "update",
        name="triage",
        description="Sort tickets",
        content="Steps",
    )
    assert folder.status == "approved"
    assert (folder.reviewed_by_user_id, folder.reviewed_at_ms) == (8, 5)
    assert folder.change == team_bots.ReviewChange(
        "folder_memory",
        "forget",
        text="Old note",
        path="notes/old.md",
        memory_type="project",
    )
    assert unknown.status == "unspecified"
    assert unknown.change == team_bots.ReviewChange("unknown", summary="Something new")


def test_resolve_returns_the_changed_item_and_falls_back_to_the_request():
    fake = FakeTransport(
        rpcs={
            "ResolveGrokBotTeamReviewItem": {
                "item": {"itemId": "item-9", "status": "REJECTED"}
            }
        }
    )
    assert team_bots.resolve_review_item(fake, "gateway", "item-9", False).status == (
        "rejected"
    )
    fake.rpcs["ResolveGrokBotTeamReviewItem"] = {}
    item = team_bots.resolve_review_item(fake, "gateway", "item-9", True)
    assert (item.item_id, item.status) == ("item-9", "unspecified")


def test_missing_and_odd_fields_get_defaults():
    fake = FakeTransport(
        rpcs={
            "GetGrokBotTeamContextSummary": {
                "summary": {"prose": 3, "memoryVersion": "2", "generatedAtMs": "x"},
                "stale": "yes",
                "skills": ["triage", {"name": "reply"}, {"name": ""}, 4],
                "learned": [
                    {"factId": "f1", "text": "Likes tea", "learnedAtMs": "9"},
                    "junk",
                ],
                "memoryCount": "many",
            },
            "ListGrokBotUserBotMemories": {"memories": "nope"},
            "ListGrokBotTeamAgents": {
                "entries": [
                    {"agent": {"agentId": "a1", "name": "Ops"}, "userTurns": "3"},
                    "junk",
                    {"id": "a2", "signals": {"teammateTurns": 2, "lastTurnAtMs": "5"}},
                ],
                "slackConnections": [{}, {}],
                "teamsConnections": "two",
            },
        }
    )
    summary = team_bots.context_summary(fake, "gateway")
    assert summary == team_bots.ContextSummary(
        memory_version=2,
        skills=("triage", "reply"),
        learned=(team_bots.MemoryFact("f1", "Likes tea", 9),),
    )
    assert team_bots.bot_memories(fake, "gateway") == ()
    agents = team_bots.team_agents(fake)
    assert agents == team_bots.TeamAgents(
        (
            team_bots.TeamAgent("a1", "Ops", user_turns=3),
            team_bots.TeamAgent("a2", "", teammate_turns=2, last_turn_at_ms=5),
        ),
        slack_connections=2,
        teams_connections=0,
    )
    fake.rpcs["GetGrokBotTeamContextSummary"] = {}
    assert team_bots.context_summary(fake, "gateway") == team_bots.ContextSummary()


def test_empty_replies_and_unimplemented_are_empty():
    assert team_bots.team_agents(FakeTransport(rpcs={"ListGrokBotTeamAgents": {}})) == (
        team_bots.TeamAgents()
    )
    fake = FakeTransport(
        rpcs={
            "ListGrokBotTeamAgents": ConnectError(
                501, '{"code": "unimplemented", "message": "Not here."}'
            )
        }
    )
    assert team_bots.team_agents(fake) == team_bots.TeamAgents()


@pytest.mark.parametrize(
    "call,rpc",
    [
        (
            lambda t: team_bots.context_summary(t, "gateway"),
            "GetGrokBotTeamContextSummary",
        ),
        (lambda t: team_bots.bot_memories(t, "gateway"), "ListGrokBotUserBotMemories"),
        (lambda t: team_bots.review_items(t, "gateway"), "ListGrokBotTeamReviewItems"),
        (lambda t: team_bots.team_agents(t), "ListGrokBotTeamAgents"),
        (lambda t: team_bots.link_preview(t, 1), "GetGrokBotTeamLinkPreview"),
    ],
)
def test_refusals_raise_with_the_server_message(call, rpc):
    fake = FakeTransport(rpcs={rpc: ConnectError(403, REFUSED)})
    with pytest.raises(ConnectError) as caught:
        call(fake)
    found = refusal(caught.value)
    assert found is not None
    assert (found.code, found.message) == (
        "permission_denied",
        "Only a team manager can see this.",
    )


def test_promote_result_and_sentence():
    fake = FakeTransport(
        rpcs={
            "PromoteGrokBotMemoriesToTeam": {
                "created": [{"factId": "f1", "text": "A", "learnedAtMs": "1"}],
                "alreadyInTeam": [{"factId": "f2", "text": "B"}],
                "keptPrivateCount": 3,
            }
        }
    )
    result = team_bots.promote_memories(fake, "gateway", ["f1", "f2"])
    assert result == team_bots.PromoteResult(
        (team_bots.MemoryFact("f1", "A", 1),),
        (team_bots.MemoryFact("f2", "B", 0),),
        3,
    )
    assert team_bots.promote_sentence(result) == (
        "Shared with the team: 1 created, 1 already in the team, 3 kept private."
    )
    assert team_bots.promote_sentence(team_bots.PromoteResult()) == (
        "Shared with the team: 0 created, 0 already in the team, 0 kept private."
    )


def test_link_preview_reads_and_sets_the_setting():
    fake = FakeTransport(
        rpcs={
            "GetGrokBotTeamLinkPreview": {"setting": {"enabled": True}},
            "SetGrokBotTeamLinkPreview": {"setting": {"enabled": False}},
        }
    )
    assert team_bots.link_preview(fake, 5) is True
    assert team_bots.set_link_preview(fake, 5, False) is False
    fake.rpcs["GetGrokBotTeamLinkPreview"] = {}
    assert team_bots.link_preview(fake, 5) is False


def test_review_item_and_change_are_plain_data():
    item = team_bots.ReviewItem("x", "pending")
    assert asdict(item)["change"] == {
        "kind": "unknown",
        "action": "unspecified",
        "text": "",
        "name": "",
        "description": "",
        "content": "",
        "path": "",
        "memory_type": "",
        "method": "",
        "summary": "",
    }


def test_date_text():
    assert team_bots.date_text(0) == ""
    assert team_bots.date_text(86_400_000) == "1970-01-02"
    assert team_bots.date_text(10**30) == ""


def test_demo_replies_cover_every_rpc():
    transport = load_fake().transport
    assert set(team_bots.RPCS) <= transport.rpcs.keys()
    assert team_bots.team_agents(transport) == team_bots.TeamAgents()
