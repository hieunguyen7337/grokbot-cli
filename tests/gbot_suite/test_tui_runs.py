import asyncio
from dataclasses import replace

from fake_calls import actions
from textual.widgets import Input

from gbot.service import events
from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, run


def test_session_run_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            bot = replace(app.state.bots["demo-helper"], running=True)
            app._receive_event(events.BotChanged(bot))
            await pilot.pause()
            screen = SessionScreen(bot.id, session_id="sub")
            await app.push_screen(screen)
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.press("ctrl+x")
            await app.workers.wait_for_complete()
            assert (
                "command",
                "interruptAgentRun",
                {"id": bot.id, "sessionId": "sub"},
            ) in actions(service.transport)
            ctx = SlashContext(app, screen, bot.id, "sub")
            assert run(ctx, "/fresh") is None
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.pause()
            await pilot.press("escape")
            assert not any(
                c[1] == "startFreshConversation" for c in actions(service.transport)
            )
            assert run(ctx, "/fresh") is None
            await pilot.pause()
            await pilot.click("#confirm")
            await app.workers.wait_for_complete()
            assert (
                "command",
                "startFreshConversation",
                {"id": bot.id, "sessionId": "sub"},
            ) in actions(service.transport)
            assert run(ctx, "/rollback") is None
            await pilot.pause()
            await pilot.click("#confirm")
            await app.workers.wait_for_complete()
            assert (
                "command",
                "rollBackConversation",
                {"id": bot.id, "sessionId": "sub"},
            ) in actions(service.transport)
            assert screen.query_one("#session-input", Input).has_focus
            assert (
                run(SlashContext(app, app.home, bot.id, None), "/rollback")
                == "/rollback works in a session"
            )

    asyncio.run(exercise())


def test_home_interrupt_sessions_and_idle(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            selected = app.home.bot_list.selected_id
            assert selected is not None
            bot = replace(
                app.state.bots[selected], running=True, running_session_ids=("a", "b")
            )
            app._receive_event(events.BotChanged(bot))
            await pilot.pause()
            await pilot.press("ctrl+x")
            await app.workers.wait_for_complete()
            assert [
                (name, args)
                for _, name, args in actions(service.transport)
                if name == "interruptAgentRun"
            ] == [
                ("interruptAgentRun", {"id": selected, "sessionId": "a"}),
                ("interruptAgentRun", {"id": selected, "sessionId": "b"}),
            ]
            app._receive_event(
                events.BotChanged(
                    replace(bot, running=False, running_turn=False, composing=False)
                )
            )
            await pilot.pause()
            field = app.home.query_one("#dispatch", Input)
            field.value = "hello"
            field.focus()
            await pilot.pause()
            field.cursor_position = len(field.value)
            await pilot.press("ctrl+x")
            await app.workers.wait_for_complete()
            assert field.value == "hello"
            assert len(actions(service.transport)) == 2

    asyncio.run(exercise())


def test_rollback_text_errors_and_hostile_names(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            bot_id = next(
                b.id
                for b in app.state.bots.values()
                if any(e.role == "user" for e in service.transcript(b.id).entries)
            )
            newest = max(
                (e for e in service.transcript(bot_id).entries if e.role == "user"),
                key=lambda e: e.seq,
            )
            screen = SessionScreen(bot_id)
            await app.push_screen(screen)
            await pilot.pause()
            await app.workers.wait_for_complete()
            ctx = SlashContext(app, screen, bot_id, None)
            assert run(ctx, "/rollback") is None
            await pilot.pause()
            await pilot.click("#confirm")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert screen.query_one("#session-input", Input).value == newest.text

            service.transport.commands["interruptAgentRun"] = OSError("Offline")
            assert run(ctx, "/interrupt") is None
            await app.workers.wait_for_complete()
            assert app.state.errors[bot_id] == "Offline"

            hostile = replace(app.state.bots[bot_id], name="[link=x]Bad\x1b[31m")
            app._receive_event(events.BotChanged(hostile))
            await pilot.pause()
            assert run(ctx, "/fresh") is None
            await pilot.pause()
            confirm = app.screen
            assert isinstance(confirm, ConfirmScreen)
            assert "[link=x]Bad" in confirm.heading
            assert "\x1b" not in confirm.heading
            await pilot.press("escape")

    asyncio.run(exercise())
