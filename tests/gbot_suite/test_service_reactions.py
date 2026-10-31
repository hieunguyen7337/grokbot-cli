from gbot.protocol import USED_COMMANDS
from gbot.service import reactions
from gbot.service.models import Entry
from gbot.service.transport import FakeTransport


def test_reactions_commands_and_grouping():
    transport = FakeTransport(reactions.DEMO_COMMANDS)
    reactions.react(transport, "bot", "entry", "x", "session")
    reactions.vote(transport, "bot", "entry", "down")
    reactions.vote(
        transport,
        "bot",
        "entry",
        "submit",
        session_id="s",
        categories=["inaccurate"],
        comment="bad",
    )
    reactions.thread_from(transport, "bot", "entry")
    assert transport.calls == [
        (
            "command",
            "reactToMessage",
            {
                "agentId": "bot",
                "entryId": "entry",
                "emoji": "x",
                "sessionId": "session",
            },
        ),
        (
            "command",
            "voteFeedback",
            {"agentId": "bot", "entryId": "entry", "action": "down"},
        ),
        (
            "command",
            "voteFeedback",
            {
                "agentId": "bot",
                "entryId": "entry",
                "action": "submit",
                "sessionId": "s",
                "categories": ["inaccurate"],
                "comment": "bad",
            },
        ),
        ("command", "createThreadFromMessage", {"agentId": "bot", "entryId": "entry"}),
    ]
    entry = Entry(
        "bot",
        "entry",
        1,
        "message",
        raw={
            "reactions": [
                {"by": "user", "emoji": "x"},
                {"by": "bot", "emoji": "x"},
                {"by": "bot", "emoji": "y"},
                {},
                None,
            ]
        },
    )
    assert reactions.entry_reactions(entry) == [("x", 2, True), ("y", 1, False)]
    assert set(reactions.COMMANDS) <= USED_COMMANDS.keys()
