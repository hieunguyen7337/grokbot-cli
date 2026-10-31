import asyncio
import json
from unittest.mock import Mock

from textual.widgets import Input, Select, Static, Switch
from tui_snapshots import assert_snapshot

from gbot.service import cloud_agents as service_module
from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, commands, run
from gbot.tui.slash.cloud_agents import (
    GATE_NOTE,
    AppSecretsPanel,
    AppsPanel,
    CloudAgentPanel,
)
from groken.client import ConnectError

SECRET = "sk-test-value-5f1e"
REFUSED = ConnectError(
    403, json.dumps({"code": "permission_denied", "message": "Not on this account."})
)


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def setup(app, pilot):
    await settle(app, pilot)
    screen = SessionScreen("demo-helper", bot_name="Helper")
    await app.push_screen(screen)
    await settle(app, pilot)
    return SlashContext(app, screen, screen.bot_id, None)


def confirm_screen(app) -> ConfirmScreen:
    assert isinstance(app.screen, ConfirmScreen)
    return app.screen


async def accept(app, pilot):
    await pilot.pause()
    assert isinstance(app.screen, ConfirmScreen)
    assert app.screen.focused is not None
    assert app.screen.focused.id == "cancel"
    await pilot.click("#confirm")
    await settle(app, pilot)


async def cancel(app, pilot):
    await pilot.pause()
    assert isinstance(app.screen, ConfirmScreen)
    assert app.screen.focused is not None and app.screen.focused.id == "cancel"
    await pilot.press("enter")
    await settle(app, pilot)


def calls(service, name):
    return [payload for _, called, payload in service.transport.calls if called == name]


def text(screen, selector):
    return str(screen.query_one(selector, Static).render())


def test_commands_registered():
    specs = {c.name: c for c in commands()}
    assert specs["apps"].scope == "any" and not specs["apps"].needs_bot
    assert specs["cloud-agent"].scope == "session" and specs["cloud-agent"].needs_bot


def test_apps_panel_snapshot_and_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            assert run(ctx, "/apps") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, AppsPanel)
            assert [(row.label, row.detail) for row in panel.rows] == [
                ("landing", "demo.example · public"),
                ("dashboard", "demo.example · team"),
            ]
            assert GATE_NOTE in text(panel, "#panel-rows")
            assert "e edit" in text(panel, ".panel-footer")
            await assert_snapshot(app, pilot, "panel-apps")
            await pilot.press("u")
            assert confirm_screen(app).heading == "Unpublish landing?"
            assert "Helper" in confirm_screen(app).details
            await cancel(app, pilot)
            assert not calls(service, "unpublishCloudAgentPublishApp")
            await pilot.press("u")
            await accept(app, pilot)
            assert calls(service, "unpublishCloudAgentPublishApp") == [
                {"bcId": "bc-demo-1", "slug": "landing", "apex": "demo.example"}
            ]
            assert len(calls(service, "listCloudAgentPublishedApps")) == 2
            await pilot.press("down")
            await pilot.press("e")
            await settle(app, pilot)
            form = app.screen
            assert form.query_one("#form-0", Input).value == "dashboard"
            assert form.query_one("#form-2", Select).value == "team"
            form.query_one("#form-2", Select).value = "public"
            form.query_one("#form-3", Switch).value = True
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert confirm_screen(app).heading == "Update app dashboard as public?"
            await cancel(app, pilot)
            assert not calls(service, "updateCloudAgentPublishApp")
            assert app.screen is form
            await pilot.press("ctrl+s")
            await accept(app, pilot)
            assert calls(service, "updateCloudAgentPublishApp") == [
                {
                    "bcId": "bc-demo-2",
                    "slug": "dashboard",
                    "apex": "demo.example",
                    "visibility": "public",
                    "muteRedeployPrompts": True,
                    "requireConfirmationForUpdates": False,
                }
            ]
            assert app.screen is panel
            assert len(calls(service, "listCloudAgentPublishedApps")) == 3

    asyncio.run(exercise())


