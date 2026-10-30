import argparse
import threading

import pytest

from gbot.context import Context
from gbot.service.broker import BrokerTransport, CredentialBroker
from gbot.service.client import GbotService
from gbot.service.routing import ROUTES, Harness, Router
from gbot.service.transport import ContextTransport, FakeTransport
from groken.client import ConnectError

# Independent wire expectations, including fields that must not reach the backend.
CASES = [
    (
        "setAgentUnread",
        {"id": "t", "isUnread": True},
        "SetGrokBotAgentClientState",
        {"agentId": "t", "markUnread": True},
    ),
    (
        "setAgentHiddenFromSidebar",
        {"id": "t", "isHidden": False},
        "SetGrokBotAgentClientState",
        {"agentId": "t", "hiddenFromSidebar": False},
    ),
    (
        "setAgentNotifyOnUpdates",
        {"id": "t", "isEnabled": True},
        "SetGrokBotAgentClientState",
        {"agentId": "t", "notifyOnUpdatesEnabled": True},
    ),
    (
        "setAgentDraftingDisabled",
        {"id": "t", "isDisabled": True},
        "SetGrokBotAgentDraftingDisabled",
        {"id": "t", "disabled": True},
    ),
    (
        "dismissAgentSuggestions",
        {"agentId": "t", "suggestionIds": ["s"], "reason": "acted"},
        "DismissGrokBotAgentSuggestions",
        {
            "agentId": "t",
            "suggestionIds": ["s"],
            "reason": "GROK_BOT_AGENT_SUGGESTION_DISMISS_REASON_ACTED",
        },
    ),
    (
        "voteFeedback",
        {
            "agentId": "t",
            "entryId": "e",
            "action": "up",
            "comment": "fine",
            "sessionId": "s",
        },
        "VoteGrokBotFeedback",
        {
            "agentId": "t",
            "entryId": "e",
            "action": "GROK_BOT_FEEDBACK_ACTION_UP",
            "categories": [],
            "comment": "fine",
            "sessionId": "s",
        },
    ),
    (
        "reactToMessage",
        {"agentId": "t", "entryId": "e", "emoji": ":)", "sessionId": "s"},
        "ReactToGrokBotMessage",
        {"agentId": "t", "entryId": "e", "emoji": ":)", "sessionId": "s"},
    ),
    (
        "createThreadFromMessage",
        {"agentId": "t", "entryId": "e", "sessionId": "ignored"},
        "CreateGrokBotThreadFromMessage",
        {"agentId": "t", "entryId": "e"},
    ),
    (
        "resolveConnectorGrant",
        {
            "agentId": "t",
            "requestId": "r",
            "entryId": "e",
            "resolution": "always_all_team_bots",
            "sessionId": "s",
        },
        "ResolveGrokBotConnectorGrant",
        {
            "agentId": "t",
            "requestId": "r",
            "entryId": "e",
            "resolution": "GROK_BOT_CONNECTOR_GRANT_RESOLUTION_ALWAYS_ALL_TEAM_BOTS",
            "sessionId": "s",
        },
    ),
    ("getSubagents", {"id": "t"}, "ListGrokBotSubagents", {"agentId": "t"}),
    (
        "getAgentTasks",
        {"agentId": "t"},
        "ListGrokBotAgentTasks",
        {"agentId": "t", "includeRecentlyDone": True},
    ),
    (
        "markAgentTaskDone",
        {"agentId": "t", "taskId": "k"},
        "MarkGrokBotAgentTaskDone",
        {"agentId": "t", "taskId": "k"},
    ),
    (
        "markAgentTaskRead",
        {"agentId": "t", "taskId": "k", "entryId": "e"},
        "MarkGrokBotAgentTaskRead",
        {"agentId": "t", "taskId": "k", "entryId": "e"},
    ),
    (
        "setAgentTaskPinned",
        {"agentId": "t", "taskId": "k", "isPinned": False},
        "SetGrokBotAgentTaskPinned",
        {"agentId": "t", "taskId": "k", "pinned": False},
    ),
    (
        "interruptAgentRun",
        {"id": "t", "sessionId": ""},
        "InterruptGrokBotAgentRun",
        {"agentId": "t", "reason": "user_interrupt", "sessionId": ""},
    ),
    (
        "startFreshConversation",
        {"id": "t", "sessionId": ""},
        "StartFreshGrokBotConversation",
        {"agentId": "t", "sessionId": ""},
    ),
    (
        "rollBackConversation",
        {"id": "t", "sessionId": ""},
        "RollBackGrokBotConversation",
        {"agentId": "t", "sessionId": ""},
    ),
]
TASK = {
    "id": "k",
    "name": "Task",
    "description": "Work",
    "status": " DONE ",
    "updatedAtMs": "12",
    "unreadEntryId": "e",
    "unreadPreview": "Ready",
    "unreadAtMs": "13",
    "pinnedAtMs": "0",
    "subagentIds": ["s"],
    "followed": True,
}
TASK_REPLY = {key: value for key, value in TASK.items() if key != "followed"}
TASK_REPLY.update(status="done", updatedAtMs=12, unreadAtMs=13, pinnedAtMs=0)


