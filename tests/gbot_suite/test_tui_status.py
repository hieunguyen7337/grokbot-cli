import asyncio
from dataclasses import replace

import pytest
from rich.text import Text
from textual.command import CommandPalette, Hit
from textual.widgets import Input, Static
from tui_snapshots import assert_snapshot

from gbot.service import events
from gbot.service.fake import load_fake
from gbot.service.models import Awaiting, Bot, ConnectionStatus
from gbot.tui.app import GbotApp
from gbot.tui.notifications import Notice, Notifier
from gbot.tui.palette import GbotCommands
from gbot.tui.screens.session import SessionScreen


@pytest.fixture
def home_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr("gbot.tui.screens.home.time", lambda: 1_800_000_000)
    return tmp_path


def test_notifier_transitions():
    notifier = Notifier()
    idle = Bot("a", "A")
    working = replace(idle, running=True, has_unread=True)
    new = replace(idle, has_unread=True)
    awaiting = replace(working, awaiting=Awaiting("answer"))
    assert notifier.update([awaiting], open_bot_id=None) == []
    assert notifier.update([idle], open_bot_id=None) == []
    assert notifier.update([new], open_bot_id=None) == [Notice("a", "A replied", False)]
    assert notifier.update([new], open_bot_id=None) == []
    assert notifier.update([working], open_bot_id=None) == []
    assert notifier.update([new], open_bot_id=None) == [Notice("a", "A replied", False)]
    assert notifier.update([awaiting], open_bot_id=None) == [
        Notice("a", "A needs you", True)
    ]
    # Awaiting -> unread is not a reply transition.
    assert notifier.update([new], open_bot_id=None) == []
    assert notifier.update([awaiting], open_bot_id="a") == []
    assert notifier.update([awaiting], open_bot_id=None) == []
    assert notifier.update([], open_bot_id=None) == []
    assert notifier.update([new], open_bot_id=None) == []
    assert notifier.update([replace(idle, hidden=True)], open_bot_id=None) == []
    assert notifier.update([awaiting], open_bot_id=None) == [
        Notice("a", "A needs you", True)
    ]


def test_status_notifications_and_nudges(home_env, monkeypatch):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notices = []
        monkeypatch.setattr(
            app, "notify", lambda text, **kw: notices.append((text, kw))
        )
        async with app.run_test(size=(160, 30)) as pilot:
            await pilot.pause()
            for status in ConnectionStatus:
                service._emit(events.ConnectionChanged(status, 2, "detail"))
                await pilot.pause()
                rendered = str(app.home.query_one("#connection", Static).render())
                assert status.value in rendered
                if status == ConnectionStatus.RECONNECTING:
                    assert "(2)" in rendered
                before = service._sources[0].nudges
                app.home.send_message("demo-outbox", "hello", str(status))
                await app.workers.wait_for_complete()
                await pilot.pause()
                assert service._sources[0].nudges - before == int(
                    status in {ConnectionStatus.ASLEEP, ConnectionStatus.SIGNED_OUT}
                )
            service._emit(events.ConnectionChanged(ConnectionStatus.SIGNED_OUT))
            service._emit(events.ConnectionChanged(ConnectionStatus.SIGNED_OUT))
            await pilot.pause()
            signed_out = [n for n in notices if n[0] == "Signed out. Run: gbot login"]
            assert len(signed_out) == 2
            assert all(n[1]["severity"] == "error" for n in signed_out)

    asyncio.run(exercise())


def test_peek_reply_nudges_and_badges(home_env, monkeypatch):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            service._emit(events.ConnectionChanged(ConnectionStatus.ASLEEP))
            await pilot.pause()
            await pilot.press("space", "tab")
            reply = app.home.peek.reply
            bot_id = app.home.peek.bot_id
            assert reply.has_focus and bot_id
            reply.value = "wake up"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert service.sent[-1][:2] == (bot_id, "wake up")
            assert service._sources[0].nudges == 1

            def fail(*args, **kwargs):
                raise OSError("Offline for this test")

            monkeypatch.setattr(service, "send", fail)
            reply.value = "again"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.state.errors[bot_id] == "Offline for this test"
            assert service._sources[0].nudges == 1

    asyncio.run(exercise())


def test_bot_errors_and_recovery(home_env, monkeypatch):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            send, pending = service.send, service.pending

            def fail(*args, **kwargs):
                raise OSError("Offline")

            monkeypatch.setattr(service, "send", fail)
            app.home.send_message("demo-outbox", "hi", "one")
            await app.workers.wait_for_complete()
            assert app.state.errors["demo-outbox"] == "Offline"
            assert (
                next(r for r in app.home.rows if r.bot_id == "demo-outbox").badge
                == "error"
            )
            monkeypatch.setattr(service, "send", send)
            app.home.send_message("demo-outbox", "hi", "two")
            await app.workers.wait_for_complete()
            assert "demo-outbox" not in app.state.errors
            assert (
                next(r for r in app.home.rows if r.bot_id == "demo-outbox").badge
                is None
            )
            monkeypatch.setattr(service, "pending", fail)
            app.refresh_cards("demo-outbox")
            await app.workers.wait_for_complete()
            assert app.state.errors["demo-outbox"] == "Offline"
            monkeypatch.setattr(service, "pending", pending)
            app.refresh_cards("demo-outbox")
            await app.workers.wait_for_complete()
            assert "demo-outbox" not in app.state.errors

    asyncio.run(exercise())


