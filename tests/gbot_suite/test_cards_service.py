from dataclasses import replace

import pytest

from gbot.pending import classify
from gbot.service import cards
from gbot.service.fake import FakeService
from gbot.service.models import Action, Card
from gbot.service.transport import FakeTransport
from groken.client import ConnectError


def card(kind: str, **changes: object) -> Card:
    actions = (
        ("approve", "deny")
        if kind.endswith("draft")
        or kind in {"auto-review-approval", "local-tool-permission", "connector-grant"}
        else ("secret",)
        if kind == "secret-request"
        else ("respond", "dismiss")
    )
    base = Card(
        "bot",
        "Bot",
        "entry",
        "session",
        kind,
        "Summary",
        None,
        actions,
        request_id="request",
        draft={"body": "old"},
        options=["A", "B"],
        fields=[{"id": "name", "required": True}, {"id": "optional"}],
        validate_options=True,
    )
    return replace(base, **changes)


BASE = {"agentId": "bot", "entryId": "entry", "sessionId": "session"}


@pytest.mark.parametrize(
    "kind,action,method,extra",
    [
        (
            "widget",
            Action("respond", value="A"),
            "RespondGrokBotWidget",
            {"value": "A"},
        ),
        ("widget", Action("dismiss"), "DismissGrokBotWidget", {}),
        (
            "user-form",
            Action("respond", fields=(("name", "Ada"),)),
            "SubmitGrokBotUserForm",
            {"values": {"name": "Ada"}, "saveToVault": False, "platform": 1},
        ),
        (
            "user-form",
            Action("dismiss"),
            "DismissGrokBotUserForm",
            {"mode": 1, "platform": 1},
        ),
        ("secret-request", Action("secret"), "SubmitGrokBotSecret", {}),
        *[
            (kind, Action("deny"), "DiscardGrokBotDraft", {})
            for kind in ("email-draft", "slack-draft", "meeting-chat-draft")
        ],
        (
            "email-draft",
            Action("approve"),
            "SendGrokBotDraft",
            {"email": {"from": "", "to": "", "cc": [], "subject": "", "body": "old"}},
        ),
        (
            "email-draft",
            Action("approve", draft={"body": "edited", "unknown": 1}),
            "SendGrokBotDraft",
            {
                "email": {
                    "from": "",
                    "to": "",
                    "cc": [],
                    "subject": "",
                    "body": "edited",
                }
            },
        ),
        (
            "slack-draft",
            Action("approve"),
            "SendGrokBotDraft",
            {"slack": {"body": "old"}},
        ),
        (
            "slack-draft",
            Action(
                "approve",
                draft={
                    "target": "channel",
                    "body": "edited",
                    "workspace": "w",
                    "thread": "t",
                    "unknown": 1,
                },
            ),
            "SendGrokBotDraft",
            {
                "slack": {
                    "target": "channel",
                    "body": "edited",
                    "workspace": "w",
                    "thread": "t",
                }
            },
        ),
    ],
)
def test_plan(kind, action, method, extra):
    assert cards.plan(card(kind), action) == (method, {**BASE, **extra})


@pytest.mark.parametrize("kind", ["auto-review-approval", "local-tool-permission"])
@pytest.mark.parametrize(
    "action,resolution,word",
    [
        (Action("approve"), 1, "approved"),
        (Action("deny"), 2, "denied"),
        (Action("approve", always=True), 3, "always"),
        (Action("deny", never=True), 4, "never"),
    ],
)
def test_resolutions(kind, action, resolution, word):
    item = card(kind)
    if kind == "auto-review-approval" and action.never:
        with pytest.raises(ValueError, match="--never applies only"):
            cards.plan(item, action)
        return
    method = (
        "ResolveGrokBotLocalToolPermission"
        if kind == "local-tool-permission"
        else "ResolveGrokBotAutoReviewApproval"
    )
    expected = {**BASE, "requestId": "request", "resolution": resolution}
    if kind == "auto-review-approval":
        expected.pop("entryId")
        expected["approvalPlatform"] = "desktop"
    assert cards.plan(item, action) == (method, expected)
    transport = FakeTransport(rpcs={method: {"dispatched": True}})
    result = cards.answer(transport, item, action)
    if kind == "local-tool-permission" and word in {"approved", "denied"}:
        word = "allow-once" if action.kind == "approve" else "deny"
    assert result.effect == word


