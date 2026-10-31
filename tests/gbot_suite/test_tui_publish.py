import asyncio
import dataclasses
from unittest.mock import Mock

from textual.widgets import Input, Select
from tui_snapshots import assert_snapshot

from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, commands, run
from gbot.tui.slash.publish import PublishPanel
from groken.client import ConnectError

TEMPLATE = {
    "shareId": "share",
    "name": "Helper Template",
    "description": "A helpful bot",
    "published": True,
    "activeVersion": 2,
    "visibility": "GROK_BOT_TEMPLATE_VISIBILITY_TEAM",
}


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def setup(app, pilot, listing="unpublished"):
    await settle(app, pilot)
    bot = app.state.bots["demo-helper"]
    raw = dict(bot.raw)
    if listing != "unknown":
        raw["publishedAtMs"] = "1799000000000" if listing == "published" else None
    app.state.bots["demo-helper"] = dataclasses.replace(bot, raw=raw)
    screen = SessionScreen("demo-helper", bot_name="Helper")
    await app.push_screen(screen)
    await settle(app, pilot)
    return SlashContext(app, screen, screen.bot_id, None)


async def accept(app, pilot):
    await pilot.pause()
    assert isinstance(app.screen, ConfirmScreen)
    assert app.screen.focused is not None and app.screen.focused.id == "cancel"
    await pilot.click("#confirm")
    await settle(app, pilot)


def calls(service, rpc):
    return [payload for _, name, payload in service.transport.calls if name == rpc]


def make(policy="all", template=TEMPLATE):
    service = load_fake()
    service.transport.commands["getBotTemplateForSourceAgent"] = (
        template if template is not None else {}
    )
    service.transport.commands["getBotTemplateExportPolicy"] = {"exportPolicy": policy}
    return service


def test_panel_snapshot_and_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = make()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            assert run(ctx, "/publish") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, PublishPanel)
            fields = dict(panel.detail.fields)
            assert fields["Marketplace"] == "unpublished"
            assert fields["Template"] == "Helper Template"
            assert fields["Active version"] == "2" and fields["Visibility"] == "team"
            assert {a.key for a in panel.detail.actions} == {"p", "a", "v", "d", "g"}
            await assert_snapshot(app, pilot, "panel-publish")
            specs = {c.name: c for c in commands()}
            assert specs["publish"].scope == "session" and specs["publish"].needs_bot

    asyncio.run(exercise())


def test_keys_follow_state(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def keys(listing, policy, template=TEMPLATE):
        service = make(policy, template)
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot, listing)
            run(ctx, "/publish")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, PublishPanel)
            return {a.key for a in panel.detail.actions}, panel.detail.body

    async def exercise():
        assert (await keys("published", "all"))[0] == {"u", "a", "v", "d", "g"}
        assert (await keys("unknown", "all"))[0] == {"p", "u", "a", "v", "d", "g"}
        found, body = await keys("unpublished", "none")
        assert found == {"p", "g"} and "turned off" in body
        found, body = await keys("unpublished", "all", None)
        assert found == {"p", "g"} and "no template" in body

    asyncio.run(exercise())


def test_team_only_hides_public(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = make("team_only")
        service.transport.rpcs["SetGrokBotTemplateVisibility"] = {"template": TEMPLATE}
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/publish")
            await settle(app, pilot)
            await pilot.press("v")
            await settle(app, pilot)
            select = app.screen.query_one("#form-0", Select)
            assert [v for _, v in select._options if isinstance(v, str)] == ["team"]
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(service, "SetGrokBotTemplateVisibility") == [
                {
                    "shareId": "share",
                    "visibility": "GROK_BOT_TEMPLATE_VISIBILITY_TEAM",
                }
            ]

    asyncio.run(exercise())


def test_listing_confirm_cancel_and_outcome(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = make()
        service.transport.rpcs["PublishGrokBotAgent"] = {"outcome": "NOT_SHARED"}
        service.transport.rpcs["UnpublishGrokBotAgent"] = {"outcome": "UNPUBLISHED"}
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot, "unknown")
            run(ctx, "/publish")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, PublishPanel)
            await pilot.press("p")
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.press("enter")
            await settle(app, pilot)
            assert not calls(service, "PublishGrokBotAgent")
            await pilot.press("p")
            await accept(app, pilot)
            assert calls(service, "PublishGrokBotAgent") == [{"agentId": "demo-helper"}]
            assert dict(panel.detail.fields)["Last result"] == (
                "Share the bot first, then list it in the marketplace."
            )
            await pilot.press("u")
            await accept(app, pilot)
            assert dict(panel.detail.fields)["Marketplace"] == "unpublished"
            assert "taken off" in dict(panel.detail.fields)["Last result"]

    asyncio.run(exercise())


def test_listing_outcome_wins_over_the_roster_row(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = make()
        service.transport.rpcs["PublishGrokBotAgent"] = {"outcome": "PUBLISHED"}
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot, "unpublished")
            run(ctx, "/publish")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, PublishPanel)
            assert dict(panel.detail.fields)["Marketplace"] == "unpublished"
            await pilot.press("p")
            await accept(app, pilot)
            assert dict(panel.detail.fields)["Marketplace"] == "published"

    asyncio.run(exercise())


def test_version_and_delete_typed_name(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = make()
        service.transport.rpcs["ActivateGrokBotTemplateVersion"] = {
            "template": TEMPLATE
        }
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/publish")
            await settle(app, pilot)
            await pilot.press("a")
            await settle(app, pilot)
            field = app.screen.query_one("#form-0", Input)
            assert field.value == "2"
            field.value = "3"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert isinstance(app.screen, ConfirmScreen)
            await accept(app, pilot)
            assert calls(service, "ActivateGrokBotTemplateVersion") == [
                {"shareId": "share", "version": 3}
            ]
            await pilot.press("d")
            await settle(app, pilot)
            app.screen.query_one("#form-0", Input).value = "wrong"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert not isinstance(app.screen, ConfirmScreen)
            assert not calls(service, "DeleteGrokBotTemplate")
            app.screen.query_one("#form-0", Input).value = "Helper Template"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(service, "DeleteGrokBotTemplate") == [{"shareId": "share"}]

    asyncio.run(exercise())


def test_refusal_notice_and_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = make()
        service.transport.rpcs["PublishGrokBotAgent"] = ConnectError(
            403,
            '{"code": "failed_precondition", "message": "Sharing is off\\u001b[2J"}',
        )
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/publish")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, PublishPanel)
            await pilot.press("p")
            await accept(app, pilot)
            assert notice.call_args.kwargs == {"severity": "error", "markup": False}
            assert "Sharing is off" in notice.call_args.args[0]
            assert "\x1b" not in notice.call_args.args[0]
            app.read_only = True
            before = len(service.transport.calls)
            for mutation in (
                panel.list_bot,
                panel.unlist,
                panel.activate,
                panel.visibility,
                panel.delete,
            ):
                mutation()
                assert notice.call_args.args[0] == "Read-only mode"
                assert app.screen is panel
            assert len(service.transport.calls) == before

    asyncio.run(exercise())
