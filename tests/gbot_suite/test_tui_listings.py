import asyncio
from unittest.mock import Mock

from textual.widgets import Static
from tui_snapshots import assert_snapshot

from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.panels.kit import ListPanel
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, commands, run
from gbot.tui.slash.listings import PluginListingPanel, SkillPublishPanel
from groken.client import ConnectError

TEMPORAL = '{"error":"publishSkill is not supported for Temporal agents"}'


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


async def cancel(app, pilot):
    await pilot.pause()
    assert isinstance(app.screen, ConfirmScreen)
    await pilot.press("enter")
    await settle(app, pilot)


def calls(service, name):
    return [args for _, call, args in service.transport.calls if call == name]


def keys(panel):
    return [key for key, _, _ in panel.keys(panel.selected())]


def footer(panel):
    return str(panel.query_one(".panel-footer", Static).render())


def test_commands_and_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            assert run(ctx, "/skill-publish") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, SkillPublishPanel)
            assert [row.label for row in panel.visible_rows] == [
                "Meeting notes",
                "Morning brief",
            ]
            assert [row.detail for row in panel.visible_rows] == [
                "demo-notes",
                "demo-brief",
            ]
            assert panel.header == "Targets: Demo team"
            assert keys(panel) == ["p", "r", "u", "g"]
            assert "p Publish" in footer(panel)
            await assert_snapshot(app, pilot, "panel-skill-publish")
            specs = {c.name: c for c in commands()}
            for name in ("skill-publish", "plugin-listing"):
                assert specs[name].scope == "session" and specs[name].needs_bot

    asyncio.run(exercise())


