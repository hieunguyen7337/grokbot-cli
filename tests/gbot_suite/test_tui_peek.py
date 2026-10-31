import asyncio
from dataclasses import replace
from threading import Event

import pytest
from textual.widgets import Static
from tui_snapshots import assert_snapshot

from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.widgets.prompt import CardPrompt


@pytest.fixture
def home_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr("gbot.tui.screens.home.time", lambda: 1_800_000_000)
    return tmp_path


def test_toggle_follow_and_read_only(home_env, monkeypatch):
    async def exercise():
        service = load_fake()

        def forbidden(*args, **kwargs):
            pytest.fail("Peek must not mark a chat read")

        monkeypatch.setattr(service, "open", forbidden)
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            home = app.home
            await pilot.press("space")
            await app.workers.wait_for_complete()
            assert home.peek.display and home.peek.bot_id == "demo-inbox"
            assert home.bot_list.has_focus
            assert home.peek.size.height <= 15
            await pilot.press("down")
            await app.workers.wait_for_complete()
            assert home.peek.bot_id == "demo-travel"
            await pilot.press("space")
            assert not home.peek.display
            await pilot.press("space", "escape")
            assert not home.peek.display
            await pilot.press("space", "home")
            assert not home.peek.display

    asyncio.run(exercise())


def test_answers_and_cancel(home_env):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("space", "1")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.click("#cancel")
            assert not service.answered
            await pilot.press("down", "down", "2")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert service.answered[-1][0] == "demo-planner"
            assert service.answered[-1][2].value == "City Loft"
            assert not isinstance(app.screen, ConfirmScreen)
            assert not app.home.peek.query(CardPrompt)

    asyncio.run(exercise())


@pytest.mark.parametrize("session_id", [None, "s1"])
def test_reply_and_escape(home_env, monkeypatch, session_id):
    async def exercise():
        service = load_fake()
        nonces = []
        send = service.send

        def capture(*args, **kwargs):
            nonces.append(kwargs["nonce"])
            return send(*args, **kwargs)

        monkeypatch.setattr(service, "send", capture)
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            card = app.state.cards["demo-inbox"][0]
            app.state.cards["demo-inbox"] = [replace(card, session_id=session_id)]
            await pilot.press("space", "tab")
            field = app.home.peek.reply
            assert field.has_focus
            field.value = "hello"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            assert service.sent == [("demo-inbox", "hello", session_id)]
            assert field.value == ""
            assert len(nonces) == 1 and nonces[0]
            field.value = "unsent"
            await pilot.press("escape")
            assert field.value == "" and app.home.bot_list.has_focus
            assert app.home.peek.display

    asyncio.run(exercise())


def test_live_entries_and_literal_text(home_env):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("space")
            service.reply("demo-inbox", "[link=x]\x1b[31m literal")
            await pilot.pause(0.6)
            await app.workers.wait_for_complete()
            from gbot.tui.widgets.transcript import BotEntry

            assert any(
                "[link=x]" in entry.text for entry in app.home.peek.query(BotEntry)
            )
            svg = app.export_screenshot()
            assert "[link=x]" in svg and "\x1b" not in svg
            assert 'href="x"' not in svg

    asyncio.run(exercise())


def test_stale_transcript_is_ignored(home_env, monkeypatch):
    async def exercise():
        service = load_fake()
        transcript = service.transcript
        entered, release = Event(), Event()

        def slow(bot_id, **kwargs):
            if bot_id == "demo-inbox":
                entered.set()
                release.wait(5)
            return transcript(bot_id, **kwargs)

        monkeypatch.setattr(service, "transcript", slow)
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("space")
            assert await asyncio.to_thread(entered.wait, 2)
            await pilot.press("down")
            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.home.peek.bot_id == "demo-travel"
            title = app.home.peek.query_one("#peek-title", Static)
            assert "Travel" in str(title.render())
            assert "invoice" not in app.export_screenshot()

    asyncio.run(exercise())


def test_peek_snapshot(home_env):
    async def exercise():
        app = GbotApp(load_fake(), animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("space")
            await app.workers.wait_for_complete()
            await assert_snapshot(app, pilot, "peek-inbox")

    asyncio.run(exercise())
