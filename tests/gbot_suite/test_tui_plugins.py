import asyncio

import pytest
from textual.widgets import Input, Static
from tui_snapshots import assert_snapshot

from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.panels.kit import DetailPanel, FormPanel
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, commands, run
from gbot.tui.slash.plugins import _CatalogPanel, _PluginsPanel


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def session(app, pilot):
    await settle(app, pilot)
    screen = SessionScreen("demo-helper", bot_name="Helper")
    await app.push_screen(screen)
    await settle(app, pilot)
    return SlashContext(app, screen, screen.bot_id, None)


def calls(service, name):
    return [
        payload for _, command, payload in service.transport.calls if command == name
    ]


async def accept(app, pilot):
    assert isinstance(app.screen, ConfirmScreen)
    assert app.screen.focused is not None
    assert app.screen.focused.id == "cancel"
    await pilot.click("#confirm")
    await settle(app, pilot)


def test_lists_details_and_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        app = GbotApp(load_fake(), animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            assert run(ctx, "/plugins") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, _PluginsPanel)
            assert panel.rows[0].label == "Notes"
            assert "needs setup" in panel.rows[0].detail
            await assert_snapshot(app, pilot, "panel-plugins")
            panel.open_plugin(panel.rows[0])
            await settle(app, pilot)
            assert isinstance(app.screen, DetailPanel)
            text = str(app.screen.query_one("#detail-content", Static).content)
            assert all(
                word in text
                for word in (
                    "Find notes",
                    "Servers",
                    "Install mode",
                    "Credential source",
                )
            )
            await pilot.press("escape", "escape")
            assert run(ctx, "/catalog") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, _CatalogPanel)
            assert [r.label for r in panel.rows if r.key.startswith("heading:")] == [
                "Productivity",
                "Utilities",
            ]
            await assert_snapshot(app, pilot, "panel-catalog")
            panel.query_one("#panel-filter", Input).value = "Notes"
            await settle(app, pilot)
            assert [r.label for r in panel.visible_rows] == ["Productivity", "Notes"]
            panel.open_entry(panel.visible_rows[1])
            await settle(app, pilot)
            text = str(app.screen.query_one("#detail-content", Static).content)
            assert all(
                word in text
                for word in ("Publisher", "Demo", "Connectors", "API token", "secret")
            )
        specs = {c.name: c for c in commands()}
        assert specs["plugins"].scope == "session" and specs["plugins"].needs_bot
        assert specs["catalog"].scope == "any"

    asyncio.run(exercise())


def test_add_cancel_and_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["GetGrokBotAgentPlugins"] = {}
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            run(ctx, "/plugins")
            await settle(app, pilot)
            panel = app.screen
            await pilot.press("a")
            await settle(app, pilot)
            catalog = app.screen
            assert isinstance(catalog, _CatalogPanel)
            catalog.add(catalog.rows[1])
            await settle(app, pilot)
            assert isinstance(app.screen, ConfirmScreen)
            assert app.screen.heading == "Add Notes to Helper?"
            assert app.screen.focused is not None
            assert app.screen.focused.id == "cancel"
            await pilot.click("#cancel")
            await settle(app, pilot)
            assert not calls(service, "SetGrokBotAgentPlugins")
            catalog.add(catalog.rows[1])
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(service, "SetGrokBotAgentPlugins")[-1] == {
                "agentId": "demo-helper",
                "plugins": [{"pluginId": "12"}],
            }
            form = app.screen
            assert isinstance(form, FormPanel)
            assert form.fields[0].kind == "password"
            assert form.query_one("#form-0", Input).value == ""
            password = form.query_one("#form-0", Input)
            password.value = "private-test"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert isinstance(app.screen, ConfirmScreen)
            assert app.screen.heading == "Save settings for Notes?"
            await accept(app, pilot)
            assert password.value == ""
            assert calls(service, "SetGrokBotAgentPluginVariables")[-1][
                "variables"
            ] == {"api_token": "private-test"}
            assert panel is not app.screen

    asyncio.run(exercise())


@pytest.mark.parametrize("read_only", [False, True])
def test_remove_settings_and_read_only(tmp_path, monkeypatch, read_only):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False, read_only=read_only)
        notices = []
        monkeypatch.setattr(app, "notify", lambda text, **kw: notices.append(text))
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            run(ctx, "/plugins")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, _PluginsPanel)
            row = panel.rows[0]
            panel.remove_plugin(row)
            await settle(app, pilot)
            if read_only:
                assert app.screen is panel
                panel.settings(row)
                panel.add()
                run(ctx, "/catalog")
                await settle(app, pilot)
                catalog = app.screen
                assert isinstance(catalog, _CatalogPanel)
                catalog.add(catalog.rows[1])
                assert notices.count("Read-only mode") == 4
                assert not calls(service, "SetGrokBotAgentPlugins")
                assert not calls(service, "SetGrokBotAgentPluginVariables")
                return
            assert isinstance(app.screen, ConfirmScreen)
            assert app.screen.heading == "Remove Notes from Helper?"
            await pilot.press("escape")
            await settle(app, pilot)
            assert not calls(service, "SetGrokBotAgentPlugins")
            panel.remove_plugin(row)
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(service, "SetGrokBotAgentPlugins")[-1]["plugins"] == []
            panel.settings(row)
            await settle(app, pilot)
            form = app.screen
            assert isinstance(form, FormPanel)
            form.query_one("#form-0", Input).value = "private-test"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await pilot.press("escape")
            await settle(app, pilot)
            assert form.query_one("#form-0", Input).value == ""
            assert not calls(service, "SetGrokBotAgentPluginVariables")
            app.read_only = True
            form.action_submit()
            assert notices[-1] == "Read-only mode"

    asyncio.run(exercise())
