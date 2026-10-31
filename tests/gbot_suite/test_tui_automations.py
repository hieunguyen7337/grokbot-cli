import asyncio
import json

import pytest
from textual.widgets import Input, TextArea
from tui_snapshots import assert_snapshot

from gbot.service import automations as a
from gbot.service.events import Other
from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.panels.kit import FormPanel
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, run
from gbot.tui.slash.automations import AutomationPanel, AutomationsPanel


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def opened(app, pilot):
    await settle(app, pilot)
    screen = SessionScreen("demo-helper", bot_name="Helper")
    await app.push_screen(screen)
    await settle(app, pilot)
    ctx = SlashContext(app, screen, "demo-helper", None)
    assert run(ctx, "/automations") is None
    await settle(app, pilot)
    return ctx


async def confirm(app, pilot, accept=True):
    assert isinstance(app.screen, ConfirmScreen)
    assert app.screen.focused is not None
    assert app.screen.focused.id == "cancel"
    if accept:
        await pilot.click("#confirm")
    else:
        await pilot.press("escape")
    await settle(app, pilot)


def test_list_detail_events_and_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr("gbot.tui.slash.automations.time", lambda: 1_800_000_000)

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await opened(app, pilot)
            panel = app.screen
            assert isinstance(panel, AutomationsPanel)
            assert panel.rows[0].label == "Morning briefing"
            await assert_snapshot(app, pilot, "panel-automations")
            await pilot.press("b")
            await settle(app, pilot)
            assert panel.all_bots and "Helper" in panel.rows[0].detail
            before = len(service.transport.calls)
            service._emit(
                Other("agent-automations-changed", {"agentId": "demo-helper"})
            )
            await settle(app, pilot)
            assert len(service.transport.calls) > before
            await pilot.press("enter")
            await settle(app, pilot)
            detail = app.screen
            assert isinstance(detail, AutomationPanel)
            assert dict(detail.detail.fields)["State"] == "on"
            assert "completed" in detail.detail.body
            assert {label for label, _ in detail.detail.fields} == {
                "Trigger",
                "State",
                "Next run",
                "Last run",
                "Created",
                "Provenance",
            }
            await assert_snapshot(app, pilot, "panel-automation")
            before = len(service.transport.calls)
            service._emit(
                Other("automations", {"agentId": "demo-helper", "automations": []})
            )
            await settle(app, pilot)
            assert len(service.transport.calls) > before

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "key,command",
    [
        ("t", "setAgentAutomationEnabled"),
        ("x", "deleteAgentAutomation"),
        ("R", "runAgentAutomationNow"),
    ],
)
def test_mutations_confirm_and_readonly(tmp_path, monkeypatch, key, command):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()

        def start(args):
            service.transport.commands["getAgentAutomations"] = [
                {
                    **a._DEMO,
                    "runs": [{"id": "new", "status": "running", "startedAt": 10}],
                }
            ]

        service.transport.commands["runAgentAutomationNow"] = start
        app = GbotApp(service, animate=False)
        notices = []
        monkeypatch.setattr(
            app, "notify", lambda text, **kw: notices.append((text, kw))
        )
        async with app.run_test(size=(100, 30)) as pilot:
            await opened(app, pilot)
            await pilot.press("enter")
            await settle(app, pilot)
            app.read_only = True
            for blocked in ("t", "x", "R", "e"):
                await pilot.press(blocked)
                assert notices[-1][0] == "Read-only mode"
            app.read_only = False
            await pilot.press(key)
            await confirm(app, pilot, False)
            assert not any(name == command for _, name, _ in service.transport.calls)
            await pilot.press(key)
            await confirm(app, pilot)
            assert any(name == command for _, name, _ in service.transport.calls)
            if key == "R":
                assert isinstance(app.screen, AutomationPanel)
                assert app.screen.run_status == "running"

    asyncio.run(exercise())


@pytest.mark.parametrize("new", [True, False])
def test_forms(tmp_path, monkeypatch, new):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notices = []
        monkeypatch.setattr(app, "notify", lambda text, **kw: notices.append(text))
        async with app.run_test(size=(100, 30)) as pilot:
            await opened(app, pilot)
            if not new:
                await pilot.press("enter")
                await settle(app, pilot)
            await pilot.press("n" if new else "e")
            await settle(app, pilot)
            form = app.screen
            assert isinstance(form, FormPanel)
            assert [f.label for f in form.fields] == ["Name", "Prompt", "Schedule"]
            form.query_one("#form-0", Input).value = "Changed"
            form.query_one("#form-1", TextArea).load_text("Multiline\nprompt")
            form.query_one("#form-2", Input).value = "@daily"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await confirm(app, pilot, False)
            command = "createAgentAutomation" if new else "updateAgentAutomation"
            assert not any(name == command for _, name, _ in service.transport.calls)
            app.read_only = True
            await pilot.press("ctrl+s")
            assert notices[-1] == "Read-only mode"
            app.read_only = False
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await confirm(app, pilot)
            payload = next(
                args for _, name, args in service.transport.calls if name == command
            )
            spec = payload["spec"]
            assert isinstance(spec, dict)
            assert spec["prompt"] == "Multiline\nprompt"

    asyncio.run(exercise())


def test_permissions_and_noncron(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        row = next(r for r in service.state.rows if r["id"] == "demo-helper")
        row["harness"] = "temporal"
        record = {**a._DEMO, "trigger": {"type": "webhook"}}
        wrapped = {
            "recordJson": json.dumps(record),
            "viewerPermissions": {
                "allowedActions": [
                    "GROK_BOT_AUTOMATION_ACTION_OPEN",
                    "GROK_BOT_AUTOMATION_ACTION_EDIT",
                ]
            },
        }
        service.transport.rpcs["ListGrokBotAgentAutomations"] = {
            "automations": [wrapped]
        }
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await opened(app, pilot)
            await pilot.press("enter")
            await settle(app, pilot)
            assert isinstance(app.screen, AutomationPanel)
            assert {action.key for action in app.screen.detail.actions} == {
                "e",
                "R",
                "r",
            }
            await pilot.press("e")
            await settle(app, pilot)
            assert isinstance(app.screen, FormPanel)
            assert [f.label for f in app.screen.fields] == ["Name", "Prompt"]

    asyncio.run(exercise())
