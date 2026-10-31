import asyncio
from unittest.mock import Mock

from textual.widgets import Input, Select, Switch
from tui_snapshots import assert_snapshot

from gbot.service import sandbox
from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, commands, run
from gbot.tui.slash.avatar_voice import _Form
from gbot.tui.slash.sandbox import SandboxPanel, SettingsPanel
from groken.client import ConnectError


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


def calls(svc, rpc):
    return [payload for _, name, payload in svc.transport.calls if name == rpc]


def zones(monkeypatch):
    # Pin the zone list so validation does not depend on the machine's tzdata.
    monkeypatch.setattr(
        sandbox.zoneinfo, "available_timezones", lambda: {"UTC", "Europe/Paris"}
    )


def test_sandbox_panel_snapshot_and_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        svc = load_fake()
        app = GbotApp(svc, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            assert run(ctx, "/sandbox") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, SandboxPanel)
            fields = dict(panel.detail.fields)
            assert fields["State"] == "running"
            assert fields["Update available"] == "yes"
            assert fields["Upgrade"] == "scheduled"
            assert fields["Recurring"] == "yes"
            assert fields["Next run"] == "2027-01-16 07:56 UTC"
            assert {a.key for a in panel.detail.actions} == {"r", "f", "s", "c", "g"}
            await assert_snapshot(app, pilot, "panel-sandbox")

    asyncio.run(exercise())


