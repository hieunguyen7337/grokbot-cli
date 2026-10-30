import asyncio
from typing import cast

import pytest
from textual.widgets import Input, Static, Switch
from tui_snapshots import assert_snapshot

from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.panels.kit import ListPanel
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, run
from gbot.tui.slash.bots import BotForm


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def confirm(app, pilot):
    await pilot.pause()
    assert isinstance(app.screen, ConfirmScreen)
    assert app.screen.focused is not None
    assert app.screen.focused.id == "cancel"
    await pilot.click("#confirm")
    await settle(app, pilot)


def test_create_retry_and_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            run(SlashContext(app, app.home, None, None), "/new Test")
            await settle(app, pilot)
            form = cast(BotForm, app.screen)
            assert isinstance(form, BotForm)
            await assert_snapshot(app, pilot, "panel-new-bot")
            bad = tmp_path / "bad.png"
            bad.write_bytes(b"bad")
            form.query_one("#form-4", Input).value = str(bad)
            form.action_submit()
            assert "Invalid PNG" in str(form.query_one("#form-notice", Static).render())
            form.query_one("#form-4", Input).value = ""
            form.action_submit()
            await pilot.pause()
            await pilot.press("escape")
            assert not any(c[1] == "createAgent" for c in service.transport.calls)
            service.transport.commands["createAgent"] = OSError("Offline")
            for _ in range(2):
                form.action_submit()
                await confirm(app, pilot)
            calls = [c for c in service.transport.calls if c[1] == "createAgent"]
            assert calls[0][2]["clientNonce"] == calls[1][2]["clientNonce"]
            form.query_one("#form-0", Input).value = "Other"
            form.action_submit()
            await confirm(app, pilot)
            calls = [c for c in service.transport.calls if c[1] == "createAgent"]
            assert calls[-1][2]["clientNonce"] != calls[0][2]["clientNonce"]
            service.transport.commands["createAgent"] = {
                "agent": {"id": "demo-helper", "name": "Other"}
            }
            form.action_submit()
            await confirm(app, pilot)
            assert isinstance(app.screen, SessionScreen)
            assert any(c[1] == "kickstartAgent" for c in service.transport.calls)

    asyncio.run(exercise())


