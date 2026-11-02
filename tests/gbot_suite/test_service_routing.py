import argparse
import json
import threading

import httpx
import pytest

from gbot.context import Context
from gbot.service import conversation, routing
from gbot.service.broker import BrokerTransport, CredentialBroker
from gbot.service.client import GbotService
from gbot.service.routing import ROUTES, Harness, Router
from gbot.service.transport import ContextTransport, FakeTransport
from groken import client as groken_client
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


# Send path: temporal bots use the backend twins, box bots keep the gateway commands.
NOW = 1_800_000_010_000


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(routing, "now_ms", lambda: NOW)


def test_temporal_send_maps_every_documented_field(clock):
    fake = FakeTransport(
        rpcs={"SendGrokBotUserMessage": {"delivery": "X_ACCEPTED_TEMPORAL"}}
    )
    args = {
        "agentId": "t",
        "prompt": "hi",
        "clientNonce": "n1",
        "richText": "<p>hi</p>",
        "replyToId": "r",
        "replyQuote": "q",
        "isFork": True,
        "traceparent": "tp",
        "enterEpochMs": 1_800_000_000_000,
        "composedAtMs": 1_800_000_005_000.7,
        "sessionId": "s",
        "machineId": "m",
        "onePasswordAppInstalled": True,
        "rendersMcpElicitationForms": True,
        "mcpConfigJson": "{}",
        "taskId": "k",
        "language": "en",
        "firstSentAtMs": NOW - 1500.5,
        "directAddressedAcceptance": True,
        "unrelated": "dropped",
    }
    assert routed(fake).command("sendPrompt", args) == {"accepted": True}
    assert fake.calls == [
        (
            "rpc",
            "SendGrokBotUserMessage",
            {
                "agentId": "t",
                "messageId": "n1",
                "text": "hi",
                "sentAtMs": str(NOW),
                "richText": "<p>hi</p>",
                "replyToId": "r",
                "replyQuote": "q",
                "traceparent": "tp",
                "mcpConfigJson": "{}",
                "taskId": "k",
                "language": "en",
                "isFork": True,
                "attachmentPaths": [],
                "attachmentNames": [],
                "enterEpochMs": "1800000000000",
                "composedAtMs": "1800000005000",
                "sessionId": "s",
                "machineId": "m",
                "onePasswordAppInstalled": True,
                "rendersMcpElicitationForms": True,
                "firstSentAgeMs": "1500",
            },
        )
    ]


def test_temporal_send_minimal_and_false_flags(clock):
    fake = FakeTransport(rpcs={"SendGrokBotUserMessage": {"delivery": "DUPLICATE"}})
    args = {
        "agentId": "t",
        "prompt": "hi",
        "clientNonce": "n1",
        "isFork": False,
        "sessionId": "",
        "machineId": "",
        "onePasswordAppInstalled": False,
        "attachmentPaths": ["p"],
        "attachmentNames": ["a.txt"],
        "firstSentAtMs": NOW + 99,
    }
    assert routed(fake).command("sendPrompt", args) == {"accepted": True}
    assert fake.calls[0][2] == {
        "agentId": "t",
        "messageId": "n1",
        "text": "hi",
        "sentAtMs": str(NOW),
        "attachmentPaths": ["p"],
        "attachmentNames": ["a.txt"],
        "firstSentAgeMs": "0",
    }


@pytest.mark.parametrize(
    "delivery", ["X_ACCEPTED_BOX", "X_ACCEPTED_TEMPORAL", "X_DUPLICATE"]
)
def test_temporal_send_accepted_outcomes(clock, delivery):
    fake = FakeTransport(rpcs={"SendGrokBotUserMessage": {"delivery": delivery}})
    reply = routed(fake).command(
        "sendPrompt", {"agentId": "t", "prompt": "hi", "clientNonce": "n"}
    )
    assert reply == {"accepted": True}


@pytest.mark.parametrize(
    "reply, message",
    [
        ({"delivery": "X_REFUSED"}, "Send refused: X_REFUSED"),
        ({}, "Send refused: unknown delivery"),
        ({"delivery": "X_SOMETHING_NEW"}, "Send refused: X_SOMETHING_NEW"),
        (
            {"refusal": {"failureCode": "busy", "message": "Try later"}},
            "Send refused: busy: Try later",
        ),
    ],
)
def test_temporal_send_refusals_never_fall_back(clock, reply, message):
    fake = FakeTransport(
        {"sendPrompt": {"accepted": True}}, {"SendGrokBotUserMessage": reply}
    )
    with pytest.raises(ValueError, match=message):
        routed(fake).command(
            "sendPrompt", {"agentId": "t", "prompt": "hi", "clientNonce": "n"}
        )
    assert [call[0] for call in fake.calls] == ["rpc"]


def test_temporal_send_transport_error_never_falls_back(clock):
    fake = FakeTransport(
        {"sendPrompt": {"accepted": True}},
        {"SendGrokBotUserMessage": ConnectError(503, "unavailable")},
    )
    with pytest.raises(ConnectError):
        routed(fake).command(
            "sendPrompt", {"agentId": "t", "prompt": "hi", "clientNonce": "n"}
        )
    assert [call[0] for call in fake.calls] == ["rpc"]


def test_temporal_send_needs_a_nonce(clock):
    fake = FakeTransport({"sendPrompt": {}}, {"SendGrokBotUserMessage": {}})
    with pytest.raises(ValueError, match="clientNonce"):
        routed(fake).command("sendPrompt", {"agentId": "t", "prompt": "hi"})
    assert fake.calls == []