@pytest.mark.parametrize(
    "item,action,message",
    [
        (
            card("widget", allowed_actions=()),
            Action("respond"),
            "widget: answer in the Grok Bot app.",
        ),
        (
            card("widget"),
            Action("approve"),
            "approve cannot answer widget. Use: gbot respond REF or gbot dismiss REF",
        ),
        (
            card("email-draft"),
            Action("approve", always=True),
            "--always and --never do not apply to drafts.",
        ),
        (
            card("email-draft", draft=None),
            Action("deny"),
            "Pending draft is missing its draft record.",
        ),
        (
            card("auto-review-approval", request_id=None),
            Action("deny", never=True),
            "Pending approval is missing its requestId.",
        ),
        (
            card("auto-review-approval"),
            Action("deny", never=True),
            "--never applies only to local-tool-permission. Use: gbot deny REF",
        ),
        (
            card("widget"),
            Action("respond"),
            "Use: gbot respond REF VALUE for a widget.",
        ),
        (
            card("widget"),
            Action("respond", value="C"),
            "Invalid widget value. Options: A | B",
        ),
        (
            card("user-form"),
            Action("respond"),
            "Use: gbot respond REF --field NAME=VALUE for a user-form.",
        ),
        (
            card("user-form"),
            Action("respond", fields=(("", "x"),)),
            "Each --field must have a unique, nonempty NAME=VALUE.",
        ),
        (
            card("user-form"),
            Action("respond", fields=(("name", "x"), ("name", "y"))),
            "Each --field must have a unique, nonempty NAME=VALUE.",
        ),
        (
            card("user-form"),
            Action("respond", fields=(("other", "x"),)),
            "Unknown field id: other. Valid ids: name, optional",
        ),
        (
            card("user-form"),
            Action("respond", fields=(("optional", "x"),)),
            "Missing required field: name",
        ),
    ],
)
def test_errors(item, action, message):
    with pytest.raises(ValueError) as exc:
        cards.plan(item, action)
    assert str(exc.value) == message


@pytest.mark.parametrize(
    "reply,message",
    [
        (
            {"accepted": False},
            "Answer was not accepted; the item may already be answered. Run: gbot approvals",
        ),
        (
            {"refusal": {"failureCode": "blocked", "message": "reason"}},
            "Answer refused: blocked: reason",
        ),
    ],
)
def test_answer_errors(reply, message):
    with pytest.raises(ValueError) as exc:
        cards.answer(
            FakeTransport(rpcs={"RespondGrokBotWidget": reply}),
            card("widget"),
            Action("respond", value="A"),
        )
    assert str(exc.value) == message


def test_answer_happy():
    transport = FakeTransport(rpcs={"RespondGrokBotWidget": {"accepted": True}})
    assert (
        cards.answer(transport, card("widget"), Action("respond", value="A")).effect
        == "answered"
    )
    assert transport.calls == [("rpc", "RespondGrokBotWidget", {**BASE, "value": "A"})]


@pytest.mark.parametrize(
    "reply,message",
    [
        (
            RuntimeError("hidden-value"),
            "Secret was not submitted successfully; no value is displayed.",
        ),
        (
            {"refusal": {"failureCode": "blocked", "message": "hidden-value"}},
            "Answer refused: blocked",
        ),
    ],
)
def test_secret_redaction(reply, message, capsys):
    action = Action("secret", secret="hidden-value")
    with pytest.raises(ValueError) as exc:
        cards.answer(
            FakeTransport(rpcs={"SubmitGrokBotSecret": reply}),
            card("secret-request"),
            action,
        )
    assert str(exc.value) == message
    assert "hidden-value" not in repr(action)
    assert capsys.readouterr() == ("", "")


def test_secret_success():
    transport = FakeTransport(rpcs={"SubmitGrokBotSecret": {"accepted": True}})
    assert (
        cards.answer(
            transport, card("secret-request"), Action("secret", secret="hidden-value")
        ).effect
        == "secret stored"
    )
    assert transport.calls[0][2] == {**BASE, "value": "hidden-value"}


def test_discover_warnings(capsys):
    transport = FakeTransport(
        commands={"getAgentTranscriptTail": ValueError("bad\npage")}
    )
    rows: list[dict[str, object]] = [{"id": "bot", "name": "Bot\nName"}]
    assert cards.discover(transport, rows, all_bots=True) == (
        [],
        ["Bot Name: bad page"],
    )
    assert capsys.readouterr() == ("", "")
    with pytest.raises(ValueError, match="bad"):
        cards.discover(transport, rows, selected="bot")
    transport.commands["getAgentTranscriptTail"] = ConnectError(401, "expired")
    with pytest.raises(ConnectError):
        cards.discover(transport, rows, all_bots=True)


