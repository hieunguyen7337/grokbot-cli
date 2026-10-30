import asyncio
from unittest.mock import Mock

import pytest
from textual.widgets import Select, Static, Switch
from tui_snapshots import assert_snapshot

from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.handoff import HandoffScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, commands, run
from gbot.tui.slash.teams import TeamsAccountPanel, TeamsPanel


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


async def accept(app, pilot):
    await pilot.pause()
    assert isinstance(app.screen, ConfirmScreen)
    assert app.screen.focused is not None
    assert app.screen.focused.id == "cancel"
    await pilot.click("#confirm")
    await settle(app, pilot)


def calls(service, rpc):
    return [payload for _, name, payload in service.transport.calls if name == rpc]


INSTALLED = {
    "state": "INSTALLED",
    "tenantId": "tenant",
    "tenantDisplayName": "Example",
    "managerIsAdmin": True,
    "installedTeams": [{"teamId": "team", "displayName": "Engineering"}],
}


def test_panel_snapshot_and_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["GetGrokBotTeamsInstallState"] = INSTALLED
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            assert run(ctx, "/teams") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, TeamsPanel)
            assert ("Installed teams", "Engineering") in panel.detail.fields
            assert {a.key for a in panel.detail.actions} == {"a", "r", "x", "d", "g"}
            await assert_snapshot(app, pilot, "panel-teams")
            for state, expected in [
                ("not_connected", {"c", "g"}),
                ("app_created", {"i", "g"}),
                ("pending_admin_approval", {"g"}),
                ("unsupported_harness", {"g"}),
                ("provisioning", {"g"}),
            ]:
                service.transport.rpcs["GetGrokBotTeamsInstallState"] = {"state": state}
                await pilot.press("g")
                await settle(app, pilot)
                assert {a.key for a in panel.detail.actions} == expected
            specs = {c.name: c for c in commands()}
            assert specs["teams"].scope == "session" and specs["teams"].needs_bot
            assert specs["teams-account"].scope == "any"

    asyncio.run(exercise())


def test_mutations_cancel_errors_and_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["GetGrokBotTeamsInstallState"] = INSTALLED
        service.transport.rpcs["ListGrokBotTeamsJoinedTeams"] = {
            "teams": [{"teamId": "second", "displayName": "Second"}]
        }
        service.transport.rpcs["DisconnectGrokBotTeamsAccount"] = {
            "revoked": True,
            "stillInstalledAgentIds": ["other"],
        }
        service.transport.rpcs["ReinstallGrokBotTeamsApp"] = INSTALLED
        service.transport.rpcs["UninstallGrokBotTeamsApp"] = INSTALLED
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/teams")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, TeamsPanel)
            for key, rpc in [
                ("r", "ReinstallGrokBotTeamsApp"),
                ("x", "UninstallGrokBotTeamsApp"),
                ("d", "DisconnectGrokBotTeamsAccount"),
            ]:
                await pilot.press(key)
                assert isinstance(app.screen, ConfirmScreen)
                assert app.screen.focused is not None
                assert app.screen.focused.id == "cancel"
                await pilot.press("enter")
                assert not calls(service, rpc)
                await pilot.press(key)
                await accept(app, pilot)
            assert "other" in notice.call_args.args[0]
            for add in (False, True):
                panel.add() if add else panel.install()
                await settle(app, pilot)
                if not add:
                    app.screen.query_one("#form-0", Switch).value = False
                    app.screen.query_one("#form-1", Switch).value = True
                await pilot.press("ctrl+s")
                await settle(app, pilot)
                await accept(app, pilot)
            assert calls(service, "InstallGrokBotTeamsApp")[-1]["teamIds"] == ["second"]
            assert calls(service, "AddGrokBotTeamsAppToTeam")[-1] == {
                "agentId": "demo-helper",
                "teamId": "second",
            }
            service.transport.rpcs["ReinstallGrokBotTeamsApp"] = ValueError(
                "bad\x1b[2J[bold]"
            )
            panel.reinstall()
            await accept(app, pilot)
            assert notice.call_args.kwargs == {"severity": "error", "markup": False}
            assert "\x1b" not in notice.call_args.args[0]
            app.read_only = True
            before = len(service.transport.calls)
            for mutation in (
                panel.connect,
                panel.install,
                panel.add,
                panel.reinstall,
                panel.uninstall,
                panel.disconnect,
            ):
                mutation()
                assert notice.call_args.args[0] == "Read-only mode"
                assert app.screen is panel
            assert len(service.transport.calls) == before
            run(ctx, "/teams-account")
            await settle(app, pilot)
            account = app.screen
            assert isinstance(account, TeamsAccountPanel)
            before = len(service.transport.calls)
            account.link()
            from gbot.tui.panels.kit import PanelRow

            account.unlink(PanelRow("tenant", "Example"))
            assert notice.call_args.args[0] == "Read-only mode"
            assert len(service.transport.calls) == before

    asyncio.run(exercise())