def test_header_and_keys_without_targets(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.commands["getSkillPublishTargets"] = {
            "teams": [],
            "unavailableReason": "Join a team to publish skills.",
            "unavailableReasonKind": "no_team",
        }
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/skill-publish")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, SkillPublishPanel)
            assert panel.header == "Join a team to publish skills."
            assert keys(panel) == ["r", "u", "g"]
            assert "p Publish" not in footer(panel)
            before = len(service.transport.calls)
            await pilot.press("p")
            await settle(app, pilot)
            assert app.screen is panel and len(service.transport.calls) == before
            # A refused targets read still lists the skills, with the sentence as the header.
            service.transport.commands["getSkillPublishTargets"] = ConnectError(
                403, '{"code":"permission_denied","message":"Teams only."}'
            )
            await pilot.press("g")
            await settle(app, pilot)
            assert panel.header == "Teams only."
            assert len(panel.visible_rows) == 2
            # No skills of your own: one plain sentence, only reload.
            service.transport.commands["getAgentWorkflows"] = []
            await pilot.press("g")
            await settle(app, pilot)
            assert not panel.visible_rows and keys(panel) == ["g"]
            assert "No skills of your own to publish" in str(
                panel.query_one("#panel-rows", Static).render()
            )

    asyncio.run(exercise())


def test_publish_resync_unpublish_confirms(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/skill-publish")
            await settle(app, pilot)
            panel = app.screen
            for key, title, name, payload in [
                (
                    "p",
                    "Publish Meeting notes to Demo team?",
                    "publishSkill",
                    {"workflowId": "demo-notes", "teamId": "demo-team"},
                ),
                (
                    "r",
                    "Resync Meeting notes?",
                    "resyncPublishedSkill",
                    {"workflowId": "demo-notes"},
                ),
                (
                    "u",
                    "Unpublish Meeting notes?",
                    "unpublishSkill",
                    {"workflowId": "demo-notes"},
                ),
            ]:
                await pilot.press(key)
                await pilot.pause()
                assert isinstance(app.screen, ConfirmScreen)
                assert app.screen.heading == title
                assert "Helper" in app.screen.details
                assert app.screen.focused is not None
                assert app.screen.focused.id == "cancel"
                await cancel(app, pilot)
                assert not calls(service, name)
                await pilot.press(key)
                await accept(app, pilot)
                assert calls(service, name) == [payload]
                assert app.screen is panel
            assert notice.call_args.args[0] == "unpublished"
            assert notice.call_args.kwargs == {"markup": False}
            # The panel reloaded after the write.
            assert len(calls(service, "getSkillPublishTargets")) == 4

    asyncio.run(exercise())


def test_several_targets_choose_one(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.commands["getSkillPublishTargets"] = {
            "teams": [
                {"teamId": "t1", "name": "One"},
                {"teamId": "t2", "name": "Two"},
            ]
        }
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/skill-publish")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, SkillPublishPanel)
            assert panel.header == "Targets: One, Two"
            await pilot.press("p")
            await settle(app, pilot)
            chooser = app.screen
            assert isinstance(chooser, ListPanel) and chooser is not panel
            assert [row.label for row in chooser.visible_rows] == ["One", "Two"]
            await pilot.press("down", "enter")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            assert app.screen.heading == "Publish Meeting notes to Two?"
            await accept(app, pilot)
            assert calls(service, "publishSkill") == [
                {"workflowId": "demo-notes", "teamId": "t2"}
            ]

    asyncio.run(exercise())


def test_refusals_errors_and_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/skill-publish")
            await settle(app, pilot)
            panel = app.screen
            service.transport.commands["resyncPublishedSkill"] = ConnectError(
                400, TEMPORAL
            )
            await pilot.press("r")
            await accept(app, pilot)
            assert "not supported for Temporal agents" in notice.call_args.args[0]
            assert notice.call_args.kwargs["severity"] == "warning"
            service.transport.commands["unpublishSkill"] = ValueError("bad\x1b[2J[b]")
            await pilot.press("u")
            await accept(app, pilot)
            assert "\x1b" not in notice.call_args.args[0]
            assert notice.call_args.kwargs == {"severity": "error", "markup": False}
            service.transport.commands["publishSkill"] = {"error": "No description."}
            await pilot.press("p")
            await accept(app, pilot)
            assert notice.call_args.args[0] == "No description."
            assert app.screen is panel
            app.read_only = True
            before = len(service.transport.calls)
            for press in ("p", "r", "u"):
                await pilot.press(press)
                await settle(app, pilot)
                assert notice.call_args.args[0] == "Read-only mode"
                assert app.screen is panel
            assert len(service.transport.calls) == before

    asyncio.run(exercise())


def test_plugin_listing(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/plugin-listing")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, PluginListingPanel)
            assert [(r.label, r.detail) for r in panel.visible_rows] == [
                ("Notes", "12")
            ]
            assert keys(panel) == ["u", "g"]
            for restorable, title in [
                (True, "Remove the Notes listing? A private copy stays."),
                (False, "Remove the Notes listing? No private copy remains."),
            ]:
                service.transport.commands["hasRestorablePluginListingCopy"] = (
                    restorable
                )
                service.transport.calls.clear()
                await pilot.press("u")
                await settle(app, pilot)
                assert isinstance(app.screen, ConfirmScreen)
                assert app.screen.heading == title
                assert app.screen.focused is not None
                assert app.screen.focused.id == "cancel"
                # The read comes first and nothing is removed before the confirm.
                assert calls(service, "hasRestorablePluginListingCopy") == [
                    {"pluginId": "12"}
                ]
                assert not calls(service, "unpublishPluginListing")
                await cancel(app, pilot)
                assert not calls(service, "unpublishPluginListing")
                await pilot.press("u")
                await settle(app, pilot)
                await accept(app, pilot)
                assert calls(service, "unpublishPluginListing") == [{"pluginId": "12"}]
            service.transport.commands["hasRestorablePluginListingCopy"] = ConnectError(
                400, TEMPORAL
            )
            await pilot.press("u")
            await settle(app, pilot)
            assert app.screen is panel
            assert "not supported for Temporal agents" in notice.call_args.args[0]
            service.transport.commands["hasRestorablePluginListingCopy"] = True
            service.transport.commands["unpublishPluginListing"] = ConnectError(
                403, '{"code":"permission_denied","message":"Not yours."}'
            )
            await pilot.press("u")
            await settle(app, pilot)
            await accept(app, pilot)
            assert notice.call_args.args[0] == "Not yours."
            app.read_only = True
            before = len(service.transport.calls)
            await pilot.press("u")
            await settle(app, pilot)
            assert notice.call_args.args[0] == "Read-only mode"
            assert app.screen is panel and len(service.transport.calls) == before

    asyncio.run(exercise())
