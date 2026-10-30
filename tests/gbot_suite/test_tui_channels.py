import asyncio
import json
from unittest.mock import Mock

import pytest
from textual.widgets import Static
from tui_snapshots import assert_snapshot

from gbot.service import channels as c
from gbot.service.fake import load_fake
from gbot.service.handoff import HandoffResult, wait_until
from gbot.tui.app import GbotApp
from gbot.tui.panels.kit import ListPanel
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.handoff import HandoffScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, commands, run
from gbot.tui.slash.channels import SlackPanel, SmsPanel
from groken.client import ConnectError


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


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))


def test_fields_actions_snapshots():
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            assert run(ctx, "/slack") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, SlackPanel)
            assert {a.key for a in panel.detail.actions} == {"c", "i", "g"}
            await assert_snapshot(app, pilot, "panel-slack")
            panel.loaded(
                c.SlackState("connected", "Workspace", (), True, True, True, True)
            )
            assert {a.key for a in panel.detail.actions} == {"c", "i", "r", "x", "g"}
            for sentence in ("manifest", "admin", "unreachable", "removed"):
                assert sentence in panel.detail.body
            panel.loaded(c.SlackState("unsupported_harness"))
            assert [a.key for a in panel.detail.actions] == ["g"]
            await pilot.press("escape")
            assert run(ctx, "/listeners") is None
            await settle(app, pilot)
            assert isinstance(app.screen, ListPanel) and len(app.screen.rows) == 6
            await assert_snapshot(app, pilot, "panel-listeners")
            await pilot.press("escape")
            assert run(ctx, "/sms") is None
            await settle(app, pilot)
            assert isinstance(app.screen, SmsPanel)
            assert [a.key for a in app.screen.detail.actions] == ["l", "g"]
            app.screen.loaded(
                c.MessagingLink(False, "Texting is not available yet."), ()
            )
            assert not app.screen.detail.actions
            assert app.screen.detail.body == "Texting is not available yet."
            specs = {s.name: s for s in commands()}
            assert specs["slack"].needs_bot and specs["slack"].scope == "session"
            assert specs["sms"].scope == specs["listeners"].scope == "any"

    asyncio.run(exercise())


@pytest.mark.parametrize("readonly", [False, True])
def test_confirm_cancel_and_readonly(monkeypatch, readonly):
    async def exercise():
        service = load_fake()
        service.transport.rpcs[c.RPCS[0]] = {
            "status": "connected",
            "workspaceName": "Workspace",
        }
        service.transport.rpcs[c.RPCS[7]] = {
            "phones": [{"handleId": "h", "address": "phone"}]
        }
        app = GbotApp(service, animate=False, read_only=readonly)
        notices = []
        monkeypatch.setattr(
            app, "notify", lambda text, **kw: notices.append((text, kw))
        )
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            for command, keys in (
                ("slack", ("c", "i", "r", "x")),
                ("sms", ("l", "x")),
                ("listeners", ("c",)),
            ):
                assert run(ctx, "/" + command) is None
                await settle(app, pilot)
                panel = app.screen
                if command == "slack":
                    assert isinstance(panel, SlackPanel)
                    panel.loaded(
                        c.SlackState(
                            "connected", "Workspace", (), removed_in_slack=True
                        )
                    )
                calls = list(service.transport.calls)
                for key in keys:
                    await pilot.press(key)
                    await settle(app, pilot)
                    if readonly:
                        assert app.screen is panel
                        assert notices[-1][0] == "Read-only mode"
                    else:
                        assert isinstance(app.screen, ConfirmScreen)
                        assert app.screen.focused is not None
                        assert app.screen.focused.id == "cancel"
                        await pilot.press("enter")
                        await settle(app, pilot)
                        assert app.screen is panel
                    assert service.transport.calls == calls
                await pilot.press("escape")

    asyncio.run(exercise())


