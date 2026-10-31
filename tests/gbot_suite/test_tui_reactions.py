import asyncio
from dataclasses import replace
from unittest.mock import Mock

import pytest
from fake_calls import actions
from textual.widgets import Input, Select, Static, Switch, TextArea
from tui_snapshots import assert_snapshot

from gbot.service import events
from gbot.service.fake import load_fake
from gbot.service.reactions import FEEDBACK_CATEGORIES
from gbot.tui.app import GbotApp
from gbot.tui.panels.kit import FormPanel, ListPanel
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, run
from gbot.tui.slash.reactions import EMOJI
from gbot.tui.widgets.transcript import Transcript

UP = "\N{THUMBS UP SIGN}"
HEART = "\N{HEAVY BLACK HEART}\N{VARIATION SELECTOR-16}"


@pytest.fixture(autouse=True)
def session_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr("gbot.tui.screens.home.time", lambda: 1_800_000_000)


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def open_session(app, pilot, session_id: str | None = "s1"):
    await settle(app, pilot)
    screen = SessionScreen("demo-ledger", session_id=session_id)
    await app.push_screen(screen)
    await settle(app, pilot)
    return screen, SlashContext(app, screen, screen.bot_id, session_id)


def newest(screen):
    return next(
        widget.entry
        for widget in reversed(screen.query_one(Transcript).entries.values())
        if widget.entry.role != "user"
        and widget.entry.kind in {"message", "send-message"}
    )


def test_react_newest_and_remove(monkeypatch):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notice = Mock(wraps=app.notify)
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            screen, ctx = await open_session(app, pilot)
            entry = newest(screen)
            # A later user message must not become the reaction target.
            app._receive_event(
                events.EntryAdded(
                    replace(
                        entry, id="later-user", seq=999, role="user", session_id="s1"
                    )
                )
            )
            await settle(app, pilot)
            assert run(ctx, f"/react {UP}") is None
            await settle(app, pilot)
            expected = (
                "command",
                "reactToMessage",
                {
                    "agentId": "demo-ledger",
                    "entryId": entry.id,
                    "emoji": UP,
                    "sessionId": "s1",
                },
            )
            assert actions(service.transport) == [expected]
            notice.assert_any_call("Reacted", markup=False)
            app._receive_event(
                events.EntryChanged(
                    replace(
                        entry,
                        session_id="s1",
                        raw={**entry.raw, "reactions": [{"by": "user", "emoji": UP}]},
                    )
                )
            )
            await settle(app, pilot)
            assert run(ctx, f"/react {UP}") is None
            await settle(app, pilot)
            assert actions(service.transport) == [expected, expected]
            notice.assert_any_call("Removed reaction", markup=False)

    asyncio.run(exercise())


def test_reaction_picker_and_other():
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            screen, ctx = await open_session(app, pilot)
            for emoji in (EMOJI[0], "\N{ROCKET}"):
                assert run(ctx, "/react") is None
                await settle(app, pilot)
                panel = app.screen
                assert isinstance(panel, ListPanel)
                assert panel.heading == "Choose a message"
                assert [row.key for row in panel.rows] == list(
                    reversed(list(screen.query_one(Transcript).entries)[-30:])
                )
                target = panel.rows[0].key
                await pilot.press("enter")
                await settle(app, pilot)
                assert isinstance(app.screen, ListPanel)
                assert app.screen.heading == "Choose a reaction"
                if emoji != EMOJI[0]:
                    await pilot.press(*(["down"] * len(EMOJI)), "enter")
                    await settle(app, pilot)
                    assert isinstance(app.screen, FormPanel)
                    assert len(app.screen.fields) == 1
                    app.screen.query_one(Input).value = emoji
                    await pilot.press("ctrl+s")
                else:
                    await pilot.press("enter")
                await settle(app, pilot)
                assert app.screen is screen
                assert actions(service.transport)[-1] == (
                    "command",
                    "reactToMessage",
                    {
                        "agentId": "demo-ledger",
                        "entryId": target,
                        "emoji": emoji,
                        "sessionId": "s1",
                    },
                )

    asyncio.run(exercise())


