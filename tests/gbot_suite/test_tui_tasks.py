import asyncio
from dataclasses import replace

from textual.widgets import Input
from tui_snapshots import assert_snapshot

from gbot.output import terminal_safe
from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.panels import ListPanel
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, run


def test_threads(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            ctx = SlashContext(app, app.home, "demo-helper", None)
            run(ctx, "/threads")
            await pilot.pause()
            await app.workers.wait_for_complete()
            panel = app.screen
            assert isinstance(panel, ListPanel)
            assert [r.status for r in panel.rows] == ["pinned", "unread"]
            await assert_snapshot(app, pilot, "panel-threads")
            await pilot.press("p")
            await app.workers.wait_for_complete()
            assert (
                "command",
                "setAgentTaskPinned",
                {"agentId": "demo-helper", "taskId": "plan", "isPinned": False},
            ) in service.transport.calls
            await pilot.press("d")
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.press("escape")
            assert not any(c[1] == "markAgentTaskDone" for c in service.transport.calls)
            await pilot.press("d")
            await pilot.pause()
            await pilot.click("#confirm")
            await app.workers.wait_for_complete()
            assert any(c[1] == "markAgentTaskDone" for c in service.transport.calls)
            await pilot.press("down", "enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert isinstance(app.screen, SessionScreen)
            assert app.screen.session_id == "task:research"
            assert (
                "command",
                "markAgentTaskRead",
                {"agentId": "demo-helper", "taskId": "research", "entryId": "result"},
            ) in service.transport.calls
            screen = SessionScreen("demo-helper", session_id="s1")
            await app.push_screen(screen)
            await pilot.pause()
            app.read_only = True
            run(SlashContext(app, screen, "demo-helper", "s1"), "/threads")
            await pilot.pause()
            await app.workers.wait_for_complete()
            count = len(service.transport.calls)
            await pilot.press("p", "d")
            assert isinstance(app.screen, ListPanel)
            await pilot.press("down", "enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert app.screen.session_id == "task:research:s1"
            assert len(service.transport.calls) == count

    asyncio.run(exercise())


def test_panels_suggestions_and_unread(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            ctx = SlashContext(app, app.home, "demo-helper", None)
            for command in ("background", "subagents", "outline"):
                run(ctx, "/" + command)
                await pilot.pause()
                await app.workers.wait_for_complete()
                assert isinstance(app.screen, ListPanel)
                assert app.screen.rows
                await pilot.press("escape")
            service.transport.commands["getAgentTasks"] = OSError("Offline")
            run(ctx, "/threads")
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert isinstance(app.screen, ListPanel)
            assert app.screen.error == "Offline"
            service.transport.commands["getAgentTasks"] = [
                {"id": "bad", "name": "[link=x]Bad\x1b[31m"}
            ]
            await pilot.press("r")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert isinstance(app.screen, ListPanel)
            assert app.screen.rows[0].label == terminal_safe("[link=x]Bad\x1b[31m")
            await pilot.press("escape")
            run(ctx, "/suggestions")
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert isinstance(app.screen, ListPanel)
            assert app.screen.empty == "No suggestions" and not app.screen.rows
            await pilot.press("escape")
            bot = app.state.bots["demo-helper"]
            app.state.bots[bot.id] = replace(
                bot,
                raw={
                    **bot.raw,
                    "suggestions": [
                        {"id": "a", "title": "First", "prompt": "Draft this"},
                        {"id": "b", "title": "Second", "prompt": "Other"},
                    ],
                },
            )
            run(ctx, "/suggestions")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.press("h")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert (
                "command",
                "dismissAgentSuggestions",
                {"agentId": bot.id, "suggestionIds": ["a"], "reason": "hidden"},
            ) in service.transport.calls
            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert app.screen.query_one("#session-input", Input).value == "Other"
            assert (
                "command",
                "dismissAgentSuggestions",
                {"agentId": bot.id, "suggestionIds": ["b"], "reason": "acted"},
            ) in service.transport.calls
            for command in ("read", "unread"):
                run(ctx, "/" + command)
                await app.workers.wait_for_complete()
            assert (
                "command",
                "setAgentUnread",
                {"id": bot.id, "isUnread": False, "markFollowedThreadsRead": True},
            ) in service.transport.calls
            assert (
                "command",
                "setAgentUnread",
                {"id": bot.id, "isUnread": True},
            ) in service.transport.calls
            app.read_only = True
            count = len(service.transport.calls)
            run(ctx, "/read")
            run(ctx, "/unread")
            await app.workers.wait_for_complete()
            assert len(service.transport.calls) == count

    asyncio.run(exercise())
