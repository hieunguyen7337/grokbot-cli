import asyncio
from unittest.mock import Mock

from textual.widgets import Input
from tui_snapshots import assert_snapshot

from gbot.service import account
from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.panels.kit import DetailPanel, ListPanel
from gbot.tui.screens.home import HomeScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, commands, run
from groken.client import ConnectError

SECRET_CARD = "tui-vault-card-secret"
SECRET_SESSION = "tui-session-secret"
TEACH = "Teach recording runs in the Grok Bot desktop app."


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


def calls(service, rpc):
    return [payload for _, name, payload in service.transport.calls if name == rpc]


def detail_panel(app) -> DetailPanel:
    assert isinstance(app.screen, DetailPanel)
    return app.screen


def test_analytics_panel_and_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            assert run(ctx, "/analytics") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, DetailPanel)
            assert panel.heading == "Helper analytics"
            assert panel.detail.fields == (
                ("Weekly active users", "2"),
                ("Minutes saved", "65.5"),
            )
            body = panel.detail.body
            assert sum(line.startswith("2026-10-") for line in body.splitlines()) == 7
            assert body.splitlines()[1].startswith("2026-10-31: active 1, turns 4")
            assert "Ada: turns 22" in body and "Grace (external): turns 9" in body
            assert [action.key for action in panel.detail.actions] == ["g"]
            await assert_snapshot(app, pilot, "panel-analytics")

    asyncio.run(exercise())


