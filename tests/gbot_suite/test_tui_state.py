from dataclasses import replace

import pytest

from gbot.service import events
from gbot.service.fake import load_fake
from gbot.service.models import Awaiting, Bot, ConnectionStatus, Entry
from gbot.tui.state import AppState


def test_roster_overlay_and_connection():
    state = AppState()
    bots = load_fake().roster()
    assert state.apply(events.RosterReplaced(tuple(bots))) == {"roster"}
    assert list(state.bots) == [b.id for b in bots]
    changed = replace(bots[0], name="Changed")
    assert state.apply(events.BotChanged(changed)) == {"roster"}
    assert state.bots[changed.id] == changed
    assert state.apply(events.BotChanged(Bot("new", "New"))) == {"roster"}
    assert list(state.bots)[-1] == "new"
    assert state.apply(events.BotOverlay(bots[2].id, {"isRunning": False})) == {
        "roster"
    }
    assert not state.bots[bots[2].id].busy
    assert state.apply(events.BotOverlay("unknown", {})) == set()
    for status in ConnectionStatus:
        assert state.apply(events.ConnectionChanged(status)) == {"status"}
        assert state.status == status
    state.cards = {"new": [], bots[0].id: []}
    state.apply(events.RosterReplaced((bots[0],)))
    assert state.cards == {bots[0].id: []}


@pytest.mark.parametrize("event_type", [events.EntryAdded, events.EntryChanged])
def test_card_refresh_requests(event_type):
    state = AppState(
        bots={"a": Bot("a", "A"), "b": Bot("b", "B", awaiting=Awaiting("ask"))}
    )
    entry = Entry("a", "e", 1, "send-message")
    assert state.apply(event_type(entry)) == set()
    assert state.apply(event_type(replace(entry, card_type="widget"))) == {"cards:a"}
    assert state.apply(event_type(replace(entry, bot_id="b"))) == {"cards:b"}
    assert state.apply(events.RosterResync("a")) == {"cards:a"}
    assert state.apply(events.RosterResync()) == {"cards:a", "cards:b"}


@pytest.mark.parametrize(
    "event",
    [
        events.EntryRemoved("a", None, "e"),
        events.TranscriptReset("a", None),
        events.BoxChanged("a", "running"),
        events.Resynced(),
        events.Other("unknown", {}),
    ],
)
def test_ignored_events(event):
    state = AppState(bots={"a": Bot("a", "A")})
    before = dict(state.bots)
    assert state.apply(event) == set()
    assert state.bots == before


def test_full_connection_and_error_pruning():
    state = AppState(errors={"a": "failed", "removed": "failed"})
    event = events.ConnectionChanged(ConnectionStatus.RECONNECTING, 3, "retry detail")
    state.apply(event)
    assert state.connection == event
    assert state.status == event.status
    state.apply(events.RosterReplaced((Bot("a", "A"),)))
    assert state.errors == {"a": "failed"}