@pytest.mark.parametrize(
    "state,expected",
    [({}, True), ({"respondedValue": "A"}, False), ({"id": "missing"}, False)],
)
def test_still_pending(state, expected):
    entry = {
        "id": "entry",
        "kind": "send-message",
        "message": {"type": "widget", "widget": {}},
        **state,
    }
    transport = FakeTransport(commands={"getAgentTranscriptTail": {"entries": [entry]}})
    assert cards.still_pending(transport, card("widget")) is expected
    assert transport.calls[0][2] == {"id": "bot", "limit": 100, "sessionId": "session"}


def test_paging():
    entry = {
        "id": "entry",
        "kind": "send-message",
        "message": {"type": "widget", "widget": {}},
    }

    def page(args):
        return (
            {"entries": [entry]}
            if "beforeSeq" in args
            else {"entries": [], "nextBeforeSeq": 10}
        )

    transport = FakeTransport(commands={"getAgentTranscriptTail": page})
    assert cards.still_pending(transport, card("widget"))
    assert cards.tail(transport, "bot", "session") == [entry]
    transport.commands["getAgentTranscriptTail"] = lambda args: {
        "entries": [],
        "nextBeforeSeq": int(str(args.get("beforeSeq", 10))) - 1,
    }
    transport.calls.clear()
    assert not cards.still_pending(transport, card("widget"))
    assert len(transport.calls) == 5


WIDGET = {
    "id": "entry",
    "kind": "send-message",
    "message": {"type": "widget", "widget": {}},
}


def two_pages(args):
    # The newest page has no card and points at an older page that holds one.
    if "beforeSeq" in args:
        return {"entries": [WIDGET]}
    return {"entries": [], "nextBeforeSeq": 10}


def reads(transport):
    return [(args["id"], args.get("sessionId")) for _, _, args in transport.calls]


def test_tail_max_pages():
    transport = FakeTransport(commands={"getAgentTranscriptTail": two_pages})
    assert cards.tail(transport, "bot", "session", max_pages=1) == []
    assert len(transport.calls) == 1
    assert "beforeSeq" not in transport.calls[0][2]
    transport.calls.clear()
    assert cards.tail(transport, "bot", "session", max_pages=2) == [WIDGET]
    assert len(transport.calls) == 2
    transport.calls.clear()
    assert cards.tail(transport, "bot", "session") == [WIDGET]
    assert len(transport.calls) == 2


def test_tail_max_pages_still_checks_advance():
    transport = FakeTransport(
        commands={
            "getAgentTranscriptTail": lambda args: {
                "entries": [],
                "nextBeforeSeq": 10,
            }
        }
    )
    with pytest.raises(ValueError, match="did not advance"):
        cards.tail(transport, "bot", None, max_pages=3)
    assert len(transport.calls) == 2


@pytest.mark.parametrize(
    "row,expected",
    [
        ({}, False),
        ({"awaitingUserResponse": None}, False),
        ({"awaitingUserResponse": False}, False),
        ({"awaitingSessionIds": []}, False),
        ({"awaitingSessionIds": [1]}, False),
        ({"awaitingUserResponse": {}}, True),
        ({"awaitingUserResponse": {"reason": "approval"}}, True),
        ({"awaitingUserResponse": True}, True),
        ({"awaitingSessionIds": ["s1"]}, True),
    ],
)
def test_waiting(row, expected):
    assert cards.waiting(row) is expected


def test_discover_recent_pages():
    rows: list[dict[str, object]] = [
        {"id": "idle", "name": "Idle"},
        {"id": "falsy", "name": "Falsy", "awaitingUserResponse": False},
        {"id": "empty", "name": "Empty", "awaitingUserResponse": {}},
        {"id": "session", "name": "Session", "awaitingSessionIds": ["s1"]},
        {
            "id": "wait",
            "name": "Wait",
            "awaitingUserResponse": {"reason": "approval"},
            "awaitingSessionIds": ["s1"],
        },
    ]
    transport = FakeTransport(commands={"getAgentTranscriptTail": two_pages})
    found, warnings = cards.discover(transport, rows, all_bots=True, recent_pages=1)
    assert warnings == []
    # A bot the roster does not show as waiting is read once; a waiting bot, flagged even by an empty mapping
    # or by a listed waiting session alone, is read to the end in every session.
    assert reads(transport) == [
        ("idle", None),
        ("falsy", None),
        ("empty", None),
        ("empty", None),
        ("session", None),
        ("session", None),
        ("session", "s1"),
        ("session", "s1"),
        ("wait", None),
        ("wait", None),
        ("wait", "s1"),
        ("wait", "s1"),
    ]
    assert [item.bot_id for item in found] == ["empty", "session", "wait"]
    transport.calls.clear()
    found, _ = cards.discover(transport, rows, all_bots=True)
    assert len(transport.calls) == 2 * (1 + 1 + 1 + 2 + 2)
    assert {item.bot_id for item in found} == {
        "idle",
        "falsy",
        "empty",
        "session",
        "wait",
    }