@pytest.mark.parametrize("verb", ["c", "i", "r"])
def test_slack_handoff(monkeypatch, verb):
    from test_handoff import FakeClock, FakeEvent

    opener = Mock(return_value=True)

    def screen(title, url, check):
        return HandoffScreen(title, url, check, opener=opener)

    monkeypatch.setattr("gbot.tui.slash.channels.HandoffScreen", screen)

    async def exercise():
        service = load_fake()
        service.transport.rpcs[c.RPCS[0]] = {
            "status": "not_connected" if verb == "i" else "app_created",
            "workspaces": [{"slackTeamId": "team"}],
        }
        method = {"c": c.RPCS[1], "i": c.RPCS[2], "r": c.RPCS[3]}[verb]

        def mutate(payload):
            return {
                "outcome": "started"
                if verb == "c"
                else "installed"
                if verb == "i"
                else "updated",
                "oauthAuthorizeUrl": "https://example.test/slack",
            }

        def fake_wait(check, **kwargs):
            opener.assert_called_once_with("https://example.test/slack")
            clock = FakeClock()
            cancel = FakeEvent(clock)

            def change():
                service.transport.rpcs[c.RPCS[0]] = {
                    "status": "connected",
                    "workspaceName": "New workspace",
                }

            cancel.on_wait = change
            result = wait_until(check, cancel=cancel, wake=None, clock=clock)
            assert clock() == 1
            return result

        monkeypatch.setattr("gbot.tui.screens.handoff.wait_until", fake_wait)
        service.transport.rpcs[method] = mutate
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            run(ctx, "/slack")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, SlackPanel)
            await pilot.press(verb)
            await settle(app, pilot)
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.click("#confirm")
            await settle(app, pilot)
            assert app.screen is panel and panel.state is not None
            assert panel.state.status == "connected"
            assert panel.state.workspace_name == "New workspace"
            opener.assert_called_once_with("https://example.test/slack")

    asyncio.run(exercise())


def test_workspace_choice_and_uninstall(monkeypatch):
    async def exercise():
        service = load_fake()
        service.transport.rpcs[c.RPCS[0]] = {
            "status": "not_connected",
            "workspaces": [
                {"slackTeamId": "first", "slackTeamName": "First"},
                {"slackTeamId": "second", "slackTeamName": "Second"},
            ],
        }
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            run(ctx, "/slack")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, SlackPanel)
            await pilot.press("i")
            await settle(app, pilot)
            assert isinstance(app.screen, ListPanel)
            await pilot.press("down", "enter")
            await settle(app, pilot)
            assert isinstance(app.screen, ConfirmScreen)
            assert app.screen.heading == "Connect Helper to Slack? Your browser opens."
            await pilot.click("#confirm")
            await settle(app, pilot)
            assert (
                "rpc",
                c.RPCS[2],
                {
                    "agentId": "demo-helper",
                    "replaceExistingApp": False,
                    "approvalRequestResubmitted": False,
                    "slackTeamId": "second",
                },
            ) in service.transport.calls
            panel.loaded(c.SlackState("connected", "Second"))
            await pilot.press("x")
            await settle(app, pilot)
            assert isinstance(app.screen, ConfirmScreen)
            assert app.screen.heading == "Remove Helper's Slack app from Second?"
            # Switching to read-only after opening a confirmation still refuses.
            app.read_only = True
            await pilot.click("#confirm")
            await settle(app, pilot)
            assert not any(name == c.RPCS[4] for _, name, _ in service.transport.calls)
            app.read_only = False
            await pilot.press("x")
            await settle(app, pilot)
            await pilot.click("#confirm")
            await settle(app, pilot)
            assert any(name == c.RPCS[4] for _, name, _ in service.transport.calls)

    asyncio.run(exercise())


def test_cancel_handoff_leaves_state(monkeypatch):
    opener = Mock(return_value=True)
    monkeypatch.setattr(
        "gbot.tui.slash.channels.HandoffScreen",
        lambda title, url, check: HandoffScreen(title, url, check, opener=opener),
    )

    async def exercise():
        service = load_fake()
        service.transport.rpcs[c.RPCS[1]] = {
            "outcome": "started",
            "url": "https://example.test/slack",
        }
        app = GbotApp(service, animate=False)
        async with app.run_test() as pilot:
            ctx = await session(app, pilot)
            run(ctx, "/slack")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, SlackPanel)
            before = panel.state
            await pilot.press("c")
            await settle(app, pilot)
            await pilot.click("#confirm")
            await pilot.pause()
            assert isinstance(app.screen, HandoffScreen)
            await pilot.press("escape")
            await settle(app, pilot)
            assert app.screen is panel and panel.state == before

    asyncio.run(exercise())


