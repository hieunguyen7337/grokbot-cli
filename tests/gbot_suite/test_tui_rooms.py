import asyncio
from uuid import UUID

from textual.widgets import Input, Static, Switch
from tui_snapshots import assert_snapshot

from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.panels import FormPanel, ListPanel
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, run


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


def test_newgroup(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)

        def create(args):
            row = {
                "id": "new",
                "name": args["name"],
                "isGroup": True,
                "memberIds": args["memberAgentIds"],
            }
            service.state.rows.append(row)
            return {"agent": row, "transcript": []}

        service.transport.commands["createGroup"] = create
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            ctx = SlashContext(app, app.home, None, None)
            run(ctx, "/newgroup")
            await settle(app, pilot)
            form = app.screen
            assert isinstance(form, FormPanel)
            switches = list(form.query(Switch))
            switches[0].value = switches[1].value = True
            form.action_submit()
            assert "Required" in str(form.query_one("#form-error-0", Static).render())
            form.query_one("#form-0", Input).value = "[link=x]Team"
            switches[1].value = False
            form.action_submit()
            assert "two bots" in str(form.query_one("#form-notice", Static).render())
            assert not service.transport.calls
            switches[1].value = True
            form.action_submit()
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.press("escape")
            assert not service.transport.calls
            form.action_submit()
            await pilot.pause()
            await pilot.click("#confirm")
            await settle(app, pilot)
            call = next(c for c in service.transport.calls if c[1] == "createGroup")
            chosen = call[2]["memberAgentIds"]
            nonce = call[2]["clientNonce"]
            assert isinstance(chosen, list) and len(chosen) == 2
            assert isinstance(nonce, str) and UUID(nonce).version == 4
            assert isinstance(app.screen, SessionScreen)
            assert app.screen.bot_id == "new"
            assert "new" in app.state.bots

    asyncio.run(exercise())


def test_form_errors_fallback_and_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notices = []
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            monkeypatch.setattr(
                app, "notify", lambda message, **kwargs: notices.append(message)
            )
            ctx = SlashContext(app, app.home, None, None)
            run(ctx, "/newgroup")
            await settle(app, pilot)
            form = app.screen
            assert isinstance(form, FormPanel)
            form.query_one("#form-0", Input).value = "[link=x]Team"
            switches = list(form.query(Switch))
            switches[0].value = switches[1].value = True
            form.action_submit()
            await pilot.pause()
            app.read_only = True
            await pilot.click("#confirm")
            await settle(app, pilot)
            assert not service.transport.calls
            assert "Read-only mode" in notices
            app.read_only = False
            service.transport.commands["createGroup"] = OSError("Offline")
            form.action_submit()
            await pilot.pause()
            await pilot.click("#confirm")
            await settle(app, pilot)
            assert "Offline" in notices
            assert app.screen is form
            service.transport.commands["createGroup"] = None
            form.action_submit()
            await pilot.pause()
            await pilot.click("#confirm")
            await settle(app, pilot)
            assert app.screen is app.home
            assert "Created [link=x]Team" in notices

    asyncio.run(exercise())


def test_members(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        ids = [b.id for b in service.roster() if not b.is_group]
        row = {
            "id": "room",
            "name": "[link=x]Team\x1b[31m",
            "isGroup": True,
            "memberIds": ids[:2],
            "people": [
                {"displayName": "Me", "isViewer": True, "userId": 1},
                {"displayName": "Other", "isViewer": False, "userId": 42},
                {"displayName": "Unknown", "isViewer": False},
            ],
        }
        service.state.rows.append(row)

        def set_members(args):
            row["memberIds"] = args["memberAgentIds"]

        service.transport.commands["setGroupMembers"] = set_members

        def remove_people(args):
            row["people"] = [
                p for p in row["people"] if p.get("userId") not in args["userIds"]
            ]
            return {}

        service.transport.rpcs["RemoveGrokBotRoomPeople"] = remove_people
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            ctx = SlashContext(app, app.home, "room", None)
            run(ctx, "/members")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, ListPanel)
            assert [r.status for r in panel.rows] == [
                "bot",
                "bot",
                "you",
                "person",
                "person",
            ]
            assert "[link=x]Team" in app.export_screenshot()
            assert "\x1b" not in panel.heading
            await assert_snapshot(app, pilot, "panel-members")
            await pilot.press("a")
            await settle(app, pilot)
            form = app.screen
            assert isinstance(form, FormPanel)
            form.query(Switch).first().value = True
            form.action_submit()
            await pilot.pause()
            await pilot.press("escape")
            assert not service.transport.calls
            form.action_submit()
            await pilot.pause()
            await pilot.click("#confirm")
            await settle(app, pilot)
            assert len(row["memberIds"]) == 3
            assert len([r for r in panel.rows if r.status == "bot"]) == 3
            for _ in range(2):
                panel.index = 0
                await pilot.press("x")
                await pilot.pause()
                assert isinstance(app.screen, ConfirmScreen)
                await pilot.click("#confirm")
                await settle(app, pilot)
            count = len(service.transport.calls)
            panel.index = 0
            await pilot.press("x")
            assert len(service.transport.calls) == count
            assert app.screen is panel
            panel.index = 1
            await pilot.press("x")
            assert app.screen is panel
            panel.index = 3
            await pilot.press("x")
            assert app.screen is panel
            panel.index = 2
            await pilot.press("x")
            await pilot.pause()
            await pilot.click("#confirm")
            await settle(app, pilot)
            assert service.transport.calls[-1] == (
                "rpc",
                "RemoveGrokBotRoomPeople",
                {"agentId": "room", "userIds": [42]},
            )
            assert "Other" not in [r.label for r in panel.rows]
            app.read_only = True
            count = len(service.transport.calls)
            await pilot.press("a", "x")
            panel.index = 0
            await pilot.press("x")
            assert app.screen is panel
            await pilot.press("escape")
            run(ctx, "/newgroup")
            assert app.screen is app.home
            run(SlashContext(app, app.home, ids[0], None), "/members")
            assert app.screen is app.home
            assert len(service.transport.calls) == count

    asyncio.run(exercise())