def test_actions_and_notices_follow_the_state(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        svc = load_fake()
        svc.transport.rpcs["GetSandBoxUpgradeSchedule"] = {}
        app = GbotApp(svc, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/sandbox")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, SandboxPanel)
            assert {a.key for a in panel.detail.actions} == {"r", "f", "s", "g"}
            assert ("Upgrade", "none scheduled") in panel.detail.fields
            svc.transport.rpcs["GetSandBoxUpgradeSchedule"] = ConnectError(
                400,
                '{"code":"invalid_argument","message":"Pick a schedule first."}',
            )
            await pilot.press("g")
            await settle(app, pilot)
            assert panel.detail.body == "Pick a schedule first."

    asyncio.run(exercise())


def test_recreate_force_schedule_and_cancel(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    zones(monkeypatch)

    async def exercise():
        svc = load_fake()
        app = GbotApp(svc, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/sandbox")
            await settle(app, pilot)

            # Keep data: one confirmation, Cancel focused, then the recreate.
            await pilot.press("r")
            assert isinstance(app.screen, _Form)
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert isinstance(app.screen, ConfirmScreen)
            assert (
                app.screen.heading == "Recreate the cloud computer? Your data is kept."
            )
            await pilot.press("enter")
            await settle(app, pilot)
            assert not calls(svc, "RecreateSandBox")
            await pilot.press("r")
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(svc, "RecreateSandBox")[-1] == {
                "preserveData": True,
                "force": False,
                "acknowledgeTerminalUpgradeSchedule": False,
            }
            assert notice.call_args.args[0].startswith("Started: yes")

            # Discard data: the word recreate is required before any confirmation.
            await pilot.press("r")
            app.screen.query_one("#form-0", Select).value = "Discard data"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert isinstance(app.screen, _Form)
            assert not any(
                payload["preserveData"] is False
                for payload in calls(svc, "RecreateSandBox")
            )
            app.screen.query_one("#form-1", Input).value = "recreate"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(svc, "RecreateSandBox")[-1]["preserveData"] is False

            # Force recreate: the typed word, then a confirmation.
            await pilot.press("f")
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert isinstance(app.screen, _Form)
            assert not calls(svc, "ForceRecreateSandBox")
            app.screen.query_one("#form-0", Input).value = "recreate"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(svc, "ForceRecreateSandBox") == [{}]

            # Reschedule: validation happens in the form before the confirmation.
            await pilot.press("s")
            assert isinstance(app.screen, _Form)
            app.screen.query_one("#form-0", Input).value = "25:00"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert isinstance(app.screen, _Form)
            assert not calls(svc, "RescheduleSandBoxUpgrade")
            app.screen.query_one("#form-0", Input).value = "04:15"
            app.screen.query_one("#form-1", Input).value = "Mars/Olympus"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert not calls(svc, "RescheduleSandBoxUpgrade")
            app.screen.query_one("#form-1", Input).value = "UTC"
            app.screen.query_one("#form-2", Switch).value = False
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(svc, "RescheduleSandBoxUpgrade")[-1] == {
                "timezone": "UTC",
                "localTime": "04:15",
                "recurring": False,
            }

            # Cancel the upgrade: confirmed, Cancel focused.
            await pilot.press("c")
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.press("enter")
            await settle(app, pilot)
            assert not calls(svc, "CancelSandBoxUpgrade")
            await pilot.press("c")
            await accept(app, pilot)
            assert calls(svc, "CancelSandBoxUpgrade") == [
                {"dismissTerminalOutcome": False}
            ]

            # A refused recreate is one plain notice, not a crash.
            svc.transport.rpcs["RecreateSandBox"] = ConnectError(
                403, '{"code":"permission_denied","message":"Not allowed here."}'
            )
            await pilot.press("r")
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert notice.call_args.args[0] == "Not allowed here."
            assert notice.call_args.kwargs == {"severity": "warning", "markup": False}

    asyncio.run(exercise())


def test_sandbox_read_only_refuses_every_change(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        svc = load_fake()
        app = GbotApp(svc, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/sandbox")
            await settle(app, pilot)
            app.read_only = True
            before = len(svc.transport.calls)
            panel = app.screen
            for key in ("r", "f", "s", "c"):
                await pilot.press(key)
                assert notice.call_args.args[0] == "Read-only mode"
                assert app.screen is panel
            assert len(svc.transport.calls) == before

    asyncio.run(exercise())


def test_runtime_pin_and_auto_review_with_a_faithful_fake(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        svc = load_fake()
        state = {
            "pinnedAgents": {"agentIds": ["demo-helper"]},
            "autoReviewInstructions": {
                "isEnabled": False,
                "allowInstructions": ["allow this"],
                "blockInstructions": ["never this"],
            },
            "hasSeenOnboarding": True,
            "mainAgentId": "demo-helper",
        }

        def update(args):
            # Write like the server: the reply carries every field, not only the changed one.
            state.update(args)
            return {"settings": dict(state)}

        svc.transport.rpcs["GetGrokBotUserRuntimeSettings"] = lambda args: {
            "settings": dict(state)
        }
        svc.transport.rpcs["UpdateGrokBotUserRuntimeSettings"] = update
        app = GbotApp(svc, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            assert run(ctx, "/runtime") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, SettingsPanel)
            fields = dict(panel.detail.fields)
            assert fields["Pinned bots"] == "Helper"
            assert fields["Auto-review"] == "off"
            assert fields["Main bot"] == "Helper"
            assert {a.key for a in panel.detail.actions} == {"p", "a", "g"}

            await pilot.press("p")
            assert isinstance(app.screen, ConfirmScreen)
            assert app.screen.heading == "Unpin Helper?"
            await pilot.press("enter")
            await settle(app, pilot)
            assert not calls(svc, "UpdateGrokBotUserRuntimeSettings")
            await pilot.press("p")
            await accept(app, pilot)
            assert calls(svc, "UpdateGrokBotUserRuntimeSettings")[-1] == {
                "pinnedAgents": {"agentIds": []}
            }
            assert dict(panel.detail.fields)["Pinned bots"] == "none"

            await pilot.press("a")
            assert app.screen.heading == "Turn auto-review on?"
            await accept(app, pilot)
            assert calls(svc, "UpdateGrokBotUserRuntimeSettings")[-1] == {
                "autoReviewInstructions": {
                    "isEnabled": True,
                    "allowInstructions": ["allow this"],
                    "blockInstructions": ["never this"],
                }
            }
            assert dict(panel.detail.fields)["Auto-review"] == "on"

    asyncio.run(exercise())


def test_runtime_picks_a_bot_from_home(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        svc = load_fake()
        svc.transport.rpcs["GetGrokBotUserRuntimeSettings"] = {"settings": {}}
        app = GbotApp(svc, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            ctx = SlashContext(app, app.screen, None, None)
            assert run(ctx, "/runtime") is None
            await settle(app, pilot)
            assert isinstance(app.screen, SettingsPanel)
            first = next(iter(app.state.bots))
            await pilot.press("p")
            assert isinstance(app.screen, _Form)
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(svc, "UpdateGrokBotUserRuntimeSettings") == [
                {"pinnedAgents": {"agentIds": [first]}}
            ]

    asyncio.run(exercise())


def test_runtime_read_refusal_blocks_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        svc = load_fake()
        svc.transport.rpcs["GetGrokBotUserRuntimeSettings"] = ConnectError(
            403, '{"code":"permission_denied","message":"Team bots only."}'
        )
        app = GbotApp(svc, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/runtime")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, SettingsPanel)
            assert panel.detail.body == "Team bots only."
            await pilot.press("a")
            assert notice.call_args.args[0] == "Team bots only."
            assert app.screen is panel
            assert not calls(svc, "UpdateGrokBotUserRuntimeSettings")

    asyncio.run(exercise())


def test_runtime_read_only_refuses_every_change(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        svc = load_fake()
        app = GbotApp(svc, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/runtime")
            await settle(app, pilot)
            app.read_only = True
            before = len(svc.transport.calls)
            for key in ("p", "a"):
                await pilot.press(key)
                assert notice.call_args.args[0] == "Read-only mode"
            assert len(svc.transport.calls) == before

    asyncio.run(exercise())


def test_commands_are_discovered_for_any_scope():
    specs = {c.name: c for c in commands()}
    assert specs["sandbox"].scope == "any" and not specs["sandbox"].needs_bot
    assert specs["runtime"].scope == "any" and not specs["runtime"].needs_bot
