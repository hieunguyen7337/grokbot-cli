import asyncio
from unittest.mock import Mock

import pytest
from textual.widgets import Input, Select, Static, TextArea
from tui_snapshots import assert_snapshot

from gbot.service.events import Other
from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp, ServiceEvent
from gbot.tui.panels.kit import FormPanel
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.slash import SlashContext, run
from gbot.tui.slash.connectors import (
    ConnectorPanel,
    ConnectorsPanel,
    ConnectorToolsPanel,
    _Handoff,
)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def accept(app, pilot):
    assert isinstance(app.screen, ConfirmScreen)
    assert app.screen.focused is not None and app.screen.focused.id == "cancel"
    await pilot.click("#confirm")
    await settle(app, pilot)


def calls(service, name):
    return [
        payload for _, command, payload in service.transport.calls if command == name
    ]


def test_panels_snapshot_and_tools():
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            ctx = SlashContext(app, app.screen, None, None)
            assert run(ctx, "/connectors") is None
            await settle(app, pilot)
            assert isinstance(app.screen, ConnectorsPanel)
            assert app.screen.rows[0].detail == "Personal · connected · 1 tools"
            await assert_snapshot(app, pilot, "panel-connectors")
            await pilot.press("enter")
            await settle(app, pilot)
            detail = app.screen
            assert isinstance(detail, ConnectorPanel)
            assert {k for k, _ in detail.detail.fields} == {
                "Status",
                "Account",
                "Transport",
                "Tools",
                "Group chats",
                "Instructions",
            }
            await pilot.press("t")
            await settle(app, pilot)
            assert isinstance(app.screen, ConnectorToolsPanel)
            await assert_snapshot(app, pilot, "panel-connector-tools")
            await pilot.press("space")
            await settle(app, pilot)
            assert isinstance(app.screen, ConfirmScreen)
            assert app.screen.focused is not None and app.screen.focused.id == "cancel"
            await pilot.press("enter")
            await settle(app, pilot)
            assert not calls(service, "toggleMcpToolDisabled")
            await pilot.press("space")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(service, "toggleMcpToolDisabled") == [
                {"serverId": "demo-connector", "toolName": "search"}
            ]
            for key, name in (("p", "level"), ("d", "reads")):
                await pilot.press(key)
                await settle(app, pilot)
                assert isinstance(app.screen, FormPanel)
                app.screen.query_one("#form-0", Select).value = "Blocked"
                await pilot.press("ctrl+s")
                await settle(app, pilot)
                await pilot.press("escape")
                count = len(calls(service, "SetGrokBotMcpToolPermissions"))
                await pilot.press("ctrl+s")
                await settle(app, pilot)
                await accept(app, pilot)
                assert len(calls(service, "SetGrokBotMcpToolPermissions")) == count + 1
                payload = calls(service, "SetGrokBotMcpToolPermissions")[-1]
                assert (
                    payload["tools"] == {"search": 3}
                    if name == "level"
                    else payload["reads"] == 3
                )

    asyncio.run(exercise())


def test_detail_mutations_cancel_and_accept():
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            run(SlashContext(app, app.screen, None, None), "/connectors")
            await settle(app, pilot)
            listing = app.screen
            await pilot.press("A")
            await settle(app, pilot)
            assert isinstance(app.screen, ConfirmScreen)
            assert (
                app.screen.heading
                == 'Forget every "always allow" answer for connector tools?'
            )
            await pilot.press("escape")
            assert not calls(service, "ClearGrokBotConnectorAlwaysAllow")
            await pilot.press("A")
            await settle(app, pilot)
            await accept(app, pilot)
            await pilot.press("enter")
            await settle(app, pilot)
            for key, name, value in (
                ("i", "setMcpCustomInstructions", "New instructions"),
                ("n", "renameMcpAccount", "Work"),
            ):
                await pilot.press(key)
                await settle(app, pilot)
                widget = app.screen.query_one("#form-0")
                if isinstance(widget, TextArea):
                    widget.text = value
                else:
                    assert isinstance(widget, Input)
                    widget.value = value
                await pilot.press("ctrl+s")
                await settle(app, pilot)
                await pilot.press("escape")
                assert not calls(service, name)
                await pilot.press("ctrl+s")
                await settle(app, pilot)
                await accept(app, pilot)
                assert len(calls(service, name)) == 1
            for key, name in (
                ("g", "UpdateGrokBotConnectorSharedSpaceAllowlist"),
                ("x", "removeMcpAccount"),
                ("X", "removeMcpServer"),
            ):
                await pilot.press(key)
                await settle(app, pilot)
                assert isinstance(app.screen, ConfirmScreen)
                await pilot.press("escape")
                assert not calls(service, name)
                await pilot.press(key)
                await settle(app, pilot)
                await accept(app, pilot)
                assert len(calls(service, name)) == 1
            assert app.screen is listing

    asyncio.run(exercise())


