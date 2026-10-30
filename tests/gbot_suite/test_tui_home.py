import asyncio
import json

import pytest
from textual.widgets import Input, Static
from tui_snapshots import assert_snapshot

from gbot.service import events
from gbot.service.fake import load_fake
from gbot.service.models import Bot, ConnectionStatus
from gbot.tui import prefs
from gbot.tui.app import GbotApp
from gbot.tui.model import RowState
from gbot.tui.screens.home import HomeScreen
from gbot.tui.screens.session import SessionScreen


@pytest.fixture
def home_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr("gbot.tui.screens.home.time", lambda: 1_800_000_000)
    return tmp_path


def test_grouping_navigation_and_collapse(home_env):
    async def exercise():
        app = GbotApp(load_fake(), animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            home = app.home
            listing = home.bot_list
            assert [s.title for s in listing.sections] == [
                "Needs input",
                "Working",
                "New replies",
                "Idle",
            ]
            assert listing.selected_id == "demo-inbox"
            assert "3 need you" in str(home.query_one("#heading", Static).render())
            assert app.title == "3 need you · gbot"
            await pilot.press("down")
            assert listing.selected_id == "demo-travel"
            await pilot.press("]")
            assert listing.selected_id == "demo-research"
            await pilot.press("alt+down")
            assert listing.selected_id == "demo-ledger"
            await pilot.press("[")
            assert listing.selected_id == "demo-research"
            await pilot.press("home", "enter")
            assert listing.sections[0].collapsed
            assert "input" in home.preferences.collapsed
            await pilot.press("enter")
            assert not listing.sections[0].collapsed
            await pilot.press("end")
            assert listing.selected_id == "demo-outbox"
            await pilot.press("pageup", "pagedown")
            assert listing.selected_id == "demo-outbox"

    asyncio.run(exercise())


def test_preferences_pin_reorder_group(home_env):
    async def exercise():
        app = GbotApp(load_fake(), animate=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            home = app.home
            await pilot.press("shift+down")
            assert home.bot_list.sections[0].rows[1].bot_id == "demo-inbox"
            await pilot.press("ctrl+t")
            assert home.bot_list.sections[0].key == "pinned"
            assert home.bot_list.selected_id == "demo-inbox"
            await pilot.press("ctrl+s")
            assert [s.title for s in home.bot_list.sections] == ["Email team", "Other"]
            await app.workers.wait_for_complete()
            saved = prefs.load(prefs.path())
            assert saved.pins == ("demo-inbox",)
            assert saved.order[:2] == ("demo-travel", "demo-inbox")
            assert saved.group_by == "team"
            assert json.loads((home_env / "tui.json").read_text(encoding="utf-8"))[
                "pins"
            ] == ["demo-inbox"]
        again = GbotApp(load_fake(), animate=False)
        async with again.run_test() as pilot:
            await pilot.pause()
            assert again.home.preferences == saved

    asyncio.run(exercise())


def test_filters_dispatch_and_escape(home_env):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            field = app.home.query_one("#dispatch", Input)
            for value, expected in (
                ("s:working", ["demo-research"]),
                ("n:plan", ["demo-planner"]),
                ("t:email s:new", ["demo-ledger"]),
            ):
                field.value = value
                await pilot.pause()
                assert app.home.bot_list.visible_ids == expected
            await pilot.press("ctrl+f")
            assert field.value == "n:" and field.has_focus
            await pilot.press("escape", "escape")
            assert app.home.bot_list.has_focus
            await pilot.press("@")
            assert field.has_focus and field.value == "@"
            field.value = "@planner hi"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            assert service.sent[-1] == ("demo-planner", "hi", None)
            assert field.value == ""
            selected = app.home.bot_list.selected_id
            field.value = "hello selected"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            assert service.sent[-1] == (selected, "hello selected", None)
            field.value = "/later"
            await pilot.press("enter")
            assert len(service.sent) == 2
            twin = Bot.from_row({"id": "demo-planner-2", "name": "Planner Two"})
            assert twin
            service._emit(events.BotChanged(twin))
            await pilot.pause()
            field.value = "@plan hi"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            assert len(service.sent) == 2
            field.value = "@planner exact"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            assert service.sent[-1] == ("demo-planner", "exact", None)

    asyncio.run(exercise())


def test_live_freeze_and_status(home_env):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            listing = app.home.bot_list
            listing.freeze_delay = 0.25
            await pilot.press("]")
            assert listing.selected_id == "demo-research"
            service.reply("demo-research", "Finished searching")
            await pilot.pause(0.05)
            assert listing.sections[1].key == "working"
            assert listing.sections[1].rows[0].state == RowState.NEW_REPLY
            await pilot.pause(0.3)
            assert "working" not in [s.key for s in listing.sections]
            assert listing.selected_id == "demo-research"
            service._emit(events.ConnectionChanged(ConnectionStatus.RECONNECTING))
            await pilot.pause()
            assert "reconnecting" in str(
                app.home.query_one("#connection", Static).render()
            )
        assert service._sources[0].closed

    asyncio.run(exercise())


def test_mouse_open_and_shortcuts(home_env):
    async def exercise():
        app = GbotApp(load_fake(), animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.click("#bot-list", offset=(8, 2))
            assert app.home.bot_list.selected_id == "demo-travel"
            await pilot.click("#bot-list", offset=(8, 2), times=2)
            assert isinstance(app.screen, SessionScreen)
            await pilot.press("escape", "alt+2")
            assert isinstance(app.screen, SessionScreen)
            assert app.screen.bot_id == "demo-travel"
            await pilot.press("escape", "space", "1", "ctrl+x")
            assert isinstance(app.screen, HomeScreen)
            assert app.home.query_one(Input).value == ""

    asyncio.run(exercise())


def test_hostile_name_is_literal(home_env):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            bot = Bot.from_row(
                {"id": "hostile", "name": "[link=x]\x1b[31m", "isRunning": True}
            )
            assert bot
            service._emit(events.BotChanged(bot))
            await pilot.pause()
            svg = app.export_screenshot()
            assert "[link=x]" in svg
            assert "\x1b" not in svg
            assert 'href="x"' not in svg

    asyncio.run(exercise())


def test_service_errors_are_not_fatal(home_env, monkeypatch):
    async def exercise():
        service = load_fake()

        def fail(*args, **kwargs):
            raise OSError("Offline for this test")

        monkeypatch.setattr(service, "pending", fail)
        app = GbotApp(service, animate=False)
        notices = []
        monkeypatch.setattr(
            app, "notify", lambda message, **kwargs: notices.append(message)
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.home.rows) == 8
            assert "Offline for this test" in notices
            monkeypatch.setattr(service, "send", fail)
            field = app.home.query_one(Input)
            field.focus()
            field.value = "try sending"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            assert notices.count("Offline for this test") == 2
            assert app.is_running
            service.reply("demo-research", "Still receiving events")
            await pilot.pause()
            assert not app.state.bots["demo-research"].busy

    asyncio.run(exercise())


def test_first_run_known_sequences_and_animation(home_env):
    async def exercise():
        service = load_fake()
        service.state.rows[0]["lastEntry"] = {"seq": 4}
        app = GbotApp(service, animate=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert prefs.load(prefs.path()).last_seen == {"demo-inbox": 4}
            frame = app.home.bot_list.frame
            await pilot.pause(0.2)
            assert app.home.bot_list.frame > frame
        app = GbotApp(load_fake(), animate=False)
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            assert app.home.bot_list.frame == 0

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "size,ascii_only,name",
    [
        ((100, 30), False, "home-wide"),
        ((60, 20), False, "home-narrow"),
        ((100, 30), True, "home-ascii"),
    ],
)
def test_home_snapshots(home_env, size, ascii_only, name):
    async def exercise():
        app = GbotApp(load_fake(), ascii_only=ascii_only, animate=False)
        async with app.run_test(size=size) as pilot:
            await assert_snapshot(app, pilot, name)

    asyncio.run(exercise())