def test_roster_notices_and_bells(home_env, monkeypatch):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notices, bells = [], []
        monkeypatch.setattr(
            app, "notify", lambda text, **kw: notices.append((text, kw))
        )
        monkeypatch.setattr(app, "bell", lambda: bells.append(True))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert not notices and not bells
            service.reply("demo-research", "Done")
            await pilot.pause()
            assert ("Research replied", {"markup": False}) in notices
            bot = replace(app.state.bots["demo-outbox"], awaiting=Awaiting("answer"))
            service._emit(events.BotChanged(bot))
            service._emit(events.BotChanged(bot))
            await pilot.pause()
            assert bells == [True]
            assert [n[0] for n in notices].count("Outbox needs you") == 1
            app.bell_enabled = False
            other = replace(app.state.bots["demo-team"], awaiting=Awaiting("answer"))
            service._emit(events.BotChanged(other))
            await pilot.pause()
            assert bells == [True]
            app.open_bot(app.state.bots["demo-research"])
            await pilot.pause()
            count = len(notices)
            service._emit(
                events.BotChanged(
                    replace(
                        app.state.bots["demo-research"], awaiting=Awaiting("answer")
                    )
                )
            )
            await pilot.pause()
            assert len(notices) == count

    asyncio.run(exercise())


def test_palette_commands(home_env):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("ctrl+p")
            assert isinstance(app.screen, CommandPalette)
            field = app.screen.query_one(Input)
            field.value = "plan"
            await pilot.pause(0.5)
            provider = GbotCommands(app.home)
            hits = [hit async for hit in provider.search("plan")]
            assert max(hits, key=lambda hit: hit.score).text == "Open Planner"
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, SessionScreen)
            assert app.screen.bot_id == "demo-planner"
            assert [label for label, _ in GbotCommands(app.screen).commands()] == [
                "Keyboard help",
                "Quit",
            ]
            await pilot.press("escape", "ctrl+p")
            app.screen.query_one(Input).value = "Group by team"
            await pilot.pause(0.5)
            await pilot.press("enter")
            await pilot.pause()
            assert app.home.preferences.group_by == "team"
            commands = dict(provider.commands())
            commands["Group by state"]()
            assert app.home.preferences.group_by == "state"
            commands["Group by team"]()
            assert app.home.preferences.group_by == "team"
            commands["Filter bots"]()
            await pilot.pause()
            assert app.home.query_one(Input).value == "n:"
            assert app.home.query_one(Input).has_focus
            app.home.action_escape()
            await pilot.pause()
            selected = app.home.bot_list.selected_id
            pin = next(
                action
                for label, action in provider.commands()
                if label.startswith("Pin or unpin")
            )
            pin()
            assert selected in app.home.preferences.pins
            pin()
            assert selected not in app.home.preferences.pins
            hostile = Bot("hostile", "[link=x]Bad\x1b[31m")
            service._emit(events.BotChanged(hostile))
            await pilot.pause()
            hit = await anext(provider.search("Bad"))
            assert isinstance(hit, Hit)
            assert isinstance(hit.match_display, Text)
            assert "[link=x]" in hit.match_display.plain
            assert not hit.match_display.spans
            assert "\x1b" not in hit.match_display.plain
            dict(provider.commands())["Keyboard help"]()
            await pilot.pause()
            assert app.screen is not app.home
            dict(provider.commands())["Quit"]()
        assert service._sources[0].closed

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "status,size,name",
    [
        (ConnectionStatus.ASLEEP, (60, 20), "status-asleep"),
        (ConnectionStatus.SIGNED_OUT, (100, 30), "status-signed-out"),
    ],
)
def test_status_snapshots(home_env, status, size, name, monkeypatch):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        monkeypatch.setattr(app, "notify", lambda *args, **kwargs: None)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            service._emit(events.ConnectionChanged(status))
            await pilot.pause()
            if status == ConnectionStatus.ASLEEP:
                assert (
                    str(app.home.query_one("#connection", Static).render())
                    == "● asleep"
                )
                heading = str(app.home.query_one("#heading", Static).render())
                assert "3 need you" in heading and "3 idle" in heading
                assert "1 working" in heading and "1 new reply" in heading
            await assert_snapshot(app, pilot, name)

    asyncio.run(exercise())