def test_apps_off_refused_and_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.commands["listCloudAgentPublishedApps"] = {"kind": "off"}
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            ctx = SlashContext(app, app.screen, None, None)
            assert run(ctx, "/apps") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, AppsPanel)
            rows = text(panel, "#panel-rows")
            assert "Cloud-agent apps are off for this account." in rows
            assert GATE_NOTE in rows
            footer = text(panel, ".panel-footer")
            assert "edit" not in footer and "unpublish" not in footer
            assert "g reload" in footer
            await pilot.press("e")
            await pilot.press("u")
            assert app.screen is panel
            service.transport.commands["listCloudAgentPublishedApps"] = REFUSED
            await pilot.press("g")
            await settle(app, pilot)
            assert "Not on this account." in text(panel, "#panel-rows")
            assert "retry" not in text(panel, "#panel-rows")
            service.transport.commands["listCloudAgentPublishedApps"] = (
                service_module.DEMO_COMMANDS["listCloudAgentPublishedApps"]
            )
            service.transport.commands["unpublishCloudAgentPublishApp"] = REFUSED
            await pilot.press("g")
            await settle(app, pilot)
            await pilot.press("u")
            await accept(app, pilot)
            assert notice.call_args.args[0] == "Not on this account."
            assert notice.call_args.kwargs == {"severity": "warning", "markup": False}
            service.transport.commands["unpublishCloudAgentPublishApp"] = ValueError(
                "bad\x1b[2J"
            )
            await pilot.press("u")
            await accept(app, pilot)
            assert notice.call_args.kwargs == {"severity": "error", "markup": False}
            assert "\x1b" not in notice.call_args.args[0]

    asyncio.run(exercise())


def test_cloud_agent_panel_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.commands["getCloudAgentConversation"] = {
            "messages": [{"role": "user", "text": f"message {i}"} for i in range(25)]
        }
        service.transport.commands["getCloudAgentPublishProposals"] = {
            "proposals": [
                {"proposalId": "p1", "slug": "landing", "visibility": "private"},
                {"id": "p2", "slug": "docs", "visibility": "GROK_BOT_X_TEAM"},
            ]
        }
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            assert run(ctx, "/cloud-agent") == "Usage: /cloud-agent BC_ID"
            assert run(ctx, "/cloud-agent bc-1") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, CloudAgentPanel)
            assert ("Status", "RUNNING") in panel.detail.fields
            assert ("Files", "1") in panel.detail.fields
            assert calls(service, "getCloudAgentInfo") == [
                {"bcId": "bc-1", "includeFiles": True, "includeArtifacts": True}
            ]
            body = panel.detail.body
            assert "message 4\n" not in body + "\n" and "message 5" in body
            assert "message 24" in body
            assert "> landing · private" in body and "  docs · team" in body
            assert {a.key for a in panel.detail.actions} == {"s", "c", "d", "k", "g"}
            await pilot.press("s")
            assert confirm_screen(app).heading == "Stop cloud agent bc-1?"
            assert "Helper" in confirm_screen(app).details
            await cancel(app, pilot)
            await pilot.press("s")
            await accept(app, pilot)
            assert calls(service, "stopCloudAgent") == [{"bcId": "bc-1"}]
            await pilot.press("down")
            assert "> docs · team" in panel.detail.body
            await pilot.press("c")
            assert confirm_screen(app).heading == "Publish docs as team?"
            await cancel(app, pilot)
            assert not calls(service, "confirmCloudAgentPublishProposal")
            await pilot.press("c")
            await accept(app, pilot)
            assert calls(service, "confirmCloudAgentPublishProposal") == [
                {
                    "agentId": "demo-helper",
                    "bcId": "bc-1",
                    "proposalId": "p2",
                    "slug": "docs",
                    "visibility": "team",
                    "requireConfirmationForUpdates": False,
                }
            ]
            await pilot.press("d")
            assert (
                confirm_screen(app).heading == "Dismiss the proposal to publish docs?"
            )
            await accept(app, pilot)
            assert calls(service, "dismissCloudAgentPublishProposal") == [
                {"bcId": "bc-1", "proposalId": "p2", "agentId": "demo-helper"}
            ]
            service.transport.commands["getCloudAgentInfo"] = None
            service.transport.commands["getCloudAgentPublishProposals"] = REFUSED
            service.transport.commands["getCloudAgentConversation"] = {}
            await pilot.press("g")
            await settle(app, pilot)
            assert panel.detail.fields == (("Cloud agent", "bc-1"),)
            assert panel.detail.body == (
                "No cloud agent with that id.\nNot on this account."
            )
            assert {a.key for a in panel.detail.actions} == {"k", "g"}

    asyncio.run(exercise())


