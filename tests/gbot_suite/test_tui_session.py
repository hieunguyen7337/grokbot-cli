import asyncio
import threading
from typing import cast

import pytest
from textual.widgets import Input, Markdown, Static
from tui_snapshots import assert_snapshot

from gbot.output import terminal_safe
from gbot.service.api import Service
from gbot.service.demo import DemoState
from gbot.service.fake import FakeService, load_fake
from gbot.service.models import Entry
from gbot.tui.app import GbotApp
from gbot.tui.glyphs import ASCII, UNICODE
from gbot.tui.screens.home import HomeScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.widgets.prompt import CardPrompt
from gbot.tui.widgets.transcript import (
    BotEntry,
    CardEntry,
    NoticeEntry,
    ToolEntry,
    Transcript,
    UnsupportedEntry,
    UserEntry,
    entry_widget,
)


@pytest.mark.parametrize(
    "kind,fields,expected",
    [
        ("message", {"role": "user"}, UserEntry),
        ("message", {"role": "assistant"}, BotEntry),
        ("send-message", {}, BotEntry),
        ("send-message", {"card_type": "widget"}, CardEntry),
        ("tool-call", {}, ToolEntry),
        ("notice", {}, NoticeEntry),
        *[
            (kind, {}, UnsupportedEntry)
            for kind in (
                "user-attachment",
                "feedback",
                "event",
                "mcp-app",
                "voice-call",
                "future-kind",
            )
        ],
    ],
)
def test_entry_widget(kind, fields, expected):
    entry = Entry("bot", "id", 1, kind, text="[bold]literal[/bold]", **fields)
    for symbols in (UNICODE, ASCII):
        widget = entry_widget(entry, symbols)
        assert isinstance(widget, expected)
        if kind in {"mcp-app", "voice-call"}:
            assert "open the Grok Bot app" in str(cast(Static, widget).content)


def test_tool_states_and_streaming():
    failed = entry_widget(
        Entry("b", "1", 1, "tool-call", raw={"status": "failed"}), UNICODE
    )
    assert failed.has_class("failed")
    pending = entry_widget(
        Entry("b", "2", 2, "tool-call", raw={"status": "pending"}), ASCII
    )
    assert ASCII.working[0] in str(cast(Static, pending).content)
    streaming = entry_widget(
        Entry("b", "3", 3, "send-message", streaming=True), UNICODE
    )
    assert isinstance(streaming, BotEntry) and streaming.streaming