def test_analytics_states_and_reload(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            service.transport.rpcs["GetGrokBotAgentAnalytics"] = ConnectError(
                404, '{"code":"not_found"}'
            )
            run(ctx, "/analytics")
            await settle(app, pilot)
            assert detail_panel(app).detail.body == "No analytics yet."
            assert detail_panel(app).detail.fields == ()
            service.transport.rpcs["GetGrokBotAgentAnalytics"] = ConnectError(
                403, '{"code":"permission_denied","message":"Owners only."}'
            )
            await pilot.press("g")
            await settle(app, pilot)
            assert detail_panel(app).detail.body == "Owners only."
            service.transport.rpcs["GetGrokBotAgentAnalytics"] = {
                "weeklyActiveUsers": 1,
                "totalMinutesSaved": 9,
                "minutesSavedMeasured": False,
                "days": [],
            }
            await pilot.press("g")
            await settle(app, pilot)
            assert detail_panel(app).detail.fields == (
                ("Weekly active users", "1"),
                ("Minutes saved", "Not measured"),
            )
            assert "No daily activity yet." in detail_panel(app).detail.body
            assert len(calls(service, "GetGrokBotAgentAnalytics")) == 3
            assert calls(service, "GetGrokBotAgentAnalytics")[-1] == {
                "agentId": "demo-helper"
            }

    asyncio.run(exercise())


def test_egress_open_restricted_and_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/egress")
            await settle(app, pilot)
            assert detail_panel(app).heading == "Network egress"
            assert detail_panel(app).detail.fields == (("Mode", "Restricted"),)
            assert "example.com" in detail_panel(app).detail.body
            assert "203.0.113.0/24 port 443" in detail_panel(app).detail.body
            service.transport.rpcs["GetGrokBotEgressPolicy"] = {}
            await pilot.press("g")
            await settle(app, pilot)
            assert detail_panel(app).detail.fields == (("Mode", "Open"),)
            assert detail_panel(app).detail.body == (
                "No outbound network restriction is set."
            )
            service.transport.rpcs["GetGrokBotEgressPolicy"] = ConnectError(
                400,
                '{"code":"failed_precondition","message":"Egress is not set up."}',
            )
            await pilot.press("g")
            await settle(app, pilot)
            assert detail_panel(app).detail.body == "Egress is not set up."
            assert [a.key for a in detail_panel(app).detail.actions] == ["g"]

    asyncio.run(exercise())


def test_payment_label_sentence_and_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["GetGrokBotDefaultPaymentMethod"] = {
            "method": {"vaultCardId": SECRET_CARD}
        }
        service.transport.rpcs["ListGrokBotStripeLinkPaymentMethods"] = {
            "outcome": 1,
            "paymentMethods": [{"id": SECRET_CARD, "brand": "Visa", "last4": "4242"}],
        }
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/payment")
            await settle(app, pilot)
            assert detail_panel(app).detail.fields == (
                ("Default payment method", "Visa ending 4242"),
            )
            assert detail_panel(app).detail.body == (
                "Change the default payment method in the Grok Bot app."
            )
            assert SECRET_CARD not in app.export_screenshot()
            service.transport.rpcs["GetGrokBotDefaultPaymentMethod"] = {}
            await pilot.press("g")
            await settle(app, pilot)
            assert detail_panel(app).detail.fields == (
                ("Default payment method", "No default payment method."),
            )

    asyncio.run(exercise())


def test_address_lookup_resolves_the_selected_suggestion(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr(account, "new_session_token", lambda: SECRET_SESSION)

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            assert run(ctx, "/address") is None
            await settle(app, pilot)
            app.screen.query_one("#form-0", Input).value = "1 example"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert isinstance(app.screen, ListPanel)
            assert [row.label for row in app.screen.rows] == [
                "1 Example Street",
                "2 Example Avenue",
            ]
            await pilot.press("down", "enter")
            await settle(app, pilot)
            assert isinstance(app.screen, DetailPanel)
            assert ("City", "Springfield") in detail_panel(app).detail.fields
            assert detail_panel(app).detail.body == (
                "1 Example Street, Springfield, IL 62701, United States"
            )
            assert calls(service, "SuggestGrokBotAddresses") == [
                {"query": "1 example", "sessionToken": SECRET_SESSION}
            ]
            assert calls(service, "ResolveGrokBotAddress") == [
                {"id": "demo-address-2", "sessionToken": SECRET_SESSION}
            ]
            assert SECRET_SESSION not in app.export_screenshot()

    asyncio.run(exercise())


def test_address_empty_and_failed_lookups_are_one_sentence(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["SuggestGrokBotAddresses"] = ConnectError(500, "boom")
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/address")
            await settle(app, pilot)
            app.screen.query_one("#form-0", Input).value = "main"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert isinstance(app.screen, ListPanel)
            assert app.screen.rows == []
            assert app.screen.empty == "Address suggestions are unavailable."

    asyncio.run(exercise())


def test_address_resolve_refusal_is_a_notice(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["ResolveGrokBotAddress"] = ConnectError(
            403, '{"code":"permission_denied","message":"Sign in again."}'
        )
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/address")
            await settle(app, pilot)
            app.screen.query_one("#form-0", Input).value = "1 example"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await pilot.press("enter")
            await settle(app, pilot)
            assert isinstance(app.screen, ListPanel)
            assert notice.call_args.args[0] == "Sign in again."
            assert notice.call_args.kwargs == {"markup": False}

    asyncio.run(exercise())


def test_teach_is_a_notice_and_session_only(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            assert run(ctx, "/teach") is None
            assert notice.call_args.args == (TEACH,)
            assert notice.call_args.kwargs == {"markup": False}
            home = SlashContext(app, app.home, None, None)
            assert isinstance(app.home, HomeScreen)
            assert run(home, "/teach") == "/teach works in a session"

    asyncio.run(exercise())


def test_reads_work_in_read_only_mode_and_commands_are_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            app.read_only = True
            run(ctx, "/egress")
            await settle(app, pilot)
            assert detail_panel(app).detail.fields == (("Mode", "Restricted"),)
            specs = {c.name: c for c in commands()}
            assert specs["analytics"].scope == "session"
            assert specs["analytics"].needs_bot
            assert specs["egress"].scope == "any"
            assert specs["payment"].scope == "any"
            assert specs["address"].scope == "any"
            assert specs["teach"].scope == "session"

    asyncio.run(exercise())
