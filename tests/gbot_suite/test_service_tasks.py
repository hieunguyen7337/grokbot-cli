import pytest

from gbot.protocol import USED_COMMANDS
from gbot.service import tasks as s
from gbot.service.fake import load_fake
from gbot.service.transport import FakeTransport


def test_arguments_and_registration():
    t = FakeTransport(dict.fromkeys(s.COMMANDS))
    s.tasks(t, "b")
    s.mark_done(t, "b", "t")
    s.mark_read(t, "b", "t", "e")
    s.set_pinned(t, "b", "t", True)
    s.background(t, "b")
    s.subagents(t, "b")
    s.outline(t, "b")
    s.dismiss_suggestions(t, "b", ["s"], "hidden")
    s.set_unread(t, "b", True)
    s.set_unread(t, "b", False)
    assert [c[2] for c in t.calls] == [
        {"agentId": "b"},
        {"agentId": "b", "taskId": "t"},
        {"agentId": "b", "taskId": "t", "entryId": "e"},
        {"agentId": "b", "taskId": "t", "isPinned": True},
        {"id": "b"},
        {"id": "b"},
        {"id": "b"},
        {"agentId": "b", "suggestionIds": ["s"], "reason": "hidden"},
        {"id": "b", "isUnread": True},
        {"id": "b", "isUnread": False, "markFollowedThreadsRead": True},
    ]
    assert set(s.COMMANDS) <= set(USED_COMMANDS)
    assert s.thread_session("t", None) == "task:t"
    assert s.thread_session("t", "s1") == "task:t:s1"
    assert len(s.tasks(load_fake().transport, "b")) == 2


@pytest.mark.parametrize(
    "command,fn",
    [
        ("getAgentTasks", s.tasks),
        ("getAsyncTasks", s.background),
        ("getSubagents", s.subagents),
        ("getConversationOutline", s.outline),
    ],
)
def test_parsing(command, fn):
    t = FakeTransport({command: None})
    assert fn(t, "b") == []
    t.commands[command] = {}
    with pytest.raises(ValueError, match=f"Unexpected reply to {command}"):
        fn(t, "b")
    t.commands[command] = [None, "bad", {}, {"id": "x", "subagentId": "x", "extra": 3}]
    (row,) = fn(t, "b")
    assert row.id == "x" and row.raw["extra"] == 3


def test_full_rows():
    row = {
        "id": "t",
        "name": "Task",
        "description": "Detail",
        "status": "open",
        "updatedAtMs": 5,
        "pinnedAtMs": 0,
        "unreadEntryId": "e",
        "unreadPreview": "New",
        "unreadAtMs": 4,
        "followed": True,
        "subagentIds": ["a"],
    }
    (item,) = s.tasks(FakeTransport({"getAgentTasks": [row]}), "b")
    assert (
        item.name,
        item.updated_at_ms,
        item.pinned_at_ms,
        item.followed,
        item.subagent_ids,
    ) == ("Task", 5, 0, True, ("a",))
    (outline,) = s.outline(
        FakeTransport(
            {
                "getConversationOutline": [
                    {"id": "m", "kind": "send-message", "message": {"text": "Sent"}}
                ]
            }
        ),
        "b",
    )
    assert outline.text == "Sent"