def test_discover_recent_pages_card_on_second_page():
    rows: list[dict[str, object]] = [{"id": "bot", "name": "Bot"}]
    transport = FakeTransport(commands={"getAgentTranscriptTail": two_pages})
    assert cards.discover(transport, rows, all_bots=True, recent_pages=1) == ([], [])
    assert len(transport.calls) == 1
    found, _ = cards.discover(transport, rows, all_bots=True, recent_pages=None)
    assert found == [classify(WIDGET, "bot", "Bot")]
    found, _ = cards.discover(transport, rows, selected="bot")
    assert found == [classify(WIDGET, "bot", "Bot")]


def test_discover_recent_pages_keeps_auth_failure():
    transport = FakeTransport(
        commands={"getAgentTranscriptTail": ConnectError(401, "expired")}
    )
    with pytest.raises(ConnectError):
        cards.discover(
            transport, [{"id": "bot", "name": "Bot"}], all_bots=True, recent_pages=1
        )


def test_fake_validates():
    service = FakeService()
    item = card("widget")
    with pytest.raises(ValueError, match="Invalid widget value. Options: A"):
        service.answer(item, Action("respond", value="invalid"))


def test_discover_card():
    entry = {
        "id": "entry",
        "kind": "send-message",
        "message": {"type": "widget", "widget": {}},
    }
    transport = FakeTransport(commands={"getAgentTranscriptTail": {"entries": [entry]}})
    found, warnings = cards.discover(
        transport, [{"id": "bot", "name": "Bot", "awaitingUserResponse": True}]
    )
    assert found == [classify(entry, "bot", "Bot")]
    assert warnings == []


@pytest.mark.parametrize("session", [None, "session"])
@pytest.mark.parametrize(
    "action,resolution",
    [
        (Action("approve"), "allowed"),
        (Action("approve", always=True), "always_this_bot"),
        (Action("approve", always=True, all_bots=True), "always_all_team_bots"),
        (Action("deny"), "skipped"),
    ],
)
def test_connector_grant(session, action, resolution):
    from gbot.protocol import USED_COMMANDS

    item = card("connector-grant", session_id=session)
    expected = {
        "agentId": "bot",
        "entryId": "entry",
        "requestId": "request",
        "resolution": resolution,
    }
    if session:
        expected["sessionId"] = session
    assert cards.plan(item, action) == ("resolveConnectorGrant", expected)
    transport = FakeTransport(commands={"resolveConnectorGrant": None})
    result = cards.answer(transport, item, action)
    assert (result.rpc, result.effect) == ("resolveConnectorGrant", resolution)
    assert transport.calls == [("command", "resolveConnectorGrant", expected)]
    assert "resolveConnectorGrant" in USED_COMMANDS


@pytest.mark.parametrize(
    "reply", [{"refusal": {"failureCode": "blocked"}}, {"refusal": None}, False, 1, []]
)
def test_connector_refused(reply):
    with pytest.raises(ValueError, match="refused|not accepted"):
        cards.answer(
            FakeTransport(commands={"resolveConnectorGrant": reply}),
            card("connector-grant"),
            Action("approve"),
        )


@pytest.mark.parametrize("reply", [{}, {"accepted": False}])
def test_connector_mapping_reply(reply):
    assert (
        cards.answer(
            FakeTransport(commands={"resolveConnectorGrant": reply}),
            card("connector-grant"),
            Action("deny"),
        ).effect
        == "skipped"
    )


@pytest.mark.parametrize(
    "item,action,hint",
    [
        (card("connector-grant"), Action("approve", all_bots=True), "--all-bots"),
        (card("connector-grant"), Action("deny", never=True), "--never"),
        (
            card("widget"),
            Action("respond", value="A", always=True, all_bots=True),
            "--all-bots",
        ),
        (card("connector-grant", request_id=None), Action("approve"), "requestId"),
    ],
)
def test_connector_usage(item, action, hint):
    with pytest.raises(ValueError, match=hint):
        cards.plan(item, action)