def test_settings_failures_read_only_and_hidden(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        row = next(r for r in service.state.rows if r["id"] == "demo-helper")
        row["isHiddenFromSidebar"] = True
        server: dict[str, object] = {
            "agentId": "demo-helper",
            "id": "server",
            "harness": "box",
        }
        service.transport.rpcs["ListGrokBotAgents"] = {"agents": [server]}
        service.transport.commands["setAgentHiddenFromSidebar"] = lambda args: (
            row.update(isHiddenFromSidebar=args["isHidden"])
        )
        app = GbotApp(service, animate=False)
        notices = []
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            monkeypatch.setattr(
                app, "notify", lambda message, **kwargs: notices.append(message)
            )
            home = SlashContext(app, app.home, None, None)
            run(home, "/hidden")
            await settle(app, pilot)
            assert cast(ListPanel, app.screen).rows[0].key == "demo-helper"
            await pilot.press("u")
            await confirm(app, pilot)
            assert not cast(ListPanel, app.screen).rows
            await pilot.press("escape")
            app.open_bot(app.state.bots["demo-helper"])
            await settle(app, pilot)
            ctx = SlashContext(app, app.screen, "demo-helper", None)
            run(ctx, "/bot")
            await settle(app, pilot)
            form = cast(BotForm, app.screen)
            switches = list(form.query(Switch))
            switches[0].value = False
            switches[1].value = False
            switches[2].value = False
            service.transport.commands["setAgentNotifyOnUpdates"] = OSError("Offline")
            form.action_submit()
            await confirm(app, pilot)
            assert "Turn off update notifications failed: Offline" in notices[-1]
            assert "Applied: Hide from sidebar" in notices[-1]
            assert not any(
                c[1] == "setAgentDraftingDisabled" for c in service.transport.calls
            )
            await pilot.press("escape")
            server["viewerIsOwner"] = False
            run(ctx, "/bot")
            await settle(app, pilot)
            form = cast(BotForm, app.screen)
            form.query(Switch).first().value = not form.query(Switch).first().value
            form.action_submit()
            assert "Only the bot's owner" in notices[-1]
            await pilot.press("escape")
            server["viewerIsOwner"] = True
            row["isGroup"] = True
            app.refresh_roster()
            await settle(app, pilot)
            run(ctx, "/bot")
            await settle(app, pilot)
            assert "drafting" not in [f.name for f in cast(BotForm, app.screen).fields]
            app.read_only = True
            app.screen.query(Switch).first().value = (
                not app.screen.query(Switch).first().value
            )
            count = len(service.transport.calls)
            cast(BotForm, app.screen).action_submit()
            assert notices[-1] == "Read-only mode"
            await pilot.press("escape")
            run(ctx, "/delete")
            run(ctx, "/main demo-helper")
            assert notices[-1] == "Read-only mode"
            run(ctx, "/edit")
            await settle(app, pilot)
            app.screen.query_one("#form-0", Input).value = "Changed"
            cast(BotForm, app.screen).action_submit()
            assert notices[-1] == "Read-only mode"
            await pilot.press("escape", "escape")
            run(home, "/new")
            await settle(app, pilot)
            cast(BotForm, app.screen).action_submit()
            assert notices[-1] == "Read-only mode"
            assert len(service.transport.calls) == count

    asyncio.run(exercise())


@pytest.mark.parametrize("temporal", [False, True])
def test_creation_route(tmp_path, monkeypatch, temporal):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["GetGrokBotRuntimeCapabilities"] = {
            "capabilities": {
                "temporalCreationEnabled": temporal,
                "durableIdentityEnabled": True,
                "durableIdentityWritesEnabled": True,
            }
        }
        app = GbotApp(service, animate=False)
        async with app.run_test() as pilot:
            await settle(app, pilot)
            run(SlashContext(app, app.home, None, None), "/new Test")
            await settle(app, pilot)
            cast(BotForm, app.screen).action_submit()
            await confirm(app, pilot)
            assert any(
                c[1] == ("CreateGrokBotTemporalAgent" if temporal else "createAgent")
                for c in service.transport.calls
            )

    asyncio.run(exercise())


def test_edit_settings_main_hidden_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["ListGrokBotAgents"] = {
            "agents": [{"agentId": "demo-helper", "id": "server", "harness": "box"}]
        }
        service.transport.rpcs["SetGrokBotMainAgent"] = lambda args: (
            service.transport.rpcs.update(
                {
                    "GetGrokBotUserRuntimeSettings": {
                        "settings": {"mainAgentId": args["agentId"]}
                    }
                }
            )
            or {}
        )
        app = GbotApp(service, animate=False)
        notices = []
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            monkeypatch.setattr(
                app, "notify", lambda message, **kwargs: notices.append(message)
            )
            app.open_bot(app.state.bots["demo-helper"])
            await settle(app, pilot)
            ctx = SlashContext(app, app.screen, "demo-helper", None)
            run(ctx, "/edit")
            await settle(app, pilot)
            form = cast(BotForm, app.screen)
            form.action_submit()
            assert "Nothing to change" in notices
            form.query_one("#form-1", Input).value = "Title"
            form.action_submit()
            await confirm(app, pilot)
            call = next(c for c in service.transport.calls if c[1] == "updateAgent")
            assert call[2]["editedFields"] == ["title"]
            run(ctx, "/bot")
            await settle(app, pilot)
            form = cast(BotForm, app.screen)
            await assert_snapshot(app, pilot, "panel-bot-settings")
            switches = list(form.query(Switch))
            for switch in switches:
                switch.value = not switch.value
            form.action_submit()
            await pilot.pause()
            assert "Hide from sidebar" in cast(ConfirmScreen, app.screen).details
            assert "Turn off drafting" in cast(ConfirmScreen, app.screen).details
            await confirm(app, pilot)
            for command, key in [
                ("setAgentHiddenFromSidebar", "isHidden"),
                ("setAgentNotifyOnUpdates", "isEnabled"),
                ("setAgentDraftingDisabled", "isDisabled"),
            ]:
                call = next(c for c in service.transport.calls if c[1] == command)
                assert call[2][key] is (key != "isEnabled")
            assert app.main_bot_id == "demo-helper"
            run(ctx, "/main")
            assert "Main bot: Helper" in notices
            await pilot.press("escape")
            await settle(app, pilot)
            assert (
                sum(r.is_main for s in app.home.bot_list.sections for r in s.rows) == 1
            )
            await assert_snapshot(app, pilot, "home-main-bot")
            run(SlashContext(app, app.home, None, None), "/hidden")
            await settle(app, pilot)
            assert isinstance(app.screen, ListPanel)
            assert not cast(ListPanel, app.screen).rows
            await pilot.press("escape")
            app.open_bot(app.state.bots["demo-helper"])
            await settle(app, pilot)
            ctx = SlashContext(app, app.screen, "demo-helper", None)
            run(ctx, "/delete")
            await confirm(app, pilot)
            assert any("Cannot delete the current main bot" in n for n in notices)
            service.transport.rpcs["GetGrokBotUserRuntimeSettings"] = {}
            run(ctx, "/delete")
            await confirm(app, pilot)
            assert app.screen is app.home
            assert any(c[1] == "deleteAgents" for c in service.transport.calls)

    asyncio.run(exercise())
