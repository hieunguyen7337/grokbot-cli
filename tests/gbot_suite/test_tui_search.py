import asyncio
from dataclasses import replace
from unittest.mock import Mock

import pytest
from fake_calls import actions
from textual.widgets import Static
from tui_snapshots import assert_snapshot

from gbot.service import events
from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.panels.kit import ListPanel
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, run
from gbot.tui.widgets.transcript import Transcript


@pytest.fixture(autouse=True)
def session_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr("gbot.tui.screens.home.time", lambda: 1_800_000_000)
    monkeypatch.setattr("gbot.tui.slash.search.time.time", lambda: 1_800_000_000)


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


def test_search_panel_snapshot_and_open():
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            assert run(SlashContext(app, app.home, None, None), "/search hello") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, ListPanel)
            assert panel.heading == "Search messages"
            assert len(panel.rows) == 1
            text = str(panel.query_one("#panel-rows", Static).render())
            assert "A helpful answer" in text
            assert app.state.bots["demo-helper"].name in text
            assert actions(service.transport) == [
                ("command", "searchAgents", {"query": "hello", "limit": 50})
            ]
            await assert_snapshot(app, pilot, "panel-search")
            await pilot.press("enter")
            await settle(app, pilot)
            assert isinstance(app.screen, SessionScreen)
            assert app.screen.bot_id == "demo-helper"

    asyncio.run(exercise())


def test_search_blank_and_failure(monkeypatch):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notice = Mock(wraps=app.notify)
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            ctx = SlashContext(app, app.home, None, None)
            assert run(ctx, "/search   ") is None
            await settle(app, pilot)
            assert app.screen is app.home
            assert actions(service.transport) == []
            notice.assert_any_call("Type something to search", markup=False)
            service.transport.commands["searchAgents"] = OSError("Search offline")
            assert run(ctx, "/search hello") is None
            await settle(app, pilot)
            assert isinstance(app.screen, ListPanel)
            assert app.screen.rows == []
            assert "Nothing here" in str(
                app.screen.query_one("#panel-rows", Static).render()
            )
            notice.assert_any_call("Search offline", severity="warning", markup=False)

    asyncio.run(exercise())


def test_media_demo():
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            assert run(SlashContext(app, app.home, None, None), "/media") is None
            await settle(app, pilot)
            assert isinstance(app.screen, ListPanel)
            text = str(app.screen.query_one("#panel-rows", Static).render())
            assert "report.pdf" in text and "pdf · Helper" in text
            assert actions(service.transport) == [
                ("command", "searchMedia", {"query": "", "limit": 50})
            ]

    asyncio.run(exercise())


@pytest.mark.parametrize("shown", [True, False])
def test_find_selection_and_incomplete(shown, monkeypatch):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notice = Mock(wraps=app.notify)
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            screen = SessionScreen("demo-helper")
            await app.push_screen(screen)
            await settle(app, pilot)
            history = screen.query_one(Transcript)
            target = next(iter(history.entries)) if shown else "not-loaded"
            scroll = Mock(wraps=history.scroll_to_widget)
            monkeypatch.setattr(history, "scroll_to_widget", scroll)
            service.transport.commands["searchConversation"] = {
                "matches": [
                    {
                        "entryId": target,
                        "role": "assistant",
                        "seq": 1,
                        "snippet": "Found hello",
                        "timestampMs": 0,
                    }
                ],
                "isComplete": False,
            }
            assert (
                run(SlashContext(app, screen, screen.bot_id, None), "/find hello")
                is None
            )
            await settle(app, pilot)
            assert isinstance(app.screen, ListPanel)
            assert "Found hello" in str(
                app.screen.query_one("#panel-rows", Static).render()
            )
            assert "More matches exist" in str(
                app.screen.query_one(".panel-footer", Static).render()
            )
            assert actions(service.transport) == [
                (
                    "command",
                    "searchConversation",
                    {"agentId": screen.bot_id, "query": "hello", "limit": 50},
                )
            ]
            await pilot.press("enter")
            await settle(app, pilot)
            assert app.screen is screen
            assert not any(isinstance(s, ListPanel) for s in app.screen_stack)
            if shown:
                assert target in history.entries
                scroll.assert_called_once_with(history.entries[target], animate=False)
            else:
                scroll.assert_not_called()
                notice.assert_any_call(
                    "Earlier in the chat · press pgup to load more", markup=False
                )

    asyncio.run(exercise())


def test_search_hostile_text_is_literal():
    async def exercise():
        service = load_fake()
        service.transport.commands["searchAgents"] = [
            {
                "agentId": "demo-helper",
                "entryId": "demo",
                "role": "assistant",
                "snippet": "[link=x]Snippet\x1b[31m",
                "timestampMs": 0,
            }
        ]
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            app._receive_event(
                events.BotChanged(
                    replace(app.state.bots["demo-helper"], name="[link=x]Bot\x1b[31m")
                )
            )
            await settle(app, pilot)
            assert run(SlashContext(app, app.home, None, None), "/search hello") is None
            await settle(app, pilot)
            text = str(app.screen.query_one("#panel-rows", Static).render())
            assert "[link=x]Bot" in text and "[link=x]Snippet" in text
            assert "\x1b" not in text

    asyncio.run(exercise())