def routed(fake):
    registry = Harness()
    registry.learn([{"id": "t", "harness": "temporal"}])
    return Router(fake, registry)


@pytest.mark.parametrize("name,args,rpc,payload", CASES)
def test_temporal_mapping(name, args, rpc, payload):
    assert set(ROUTES) == {case[0] for case in CASES}
    reply, expected = {}, None
    if name == "setAgentHiddenFromSidebar":
        reply, expected = {"state": {"updatedAtMs": "19"}}, {"stateUpdatedAt": 19}
    elif name == "interruptAgentRun":
        reply = expected = {"hadActiveRun": True}
    elif name == "getSubagents":
        reply = {
            "subagents": [
                {
                    "subagentId": "s",
                    "subagentType": "work",
                    "title": "Helper",
                    "startedAtMs": "4",
                    "freshUntilMs": "8",
                    "status": "done",
                }
            ]
        }
        expected = [
            {
                "subagentId": "s",
                "subagentType": "work",
                "title": "Helper",
                "startedAtMs": 4,
                "freshUntilMs": 8,
                "status": "running",
            }
        ]
    elif name in {
        "getAgentTasks",
        "markAgentTaskDone",
        "markAgentTaskRead",
        "setAgentTaskPinned",
    }:
        reply, expected = {"tasks": [TASK]}, [TASK_REPLY]
    fake = FakeTransport({name: None}, {rpc: reply})
    router = routed(fake)
    assert router.command(name, {**args, "unrelated": "discard"}) == expected
    router.harness.drain()
    calls = [("rpc", rpc, payload)]
    if name == "setAgentNotifyOnUpdates":
        calls.append(("command", name, {**args, "unrelated": "discard"}))
    assert fake.calls == calls


@pytest.mark.parametrize("name,args,rpc,payload", CASES)
@pytest.mark.parametrize("harness", ["box", None])
def test_gateway_unchanged(name, args, rpc, payload, harness):
    fake = FakeTransport({name: {"unchanged": True}})
    registry = Harness()
    if harness:
        registry.learn([{"id": "t", "harness": harness}])
    assert Router(fake, registry).command(name, args) == {"unchanged": True}
    assert fake.calls == [("command", name, args)]


@pytest.mark.parametrize(
    "creation", ["createAgent", "createGroup", "createAgentFromTemplate"]
)
def test_learning(creation):
    fake = FakeTransport(
        {
            "listAgents": [{"id": "t", "harness": "temporal"}],
            creation: {"agent": {"id": "new", "harness": "temporal"}},
        },
        {
            "ListGrokBotAgents": {
                "agents": [
                    {"id": "server", "agentId": "gateway", "harness": "temporal"}
                ]
            }
        },
    )
    router = Router(fake, Harness())
    router.command("listAgents")
    router.command(creation)
    router.rpc("ListGrokBotAgents", {})
    router.harness.learn([{"id": "t"}, {"id": "unknown"}, None])
    assert all(router.harness.temporal(i) for i in ("t", "new", "gateway"))
    assert not router.harness.temporal("server")
    assert not router.harness.temporal("unknown")
    router.harness.learn([{"id": "t", "harness": "box"}])
    assert not router.harness.temporal("t")
    assert not Harness().temporal("new")