def test_read_only_and_hidden_actions(monkeypatch):
    async def exercise():
        service = load_fake()
        service.transport.commands["getMcpState"] = {
            "servers": [{"id": "team", "name": "Team", "isTeamServer": True}]
        }
        app = GbotApp(service, animate=False, read_only=True)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test() as pilot:
            await settle(app, pilot)
            run(SlashContext(app, app.screen, None, None), "/connectors")
            await settle(app, pilot)
            await pilot.press("A")
            notice.assert_called_with(
                "Read-only mode", severity="warning", markup=False
            )
            await pilot.press("enter")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, ConnectorPanel)
            assert not {"X", "x", "n"} & {a.key for a in panel.detail.actions}
            for key in ("i", "s", "g"):
                await pilot.press(key)
                notice.assert_called_with(
                    "Read-only mode", severity="warning", markup=False
                )
                assert app.screen is panel
            await pilot.press("t")
            await settle(app, pilot)
            tools = app.screen
            for key in ("space", "p", "d"):
                await pilot.press(key)
                assert app.screen is tools
                notice.assert_called_with(
                    "Read-only mode", severity="warning", markup=False
                )

    asyncio.run(exercise())


def test_sign_in_event_wiring(monkeypatch):
    opener = Mock(return_value=True)
    original = _Handoff.__init__

    def injected(self, *args, **kwargs):
        original(self, *args, opener=opener, **kwargs)

    monkeypatch.setattr(_Handoff, "__init__", injected)

    async def exercise():
        service = load_fake()
        service.transport.commands["authenticateMcpServer"] = {
            "status": "started",
            "authorizationUrl": "https://auth.test/secret",
        }
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test() as pilot:
            await settle(app, pilot)
            run(SlashContext(app, app.screen, None, None), "/connectors")
            await settle(app, pilot)
            await pilot.press("enter")
            await settle(app, pilot)
            detail = app.screen
            await pilot.press("s")
            await settle(app, pilot)
            await pilot.press("escape")
            assert not calls(service, "authenticateMcpServer")
            await pilot.press("s")
            await settle(app, pilot)
            # Do not await all workers while the handoff is pending.
            await pilot.click("#confirm")
            for _ in range(8):
                await pilot.pause()
                if isinstance(app.screen, _Handoff):
                    break
            assert isinstance(app.screen, _Handoff)
            handoff = app.screen
            opener.assert_called_once_with("https://auth.test/secret")
            app.post_message(ServiceEvent(Other("mcp-auth", {"serverId": "other"})))
            await pilot.pause()
            assert app.screen is handoff
            app.post_message(
                ServiceEvent(
                    Other(
                        "mcp-auth",
                        {
                            "serverId": "demo-connector",
                            "outcome": "cancelled",
                            "failureDetail": "Provider refused",
                        },
                    )
                )
            )
            await settle(app, pilot)
            assert app.screen is detail
            notice.assert_called_with(
                "Provider refused", severity="error", markup=False
            )
            service.transport.commands["authenticateMcpServer"] = {
                "status": "already_authenticated"
            }
            await pilot.press("s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert app.screen is detail
            notice.assert_called_with(
                "This account is already signed in.", markup=False
            )

    asyncio.run(exercise())


def test_worker_error_and_empty_clear(monkeypatch):
    async def exercise():
        service = load_fake()
        service.transport.commands["getMcpState"] = {"servers": []}
        service.transport.rpcs["ClearGrokBotConnectorAlwaysAllow"] = ValueError(
            "Failed\x1b[31m[bold]"
        )
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test() as pilot:
            await settle(app, pilot)
            run(SlashContext(app, app.screen, None, None), "/connectors")
            await settle(app, pilot)
            await pilot.press("A")
            await settle(app, pilot)
            await accept(app, pilot)
            args, kwargs = notice.call_args
            assert "\x1b" not in args[0] and kwargs == {
                "severity": "error",
                "markup": False,
            }
            assert "Nothing here" in str(
                app.screen.query_one("#panel-rows", Static).render()
            )

    asyncio.run(exercise())
