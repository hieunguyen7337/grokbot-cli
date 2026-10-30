import asyncio
from types import SimpleNamespace

import pytest
from textual.widgets import Input
from tui_snapshots import assert_snapshot

from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.panels import ListPanel
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashCommand, SlashContext, commands, parse, run
from gbot.tui.widgets.slashmenu import SlashMenu


def test_registry():
    assert [c.name for c in commands()] == ["help", "keys"]
    assert parse("/rooms  add x") == ("rooms", "add x")


def test_dispatch_errors_and_prefix(monkeypatch):
    calls = []
    entries = (
        SlashCommand("hello", "hello", lambda ctx, args: calls.append(args)),
        SlashCommand("helpful", "helpful", lambda ctx, args: None),
        SlashCommand("session", "session", lambda ctx, args: None, scope="session"),
        SlashCommand("bot", "bot", lambda ctx, args: None, needs_bot=True),
    )
    monkeypatch.setattr("gbot.tui.slash.commands", lambda: entries)
    app = GbotApp(load_fake(), animate=False)
    ctx = SlashContext(app, app.home, None, None)
    assert run(ctx, "/hell arg") is None and calls == ["arg"]
    assert run(ctx, "/hel") == "Unknown command /hel · /help lists commands"
    assert run(ctx, "/session") == "/session works in a session"
    assert run(ctx, "/bot") == "Select a bot first"


@pytest.mark.parametrize("names", [("bad_name",), ("same", "same")])
def test_discovery_rejects_invalid_and_duplicate(monkeypatch, names):
    from gbot.tui import slash

    modules = [SimpleNamespace(name=f"fake{i}") for i in range(len(names))]
    monkeypatch.setattr(slash.pkgutil, "iter_modules", lambda path: modules)
    monkeypatch.setattr(
        slash.importlib,
        "import_module",
        lambda name: SimpleNamespace(
            COMMANDS=(
                SlashCommand(names[int(name[-1])], "test", lambda ctx, args: None),
            )
        ),
    )
    slash.commands.cache_clear()
    try:
        with pytest.raises(ValueError):
            slash.commands()
    finally:
        slash.commands.cache_clear()


def test_home_menu(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        app = GbotApp(load_fake(), animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            field = app.home.query_one("#dispatch", Input)
            field.focus()
            field.value = "/"
            await pilot.pause()
            menu = app.home.query_one(SlashMenu)
            assert [c.name for c in menu.matches] == ["help", "keys"]
            await assert_snapshot(app, pilot, "slash-menu")
            await pilot.press("down", "up", "enter")
            await pilot.pause()
            assert isinstance(app.screen, ListPanel)
            await app.workers.wait_for_complete()
            await assert_snapshot(app, pilot, "panel-help")
            await pilot.press("escape")
            assert field.has_focus

    asyncio.run(exercise())


def test_session_menu_and_escaped_message(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app.push_screen(SessionScreen("demo-inbox", session_id="test"))
            await pilot.pause()
            field = app.screen.query_one("#session-input", Input)
            field.value = "/he"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ListPanel)
            await pilot.press("escape")
            assert field.has_focus
            field.value = "//hi"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            assert service.sent[-1] == ("demo-inbox", "/hi", "test")

    asyncio.run(exercise())