def test_app_secrets_masked_set_then_tell(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.commands["getCloudAgentAppSecrets"] = {
            "secrets": [{"name": "API_KEY", "value": SECRET}]
        }
        service.transport.commands["setCloudAgentAppSecrets"] = {
            "refused": [
                {
                    "name": "API_KEY",
                    "kind": "value_not_saved",
                    "message": "Could not save " + SECRET,
                }
            ],
            "applyNeeded": True,
        }
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/cloud-agent bc-1")
            await settle(app, pilot)
            await pilot.press("k")
            await settle(app, pilot)
            app.screen.query_one("#form-0", Input).value = "/workspace/app"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            secrets = app.screen
            assert isinstance(secrets, AppSecretsPanel)
            assert [row.key for row in secrets.rows] == ["API_KEY"]
            assert SECRET not in text(secrets, "#panel-rows")
            assert calls(service, "getCloudAgentAppSecrets") == [
                {"bcId": "bc-1", "projectDir": "/workspace/app"}
            ]
            await pilot.press("n")
            await settle(app, pilot)
            form = app.screen
            assert form.query_one("#form-0", Input).value == "API_KEY"
            value = form.query_one("#form-1", Input)
            assert value.password
            value.value = SECRET
            await pilot.press("ctrl+s")
            assert confirm_screen(app).heading == "Save secret API_KEY?"
            await cancel(app, pilot)
            assert value.value == ""
            assert not calls(service, "setCloudAgentAppSecrets")
            value.value = SECRET
            await pilot.press("ctrl+s")
            await accept(app, pilot)
            assert len(calls(service, "setCloudAgentAppSecrets")) == 1
            assert calls(service, "tellCloudAgentAppSecretsSet") == [
                {
                    "bcId": "bc-1",
                    "projectDir": "/workspace/app",
                    "names": [],
                    "refused": [
                        {
                            "name": "API_KEY",
                            "kind": "value_not_saved",
                            "message": "Could not save [redacted]",
                            "permanent": False,
                        }
                    ],
                    "applyNeeded": True,
                }
            ]
            assert app.screen is secrets
            shown = " ".join(str(call.args) for call in notice.call_args_list)
            assert "Could not save [redacted]" in shown
            assert SECRET not in shown
            assert all(SECRET not in str(row) for row in secrets.rows)
            # Only the set request carries the value; no other request or notice repeats it.
            assert [
                name
                for _, name, _args in service.transport.calls
                if SECRET in repr(_args)
            ] == ["setCloudAgentAppSecrets"]

    asyncio.run(exercise())


def test_read_only_refuses_every_change(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/apps")
            await settle(app, pilot)
            apps = app.screen
            assert isinstance(apps, AppsPanel)
            app.read_only = True
            before = len(service.transport.calls)
            for key in ("e", "u"):
                await pilot.press(key)
                assert notice.call_args.args[0] == "Read-only mode"
                assert app.screen is apps
            app.read_only = False
            run(ctx, "/cloud-agent bc-1")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, CloudAgentPanel)
            app.read_only = True
            before = len(service.transport.calls)
            for key in ("s", "c", "d"):
                await pilot.press(key)
                assert notice.call_args.args[0] == "Read-only mode"
                assert app.screen is panel
            secrets = AppSecretsPanel(ctx, "bc-1", "/app")
            app.read_only = False
            await app.push_screen(secrets)
            await settle(app, pilot)
            app.read_only = True
            await pilot.press("n")
            assert notice.call_args.args[0] == "Read-only mode"
            assert app.screen is secrets
            assert [
                call
                for call in service.transport.calls[before:]
                if call[1] != "getCloudAgentAppSecrets"
            ] == []

    asyncio.run(exercise())


def test_refused_tell_after_set_is_a_notice(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.commands["getCloudAgentAppSecrets"] = {"secrets": []}
        service.transport.commands["setCloudAgentAppSecrets"] = {"applyNeeded": True}
        service.transport.commands["tellCloudAgentAppSecretsSet"] = REFUSED
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/cloud-agent bc-1")
            await settle(app, pilot)
            await pilot.press("k")
            await settle(app, pilot)
            app.screen.query_one("#form-0", Input).value = "/workspace/app"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await pilot.press("n")
            await settle(app, pilot)
            form = app.screen
            form.query_one("#form-0", Input).value = "API_KEY"
            form.query_one("#form-1", Input).value = SECRET
            await pilot.press("ctrl+s")
            await accept(app, pilot)
            shown = " ".join(str(call.args) for call in notice.call_args_list)
            assert "Not on this account." in shown
            assert "permission_denied" not in shown and "Saved secret" in shown
            assert SECRET not in shown

    asyncio.run(exercise())


def test_unknown_visibility_app_is_not_edited_silently(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.commands["listCloudAgentPublishedApps"] = {
            "kind": "on",
            "apps": [
                {"bcId": "bc-1", "slug": "landing", "apex": "a", "visibility": "x"}
            ],
        }
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/apps")
            await settle(app, pilot)
            await pilot.press("e")
            await settle(app, pilot)
            assert isinstance(app.screen, AppsPanel)
            assert "unknown" in " ".join(str(c.args) for c in notice.call_args_list)
            assert not calls(service, "updateCloudAgentPublishApp")

    asyncio.run(exercise())


def test_empty_conversation_and_proposals_say_so(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.commands["getCloudAgentConversation"] = {"messages": []}
        service.transport.commands["getCloudAgentPublishProposals"] = {"proposals": []}
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/cloud-agent bc-1")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, CloudAgentPanel)
            assert "No messages." in panel.detail.body
            assert "No publish proposals." in panel.detail.body
            assert "[]" not in panel.detail.body

    asyncio.run(exercise())