@pytest.mark.parametrize("timeout", [False, True])
def test_listener_handoff(monkeypatch, timeout):
    from gbot.tui.slash.channels import _ListenerHandoff

    opener = Mock(return_value=True)
    monkeypatch.setattr(
        "gbot.tui.slash.channels._ListenerHandoff",
        lambda *a: _ListenerHandoff(*a, timeout_s=0, opener=opener),
    )

    async def exercise():
        service = load_fake()

        def connect(payload):
            if not timeout:
                service.transport.commands["getListenerIntegrations"] = {
                    "integrations": [
                        {
                            "platform": "azure-devops",
                            "isConnected": True,
                            "state": "listening",
                        }
                    ]
                }
            return {"url": "https://example.test/listener"}

        service.transport.commands["getListenerConnectUrl"] = connect
        app = GbotApp(service, animate=False)
        notices = []
        monkeypatch.setattr(app, "notify", lambda text, **kw: notices.append(text))
        async with app.run_test() as pilot:
            ctx = await session(app, pilot)
            run(ctx, "/listeners")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, ListPanel)
            await pilot.press("c")
            await settle(app, pilot)
            await pilot.click("#confirm")
            await settle(app, pilot)
            opener.assert_called_once_with("https://example.test/listener")
            if timeout:
                assert c.CALLBACK_HINT in str(
                    app.screen.query_one("#handoff-status", Static).render()
                )
                assert notices[-1] == c.CALLBACK_HINT
                await pilot.press("escape")
            else:
                assert app.screen is panel and "True" in panel.rows[0].detail

    asyncio.run(exercise())


def test_sms_issue_unlink_error_and_unavailable(monkeypatch):
    async def exercise():
        service = load_fake()
        service.transport.rpcs[c.RPCS[7]] = {
            "phones": [{"handleId": "h", "address": "phone"}]
        }
        app = GbotApp(service, animate=False)
        notices = []
        monkeypatch.setattr(
            app, "notify", lambda text, **kw: notices.append((text, kw))
        )
        async with app.run_test() as pilot:
            ctx = await session(app, pilot)
            run(ctx, "/sms")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, SmsPanel)
            for key in ("l", "x"):
                await pilot.press(key)
                await settle(app, pilot)
                await pilot.click("#confirm")
                await settle(app, pilot)
                assert app.screen is panel
                if key == "l":
                    assert (
                        "Link DEMO" in panel.detail.body and "sms:" in panel.detail.body
                    )
            assert ("rpc", c.RPCS[8], {"handleId": "h"}) in service.transport.calls
            service.transport.rpcs[c.RPCS[6]] = ValueError("Failed\x1b[31m[bold]")
            await pilot.press("l")
            await settle(app, pilot)
            await pilot.click("#confirm")
            await settle(app, pilot)
            assert "\x1b" not in notices[-1][0]
            assert notices[-1][1] == {"severity": "error", "markup": False}
            service.transport.rpcs[c.RPCS[5]] = ConnectError(
                403,
                json.dumps(
                    {"code": "permission_denied", "message": "Not available yet."}
                ),
            )
            await pilot.press("g")
            await settle(app, pilot)
            assert (
                panel.detail.body == "Not available yet." and not panel.detail.actions
            )

    asyncio.run(exercise())


def test_checks_fake_clock(monkeypatch):
    # Exercise the actual shared wait loop with an injected condition clock.
    from test_handoff import FakeClock, FakeEvent

    fake = load_fake().transport
    clock = FakeClock()
    cancel = FakeEvent(clock)
    before = c.slack_state(fake, "b")

    def change():
        fake.rpcs[c.RPCS[0]] = {"status": "connected"}

    cancel.on_wait = change
    assert (
        wait_until(
            c.slack_check(fake, "b", before), cancel=cancel, wake=None, clock=clock
        ).status
        == "done"
    )
    assert clock() == 1
    assert HandoffResult("cancelled").value is None