def test_feedback_down_and_form(monkeypatch):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notice = Mock(wraps=app.notify)
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            screen, ctx = await open_session(app, pilot)
            base = {
                "agentId": "demo-ledger",
                "entryId": newest(screen).id,
                "sessionId": "s1",
            }
            assert run(ctx, "/feedback down") is None
            await settle(app, pilot)
            assert actions(service.transport) == [
                ("command", "voteFeedback", {**base, "action": "down"})
            ]
            service.transport.calls.clear()
            assert run(ctx, "/feedback") is None
            await settle(app, pilot)
            form = app.screen
            assert isinstance(form, FormPanel)
            form.query_one(Select).focus()
            await pilot.press("enter", "down", "enter")
            assert form.query_one(Select).value == "Not helpful"
            # Toggle in reverse order; the wire categories still follow the contract order.
            for index in (3, 1):
                form.query_one(f"#form-{index}", Switch).focus()
                await pilot.press("space")
            form.query_one(TextArea).focus()
            await pilot.press(*"Please clarify")
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert app.screen is screen
            assert actions(service.transport) == [
                ("command", "voteFeedback", {**base, "action": "down"}),
                (
                    "command",
                    "voteFeedback",
                    {
                        **base,
                        "action": "submit",
                        "categories": [FEEDBACK_CATEGORIES[0], FEEDBACK_CATEGORIES[2]],
                        "comment": "Please clarify",
                    },
                ),
            ]
            notice.assert_any_call("Feedback sent", markup=False)

    asyncio.run(exercise())


def test_feedback_failure_keeps_comment():
    async def exercise():
        service = load_fake()
        service.transport.commands["voteFeedback"] = OSError("Feedback offline")
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            _, ctx = await open_session(app, pilot)
            assert run(ctx, "/feedback") is None
            await settle(app, pilot)
            form = app.screen
            assert isinstance(form, FormPanel)
            form.query_one(TextArea).focus()
            await pilot.press(*"Keep this comment", "ctrl+s")
            await settle(app, pilot)
            assert app.screen is form
            assert "Feedback offline" in str(
                form.query_one("#form-notice", Static).render()
            )
            assert form.query_one(TextArea).text == "Keep this comment"
            assert [name for _, name, _ in actions(service.transport)] == [
                "voteFeedback"
            ]

    asyncio.run(exercise())


def test_thread_cancel_and_confirm(monkeypatch):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notice = Mock(wraps=app.notify)
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            _, ctx = await open_session(app, pilot)
            for confirm in (False, True):
                assert run(ctx, "/thread") is None
                await settle(app, pilot)
                assert isinstance(app.screen, ListPanel)
                target = app.screen.rows[0].key
                await pilot.press("enter")
                await settle(app, pilot)
                assert isinstance(app.screen, ConfirmScreen)
                if confirm:
                    await pilot.click("#confirm")
                else:
                    await pilot.press("escape")
                await settle(app, pilot)
                assert actions(service.transport) == (
                    [
                        (
                            "command",
                            "createThreadFromMessage",
                            {"agentId": "demo-ledger", "entryId": target},
                        )
                    ]
                    if confirm
                    else []
                )
            notice.assert_any_call("Thread started · /threads lists it", markup=False)

    asyncio.run(exercise())


def test_read_only_reactions_and_search(monkeypatch):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False, read_only=True)
        notice = Mock(wraps=app.notify)
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            screen, ctx = await open_session(app, pilot)
            notice.reset_mock()
            for command in (f"/react {UP}", "/feedback up", "/thread"):
                assert run(ctx, command) is None
                await settle(app, pilot)
                assert app.screen is screen
            assert actions(service.transport) == []
            assert notice.call_count == 3
            notice.assert_called_with("Read-only mode", markup=False)
            assert run(ctx, "/search hello") is None
            await settle(app, pilot)
            assert isinstance(app.screen, ListPanel)
            assert app.screen.rows
            assert [name for _, name, _ in actions(service.transport)] == [
                "searchAgents"
            ]

    asyncio.run(exercise())


def test_entry_changed_reactions_snapshot():
    async def exercise():
        app = GbotApp(load_fake(), animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            screen, _ = await open_session(app, pilot, session_id=None)
            entry = newest(screen)
            app._receive_event(
                events.EntryChanged(
                    replace(
                        entry,
                        raw={
                            **entry.raw,
                            "reactions": [
                                {"by": "user", "emoji": UP},
                                {"by": "bot", "emoji": UP},
                                {"by": "other", "emoji": HEART},
                            ],
                        },
                    )
                )
            )
            await settle(app, pilot)
            widget = screen.query_one(Transcript).entries[entry.id]
            assert widget.has_class("reacted-entry")
            line = widget.children[-1]
            assert isinstance(line, Static)
            rendered = line.render()
            assert f"{UP} 2" in str(rendered) and f"{HEART} 1" in str(rendered)
            assert any(span.style == "dim" for span in getattr(rendered, "spans", ()))
            assert line.region.y >= widget.children[0].region.bottom
            await assert_snapshot(app, pilot, "session-reactions")

    asyncio.run(exercise())