@pytest.mark.parametrize("harness", [None, "box", "other"])
def test_box_send_and_status_stay_on_gateway(harness):
    fake = FakeTransport(
        {"sendPrompt": {"accepted": True}, "promptAcceptanceStatus": {"x": 1}},
        {"SendGrokBotUserMessage": {}, "GetGrokBotSendStatus": {}},
    )
    registry = Harness()
    registry.learn([{"id": "t", "harness": "temporal"}])
    row: dict[str, object] = {"id": "b"}
    if harness:
        row["harness"] = harness
    registry.learn([row])
    router = Router(fake, registry)
    send = {"agentId": "b", "prompt": "hi", "clientNonce": "n"}
    assert router.command("sendPrompt", send) == {"accepted": True}
    status = {"agentId": "b", "clientNonce": "n"}
    assert router.command("promptAcceptanceStatus", status) == {"x": 1}
    assert fake.calls == [
        ("command", "sendPrompt", send),
        ("command", "promptAcceptanceStatus", status),
    ]


def test_temporal_status_request_mapping(clock):
    fake = FakeTransport(rpcs={"GetGrokBotSendStatus": {"outcome": "X_NOT_FOUND"}})
    args = {
        "agentId": "t",
        "clientNonce": "n",
        "sessionId": "s",
        "taskId": "k",
        "firstSentAtMs": NOW - 20,
        "accountSlot": "host",
    }
    assert routed(fake).command("promptAcceptanceStatus", args) == {
        "outcome": "not-found"
    }
    assert fake.calls == [
        (
            "rpc",
            "GetGrokBotSendStatus",
            {
                "agentId": "t",
                "messageId": "n",
                "sessionId": "s",
                "taskId": "k",
                "firstSentAgeMs": "20",
            },
        )
    ]


def _record(status, **extra):
    return {
        "accountSlot": "host",
        "clientNonce": "n",
        "agentId": "t",
        "inputDigest": "",
        "status": status,
        **extra,
    }


@pytest.mark.parametrize(
    "reply, expected",
    [
        ({"outcome": "X_NOT_FOUND"}, {"outcome": "not-found"}),
        ({}, {"outcome": "unknown-durability"}),
        ({"outcome": "X_UNSPECIFIED"}, {"outcome": "unknown-durability"}),
        (
            {"outcome": "X_FOUND", "status": "X_MYSTERY"},
            {"outcome": "unknown-durability"},
        ),
        (
            {
                "outcome": "X_FOUND",
                "status": "X_ACCEPTED",
                "acceptedAtMs": "1800000000000",
                "echoEntryId": "e1",
                "rejectionCode": "ignored",
            },
            _record(
                "accepted",
                acceptedAtMs=1_800_000_000_000,
                echoEntryId="e1",
                rejectionCode=None,
            ),
        ),
        (
            {"outcome": "X_FOUND", "status": "X_PENDING"},
            _record("pending", acceptedAtMs=0, echoEntryId=None, rejectionCode=None),
        ),
        (
            {
                "outcome": "X_FOUND",
                "record": {"status": "X_REJECTED", "rejectionCode": "too_long"},
            },
            _record(
                "rejected", acceptedAtMs=0, echoEntryId=None, rejectionCode="too_long"
            ),
        ),
    ],
)
def test_temporal_status_outcomes(clock, reply, expected):
    fake = FakeTransport(
        {"promptAcceptanceStatus": {}}, {"GetGrokBotSendStatus": reply}
    )
    result = routed(fake).command(
        "promptAcceptanceStatus", {"agentId": "t", "clientNonce": "n"}
    )
    assert result == expected
    assert [call[0] for call in fake.calls] == ["rpc"]


def test_temporal_send_retry_keeps_the_message_id(clock):
    fake = FakeTransport(
        {"getAgentTranscriptTail": {"entries": []}},
        {"SendGrokBotUserMessage": {"delivery": "X_ACCEPTED_TEMPORAL"}},
    )
    router = routed(fake)
    first = conversation.send(router, "t", "hi")
    again = conversation.send(router, "t", "hi", nonce=first.nonce)
    assert first.accepted and again.accepted
    sends = [
        args for kind, name, args in fake.calls if name == "SendGrokBotUserMessage"
    ]
    assert [args["messageId"] for args in sends] == [first.nonce, first.nonce]
    assert not [call for call in fake.calls if call[1] == "sendPrompt"]


def test_temporal_send_refreshes_once_and_retries_the_same_message_id(
    clock, monkeypatch
):
    bodies = []

    def handle(request):
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(401, text="expired")
        return httpx.Response(200, json={"delivery": "X_ACCEPTED_TEMPORAL"})

    sand = groken_client.SandClient.__new__(groken_client.SandClient)
    sand.access_token = "fake"
    sand.machine_id = "machine"
    sand.client_version = "0.0.0"
    sand.http = httpx.Client(transport=httpx.MockTransport(handle))
    refreshed = []
    monkeypatch.setattr(sand, "_relogin_once", lambda: refreshed.append(1) or True)

    class Backend:
        def command(self, name, args=None):
            pytest.fail("a temporal send must not reach the gateway")

        def rpc(self, method, payload):
            return sand.unary(groken_client.GROK_BOT, method, dict(payload))

    registry = Harness()
    registry.learn([{"id": "t", "harness": "temporal"}])
    reply = Router(Backend(), registry).command(
        "sendPrompt", {"agentId": "t", "prompt": "hi", "clientNonce": "n"}
    )
    assert reply == {"accepted": True}
    assert refreshed == [1]
    assert len(bodies) == 2 and bodies[0] == bodies[1]
    assert bodies[0]["messageId"] == "n"
