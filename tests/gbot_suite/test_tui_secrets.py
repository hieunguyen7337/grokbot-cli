import asyncio

from textual.widgets import Input, Static, Switch
from tui_snapshots import assert_snapshot

from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.panels.kit import FormPanel, ListPanel
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, commands, run


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


def test_secret_flows(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    notices = []

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        monkeypatch.setattr(
            app, "notify", lambda text, **kw: notices.append((text, kw))
        )
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            assert run(ctx, "/secrets") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, ListPanel)
            assert [row.label for row in panel.rows] == ["DEMO_TOKEN"]
            assert "updated" in panel.rows[0].detail
            assert "Computer: 2 secret names (applied)" in str(
                panel.query_one("#panel-rows", Static).render()
            )
            await pilot.press("a")
            assert isinstance(app.screen, FormPanel)
            form = app.screen
            name = form.query_one("#form-0", Input)
            password = form.query_one("#form-2", Input)
            assert password.password
            name.value = "1bad"
            password.value = "private-test-value"
            await pilot.press("ctrl+s")
            assert app.screen is form
            assert "start with a letter" in notices[-1][0]
            name.value = "token"
            password.value = " "
            await pilot.press("ctrl+s")
            assert "must not be empty" in notices[-1][0]
            password.value = "private-test-value"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert app.screen.heading == "Save secret TOKEN to Helper?"
            await pilot.press("escape")
            assert not calls(service, "PutGrokBotSecret")
            assert password.value == ""
            password.value = "private-test-value"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert password.value == ""
            assert calls(service, "PutGrokBotSecret") == [
                {
                    "id": "server-demo-helper",
                    "name": "TOKEN",
                    "description": "",
                    "value": "private-test-value",
                }
            ]
            assert app.screen is panel
            await pilot.press("a")
            app.screen.query_one("#form-0", Input).value = "demo_token"
            app.screen.query_one("#form-2", Input).value = "replacement"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert app.screen.heading == "Replace secret DEMO_TOKEN on Helper?"
            await pilot.press("escape", "escape")
            await pilot.press("d")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(service, "DeleteGrokBotSecret") == [
                {"id": "server-demo-helper", "name": "DEMO_TOKEN"}
            ]
            await pilot.press("c")
            app.screen.query_one("#form-0", Switch).value = True
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert app.screen.heading == "Copy 1 computer secrets to Helper?"
            await accept(app, pilot)
            assert calls(service, "carryBoxSecretsToBot")[-1]["names"] == ["DEMO_TOKEN"]
            assert notices[-1][0] == "DEMO_TOKEN: copied"
            app.read_only = True
            before = len(service.transport.calls)
            for key in ("a", "d", "c"):
                await pilot.press(key)
                assert notices[-1][0] == "Read-only mode"
                assert app.screen is panel
            assert len(service.transport.calls) == before
            assert "private-test-value" not in repr(notices)

    asyncio.run(exercise())


def test_empty_errors_and_readonly_forms(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["ListGrokBotSecrets"] = {}
        app = GbotApp(service, animate=False)
        notices = []
        monkeypatch.setattr(
            app, "notify", lambda text, **kw: notices.append((text, kw))
        )
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            run(ctx, "/secrets")
            await settle(app, pilot)
            panel = app.screen
            assert "No secrets" in str(panel.query_one("#panel-rows", Static).render())
            for key in ("a", "c"):
                await pilot.press(key)
                assert isinstance(app.screen, FormPanel)
                app.read_only = True
                await pilot.press("ctrl+s")
                assert notices[-1][0] == "Read-only mode"
                app.read_only = False
                await pilot.press("escape")
            await pilot.press("a")
            app.screen.query_one("#form-0", Input).value = "TOKEN"
            app.screen.query_one("#form-2", Input).value = "private-test-value"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            app.read_only = True
            await accept(app, pilot)
            assert not calls(service, "PutGrokBotSecret")
            app.read_only = False
            app.screen.query_one("#form-2", Input).value = "private-test-value"
            service.transport.rpcs["PutGrokBotSecret"] = RuntimeError(
                "private-test-value\x1b[2J"
            )
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert notices[-1][1] == {"severity": "error", "markup": False}
            assert "private-test-value" not in str(notices)

    asyncio.run(exercise())


def test_panel_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr("gbot.tui.slash.secrets._age", lambda stamp: "now")

    async def exercise():
        app = GbotApp(load_fake(), animate=False, read_only=True)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            run(ctx, "/secrets")
            await settle(app, pilot)
            await assert_snapshot(app, pilot, "panel-secrets")
            spec = next(command for command in commands() if command.name == "secrets")
            assert spec.scope == "session" and spec.needs_bot

    asyncio.run(exercise())