@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("complete", [False, True])
def test_connect_handoff(tmp_path, monkeypatch, admin, complete):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    opener = Mock()

    def screen(*args, **kwargs):
        return HandoffScreen(*args, **kwargs, opener=opener)

    monkeypatch.setattr("gbot.tui.slash.teams.HandoffScreen", screen)

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/teams")
            await settle(app, pilot)
            await pilot.press("c")
            await settle(app, pilot)
            app.screen.query_one("#form-0", Select).value = (
                "Admin" if admin else "Normal"
            )
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert isinstance(app.screen, ConfirmScreen)
            assert app.screen.heading == "Connect Helper to Teams? Your browser opens."
            if complete:
                service.transport.rpcs["GetGrokBotTeamsInstallState"] = {
                    "consentResult": "ACCESS_DENIED"
                }
                await accept(app, pilot)
                assert isinstance(app.screen, TeamsPanel)
                assert "Microsoft consent was denied." in app.screen.detail.body
            else:
                await pilot.click("#confirm")
                await pilot.pause()
                assert isinstance(app.screen, HandoffScreen)
                await pilot.press("escape")
                await settle(app, pilot)
                assert isinstance(app.screen, TeamsPanel)
            opener.assert_called_once_with(
                "https://example.invalid/teams-admin"
                if admin
                else "https://example.invalid/teams"
            )
            assert not calls(service, "InstallGrokBotTeamsApp")

    asyncio.run(exercise())


def test_account_handoff_and_unlink(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    opener = Mock()

    def screen(*args, **kwargs):
        return HandoffScreen(*args, **kwargs, opener=opener)

    monkeypatch.setattr("gbot.tui.slash.teams.HandoffScreen", screen)

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/teams-account")
            await settle(app, pilot)
            await pilot.press("l")
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.press("enter")
            assert not calls(service, "StartMicrosoftTeamsAccountLink")
            await pilot.press("l")
            await pilot.click("#confirm")
            await pilot.pause()
            handoff = app.screen
            assert isinstance(handoff, HandoffScreen)
            service.transport.rpcs["GetMicrosoftTeamsAccountLinkStatus"] = {
                "links": [
                    {
                        "tenantId": "tenant",
                        "aadObjectId": "aad",
                        "linkedAtMs": "86400000",
                    }
                ]
            }
            handoff.poke()
            await settle(app, pilot)
            assert isinstance(app.screen, TeamsAccountPanel)
            assert app.screen.rows[0].detail == "1970-01-02"
            await pilot.press("x")
            assert app.screen.heading == "Unlink your Teams account in tenant?"
            await accept(app, pilot)
            assert calls(service, "UnlinkMicrosoftTeamsAccount") == [
                {"tenantId": "tenant"}
            ]
            opener.assert_called_once_with("https://example.invalid/teams-account")
            assert "No Teams account" not in str(
                app.screen.query_one("#panel-rows", Static).render()
            )

    asyncio.run(exercise())