def test_mixed_delete():
    errors = {
        "missing": ConnectError(404, "gone"),
        "denied": ConnectError(400, '{"code":"permission_denied"}'),
        "failed": ConnectError(503, "offline"),
    }

    def delete(payload):
        if payload["id"] in errors:
            raise errors[payload["id"]]
        return {}

    def gateway(payload):
        if payload["ids"] == ["box", "unknown"]:
            return {"transcript": ["box transcript"], "refusedAgentIds": ["box"]}
        raise RuntimeError("mirror unavailable")

    fake = FakeTransport({"deleteAgents": gateway}, {"DeleteGrokBotAgent": delete})
    router = routed(fake)
    router.harness.learn({"id": i, "harness": "temporal"} for i in errors)
    assert router.command(
        "deleteAgents", {"ids": ["t", "box", "missing", "denied", "failed", "unknown"]}
    ) == {
        "transcript": ["box transcript"],
        "refusedAgentIds": ["box", "denied"],
        "failedAgentIds": ["failed"],
    }
    router.harness.drain()
    assert fake.calls == [
        *(
            ("rpc", "DeleteGrokBotAgent", {"id": i})
            for i in ("t", "missing", "denied", "failed")
        ),
        ("command", "deleteAgents", {"ids": ["box", "unknown"]}),
        ("command", "deleteAgents", {"ids": ["t", "missing"]}),
    ]


def test_delete_gateway_and_temporal_only():
    fake = FakeTransport(
        {"deleteAgents": {"transcript": []}}, {"DeleteGrokBotAgent": {}}
    )
    router = routed(fake)
    assert router.command("deleteAgents", {"ids": ["box"]}) == {"transcript": []}
    assert router.command("deleteAgents", {"ids": ["t"]}) == {"transcript": []}
    router.harness.drain()
    assert fake.calls == [
        ("command", "deleteAgents", {"ids": ["box"]}),
        ("rpc", "DeleteGrokBotAgent", {"id": "t"}),
        ("command", "deleteAgents", {"ids": ["t"]}),
    ]


def test_notify_mirror_is_background_and_failure_ignored():
    entered, release = threading.Event(), threading.Event()

    def mirror(args):
        entered.set()
        assert release.wait(5)
        raise RuntimeError("offline")

    fake = FakeTransport(
        {"setAgentNotifyOnUpdates": mirror}, {"SetGrokBotAgentClientState": {}}
    )
    router = routed(fake)
    try:
        assert (
            router.command("setAgentNotifyOnUpdates", {"id": "t", "isEnabled": False})
            is None
        )
        assert entered.wait(5)
    finally:
        release.set()
        router.harness.drain()
    assert fake.calls == [
        (
            "rpc",
            "SetGrokBotAgentClientState",
            {"agentId": "t", "notifyOnUpdatesEnabled": False},
        ),
        ("command", "setAgentNotifyOnUpdates", {"id": "t", "isEnabled": False}),
    ]


@pytest.mark.parametrize(
    "failure",
    [
        {"refusal": {"failureCode": "denied", "message": "No access"}},
        ConnectError(501, "unimplemented"),
    ],
)
def test_failure_never_falls_back(failure):
    fake = FakeTransport(rpcs={"ReactToGrokBotMessage": failure})
    with pytest.raises(
        ValueError if isinstance(failure, dict) else ConnectError,
        match="Answer refused: denied: No access"
        if isinstance(failure, dict)
        else "unimplemented",
    ):
        routed(fake).command(
            "reactToMessage", {"agentId": "t", "entryId": "e", "emoji": ":)"}
        )
    assert len(fake.calls) == 1 and fake.calls[0][0] == "rpc"


