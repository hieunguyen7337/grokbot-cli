import pytest

from gbot.protocol import USED_COMMANDS
from gbot.service import runs
from gbot.service.fake import load_fake
from gbot.service.transport import FakeTransport


@pytest.mark.parametrize(
    "reply, expected",
    [({"hadActiveRun": True}, True), ({"hadActiveRun": False}, False), (None, False)],
)
def test_interrupt(reply, expected):
    transport = FakeTransport({"interruptAgentRun": reply})
    assert runs.interrupt(transport, "bot") is expected
    assert transport.calls == [("command", "interruptAgentRun", {"id": "bot"})]


@pytest.mark.parametrize("reply", [[], {}, {"hadActiveRun": 1}, "bad"])
def test_interrupt_rejects_malformed(reply):
    with pytest.raises(ValueError, match="Unexpected reply to interruptAgentRun"):
        runs.interrupt(FakeTransport({"interruptAgentRun": reply}), "bot", "s")


def test_commands_and_demo_merge():
    transport = FakeTransport({"interruptAgentRun": {"hadActiveRun": False}})
    service = load_fake({"transport": transport})
    # Every area merges its demo replies; a reply the caller gives wins.
    expected = {**runs.DEMO_COMMANDS, "interruptAgentRun": {"hadActiveRun": False}}
    assert {name: transport.commands[name] for name in expected} == expected
    assert set(runs.COMMANDS) <= set(USED_COMMANDS)
    assert not runs.interrupt(service.transport, "bot", "s")
    runs.start_fresh(service.transport, "bot", "s")
    runs.roll_back(service.transport, "bot")
    assert transport.calls == [
        ("command", "interruptAgentRun", {"id": "bot", "sessionId": "s"}),
        ("command", "startFreshConversation", {"id": "bot", "sessionId": "s"}),
        ("command", "rollBackConversation", {"id": "bot"}),
    ]
