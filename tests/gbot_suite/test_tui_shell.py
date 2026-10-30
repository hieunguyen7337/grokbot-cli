import asyncio
import sys
from typing import cast

import pytest
from textual.widgets import Input
from tui_snapshots import assert_snapshot

from gbot.cli import main
from gbot.service.api import Service
from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.glyphs import UNICODE
from gbot.tui.screens.help import HelpScreen
from gbot.tui.screens.home import HomeScreen
from gbot.tui.screens.session import SessionScreen


@pytest.mark.parametrize("ascii_only", [False, True])
def test_screenshot(tmp_path, monkeypatch, ascii_only):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    path = tmp_path / "home.svg"
    args = ["tui", "--demo", "--screenshot", str(path)]
    if ascii_only:
        args.append("--ascii")
    assert main(args) == 0
    svg = path.read_text(encoding="utf-8")
    assert "<svg" in svg and "Inbox" in svg
    if ascii_only:
        assert all(frame not in svg for frame in UNICODE.working)


def test_missing_textual(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "textual", None)
    for args in (["--help"], ["tui", "--help"]):
        with pytest.raises(SystemExit) as exc:
            main(args)
        assert exc.value.code == 0
    assert main(["tui", "--demo"]) == 1
    output = capsys.readouterr()
    assert "The terminal UI needs the tui extra." in output.err
    assert 'uv tool install --editable ".[tui]" --force' in output.err


def test_pilot_shell(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr("gbot.tui.screens.home.time", lambda: 1_800_000_000)

    async def exercise():
        app = GbotApp(cast(Service, load_fake()), animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            assert app.theme == "gbot"
            await pilot.press("?")
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            assert isinstance(app.screen, HomeScreen)
            await pilot.press("enter")
            assert isinstance(app.screen, SessionScreen)
            await pilot.press("escape", "right")
            assert isinstance(app.screen, SessionScreen)
            await pilot.press("escape")
            for n in range(1, 10):
                await pilot.press(f"alt+{n}")
                if n <= len(app.bots):
                    assert isinstance(app.screen, SessionScreen)
                    assert app.screen.bot_id == app.home.bot_list.visible_ids[n - 1]
                    await pilot.press("escape")
            await pilot.press("ctrl+p")
            assert app.screen.__class__.__name__ == "CommandPalette"
            await pilot.press("escape")
            await pilot.press("ctrl+c")
            assert app.is_running
            await pilot.press("ctrl+c")
            assert not app.is_running

    asyncio.run(exercise())


def test_printable_keys_in_input(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr("gbot.tui.screens.home.time", lambda: 1_800_000_000)

    async def exercise():
        app = GbotApp(cast(Service, load_fake()), animate=False)
        async with app.run_test() as pilot:
            field = Input()
            await app.screen.mount(field)
            field.focus()
            await pilot.press("?", "[", "]", "1", "space")
            assert field.value == "?[]1 "
            assert isinstance(app.screen, HomeScreen)

    asyncio.run(exercise())


def test_initial_bot(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr("gbot.tui.screens.home.time", lambda: 1_800_000_000)

    async def exercise():
        app = GbotApp(cast(Service, load_fake()), bot="Inbox", animate=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, SessionScreen)
            assert app.screen.bot_id == "demo-inbox"

    asyncio.run(exercise())


def test_home_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr("gbot.tui.screens.home.time", lambda: 1_800_000_000)

    async def exercise():
        app = GbotApp(cast(Service, load_fake()), animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await assert_snapshot(app, pilot, "demo-home")

    asyncio.run(exercise())