@pytest.mark.parametrize(
    "command",
    [
        "sendPrompt",
        "promptAcceptanceStatus",
        "setGroupMembers",
        "updateAgent",
        "createAgent",
    ],
)
def test_deliberate_gateway_routes(command):
    fake = FakeTransport({command: None})
    assert routed(fake).command(command, {"agentId": "t"}) is None
    assert fake.calls == [("command", command, {"agentId": "t"})]


@pytest.mark.parametrize(
    "name",
    [
        "voteFeedback",
        "reactToMessage",
        "resolveConnectorGrant",
        "interruptAgentRun",
        "startFreshConversation",
        "rollBackConversation",
    ],
)
@pytest.mark.parametrize("session", [None, "", "s"])
def test_session_rules(name, session):
    _, args, rpc, payload = next(case for case in CASES if case[0] == name)
    args, payload = dict(args), dict(payload)
    args["sessionId"] = session
    payload.pop("sessionId", None)
    if session is not None and (
        session
        or name
        in {"interruptAgentRun", "startFreshConversation", "rollBackConversation"}
    ):
        payload["sessionId"] = session
    fake = FakeTransport(rpcs={rpc: {}})
    routed(fake).command(name, args)
    assert fake.calls == [("rpc", rpc, payload)]


def test_unread_and_reply_defaults():
    fake = FakeTransport(
        rpcs={
            "SetGrokBotAgentClientState": {},
            "ListGrokBotAgentTasks": {
                "tasks": [{"id": "x", "status": "mystery", "subagentIds": []}]
            },
            "ListGrokBotSubagents": {
                "subagents": [{"subagentId": "s", "freshUntilMs": "0"}]
            },
        }
    )
    router = routed(fake)
    assert (
        router.command(
            "setAgentUnread",
            {"id": "t", "isUnread": False, "markFollowedThreadsRead": True},
        )
        is None
    )
    assert fake.calls[-1][2] == {
        "agentId": "t",
        "markRead": True,
        "markFollowedThreadsRead": True,
    }
    assert (
        router.command("setAgentHiddenFromSidebar", {"id": "t", "isHidden": True})
        is None
    )
    assert router.command("getAgentTasks", {"agentId": "t"}) == [
        {"id": "x", "name": "", "description": "", "status": "open", "updatedAtMs": 0}
    ]
    assert router.command("getSubagents", {"id": "t"}) == [
        {
            "subagentId": "s",
            "subagentType": "",
            "title": "",
            "status": "running",
            "startedAtMs": 0,
        }
    ]


def test_context_and_service_use_shared_registry(monkeypatch):
    fake = FakeTransport(
        {"listAgents": [{"id": "t", "harness": "temporal"}]},
        {"ListGrokBotSubagents": {"subagents": []}},
    )
    ctx = Context(argparse.Namespace(debug=False, json=False))
    monkeypatch.setattr(ctx, "manager", lambda: fake)

    class Backend:
        def unary(self, service, method, payload):
            return fake.rpc(method, payload)

    monkeypatch.setattr(ctx, "backend", Backend)
    ContextTransport(ctx).command("listAgents")
    assert ContextTransport(ctx).command("getSubagents", {"id": "t"}) == []
    monkeypatch.setattr(
        BrokerTransport,
        "command",
        lambda self, name, args=None: fake.command(name, args),
    )
    monkeypatch.setattr(
        BrokerTransport, "rpc", lambda self, method, payload: fake.rpc(method, payload)
    )
    service = GbotService(CredentialBroker(dict))
    service.transport.command("listAgents")
    assert service._background_transport.command("getSubagents", {"id": "t"}) == []
    assert service.transport.command("getSubagents", {"id": "t"}) == []
    assert not GbotService(CredentialBroker(dict)).harness.temporal("t")
    assert not Context(argparse.Namespace(debug=False, json=False)).harness.temporal(
        "t"
    )
    service.close()
    ctx.close()