def test_inbox_and_input():
    async def exercise():
        service = load_fake()
        app = GbotApp(cast(Service, service), bot="Inbox", animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            screen = cast(SessionScreen, app.screen)
            history = screen.query_one(Transcript)
            assert [type(w) for w in history.children[1:]] == [
                UserEntry,
                ToolEntry,
                BotEntry,
                CardEntry,
            ]
            svg = app.export_screenshot()
            for phrase in (
                "Check",
                "Searched",
                "Two",
                "email-draft:",
                "invoice",
                "needs",
                "asleep",
            ):
                assert phrase in svg
            # The inline prompt can push the top marker out of view; check the widget.
            assert "Beginning" in str(history.marker.render())
            assert "Check" in str(history.children[1].render())
            assert "Searched 24 unread threads" in str(history.children[2].render())
            assert screen.query_one(Markdown).source.startswith("Two threads")
            # The pending email draft takes focus; Tab switches to the composer and back.
            composer = screen.query_one(Input)
            assert isinstance(app.focused, CardPrompt)
            await pilot.press("tab")
            assert composer.has_focus
            await pilot.press("tab")
            assert isinstance(app.focused, CardPrompt)
            await pilot.press("tab", "h", "i")
            assert composer.value == "hi"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert service.sent == [("demo-inbox", "hi", None)]
            assert service.answered == []
            assert screen.query_one(Input).value == ""
            assert str(screen.query_one("#session-notice", Static).render()) == ""
            await pilot.press("x", "left")
            assert app.screen is screen
            await pilot.press("escape")
            assert isinstance(app.screen, HomeScreen)
            app.open_bot(app.bots[0])
            await pilot.pause()
            await pilot.press("left")
            assert isinstance(app.screen, HomeScreen)

    asyncio.run(exercise())


def test_paging():
    async def exercise():
        ui_thread = threading.get_ident()

        class PagedFake(FakeService):
            def __init__(self):
                super().__init__(
                    DemoState(
                        [{"id": "b", "name": "History"}],
                        {
                            "b": [
                                {
                                    "id": str(n),
                                    "seq": n,
                                    "kind": "message",
                                    "role": "user",
                                    "content": f"Entry {n}",
                                }
                                for n in range(1, 131)
                            ]
                        },
                    )
                )
                self.opens = []
                self.pages = []
                self.release = threading.Event()
                self.started = threading.Event()

            def open(self, bot_id, *, session_id=None, limit=200):
                assert threading.get_ident() != ui_thread
                self.opens.append((bot_id, session_id, limit))
                # A server may return a smaller tail than the requested limit.
                return super().open(bot_id, session_id=session_id, limit=min(limit, 30))

            def transcript(self, bot_id, *, before_seq=None, limit=50, session_id=None):
                assert threading.get_ident() != ui_thread
                self.pages.append((before_seq, limit, session_id))
                self.started.set()
                assert self.release.wait(5)
                return super().transcript(
                    bot_id, before_seq=before_seq, limit=limit, session_id=session_id
                )

            def box_state(self, bot_id):
                assert threading.get_ident() != ui_thread
                return "running"

        service = PagedFake()
        app = GbotApp(cast(Service, service), animate=False)
        async with app.run_test(size=(80, 24)) as pilot:
            await app.push_screen(SessionScreen("b", session_id="chosen"))
            await app.workers.wait_for_complete()
            await pilot.pause()
            screen = cast(SessionScreen, app.screen)
            history = screen.query_one(Transcript)
            assert service.opens == [("b", "chosen", 200)]
            assert len(history.children) == 31
            assert history.scroll_y > 0
            # Scrolling to zero triggers paging even without a keyboard binding.
            history.scroll_home(animate=False, immediate=True)
            await pilot.pause()
            assert service.started.is_set()
            anchor = history.children[1]
            old_y = anchor.region.y
            await pilot.press("pageup", "home", "pageup")
            assert service.pages == [(101, 50, "chosen")]
            service.release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(history.children) == 81
            assert anchor.region.y == old_y
            assert history.scroll_y > 0
            await pilot.press("home")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(history.children) == 131
            assert screen.next_before_seq is None
            await pilot.press("home", "pageup", "home")
            assert len(service.pages) == 2
            assert "Beginning" in str(history.marker.render())
            for n, widget in enumerate(history.children[1:], 1):
                assert str(cast(Static, widget).content) == f"> Entry {n}"

    asyncio.run(exercise())


def test_full_130_entry_tail():
    async def exercise():
        service = FakeService(
            DemoState(
                [{"id": "b", "name": "History"}],
                {
                    "b": [
                        {"id": str(n), "seq": n, "kind": "notice", "text": str(n)}
                        for n in range(130)
                    ]
                },
            )
        )
        app = GbotApp(cast(Service, service), bot="b", animate=False)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(app.screen.query_one(Transcript).children) == 131
            assert cast(SessionScreen, app.screen).next_before_seq is None

    asyncio.run(exercise())


def test_hostile_content(monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda *args, **kwargs: opened.append(args))

    async def exercise():
        hostile = "[link=x]literal[/link] \x1b[31m danger"
        service = load_fake()
        service.state.transcripts["demo-inbox"] = [
            {
                "id": "u",
                "seq": 1,
                "kind": "message",
                "role": "user",
                "content": hostile,
            },
            {
                "id": "b",
                "seq": 2,
                "kind": "message",
                "role": "assistant",
                "content": hostile + " [click](javascript:alert%281%29)",
            },
        ]
        app = GbotApp(cast(Service, service), bot="Inbox", animate=False)
        async with app.run_test(size=(120, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            md = app.screen.query_one(Markdown)
            assert not md._open_links
            assert terminal_safe(hostile) in md.source
            svg = app.export_screenshot()
            assert "[link=x]literal[/link]" in svg
            assert "\\u001b[31m" in svg
            md.post_message(Markdown.LinkClicked(md, "javascript:alert(1)"))
            await pilot.pause()
            assert opened == []

    asyncio.run(exercise())


def test_load_error_retry():
    async def exercise():
        service = load_fake()
        original = service.open
        calls = []

        def flaky(bot_id, *, session_id=None, limit=200):
            calls.append(limit)
            if len(calls) == 1:
                raise ValueError("[bold]offline")
            return original(bot_id, session_id=session_id, limit=limit)

        service.open = flaky
        app = GbotApp(cast(Service, service), bot="Inbox", animate=False)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            screen = cast(SessionScreen, app.screen)
            assert "[bold]offline — press r to retry" in str(
                screen.query_one(Transcript).marker.render()
            )
            await pilot.press("o", "r")
            assert screen.query_one(Input).value == "or"
            assert calls == [200]
            screen.query_one(Input).value = ""
            await pilot.press("r")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert screen.loaded and not screen.failed
            assert calls == [200, 200]
            assert screen.query_one(Input).value == ""

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "bot,size,name",
    [
        ("Inbox", (100, 30), "session-inbox"),
        ("Planner", (80, 24), "session-planner"),
    ],
)
def test_session_snapshot(bot, size, name):
    async def exercise():
        app = GbotApp(cast(Service, load_fake()), bot=bot, animate=False)
        async with app.run_test(size=size) as pilot:
            await app.workers.wait_for_complete()
            await assert_snapshot(app, pilot, name)

    asyncio.run(exercise())
