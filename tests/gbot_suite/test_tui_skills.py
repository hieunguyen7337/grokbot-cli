import asyncio

import pytest
from textual.widgets import Input, Static, TextArea
from tui_snapshots import assert_snapshot

from gbot.service.events import Other
from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp, ServiceEvent
from gbot.tui.panels.kit import DetailPanel, FormPanel
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, commands, run
from gbot.tui.slash.skills import _Catalog, _Skills


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
    return [args for _, command, args in service.transport.calls if command == name]


def select(panel, key):
    panel.index = next(i for i, row in enumerate(panel.visible_rows) if row.key == key)
    panel._draw()


async def accept(app, pilot):
    assert isinstance(app.screen, ConfirmScreen)
    assert app.screen.focused is not None
    assert app.screen.focused.id == "cancel"
    await pilot.click("#confirm")
    await settle(app, pilot)


def test_groups_detail_events_and_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            assert run(ctx, "/skills") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, _Skills)
            assert [
                row.label for row in panel.rows if row.key.startswith("heading:")
            ] == ["Yours", "Scheduled", "Managed"]
            await assert_snapshot(app, pilot, "panel-skills")
            select(panel, "demo-notes")
            await pilot.press("enter")
            assert isinstance(app.screen, DetailPanel)
            assert ("Source", "user") in app.screen.detail.fields
            assert "Collect decisions" in app.screen.detail.body
            await pilot.press("escape")
            select(panel, "demo-research")
            footer = str(panel.query_one(".panel-footer", Static).content)
            assert "Edit" not in footer and "Delete" not in footer
            await pilot.press("e", "x", "enter")
            assert isinstance(app.screen, DetailPanel)
            assert app.screen.detail.actions == []
            await pilot.press("escape")
            for channel in ("workflows", "bot-skills"):
                before = len(calls(service, "getAgentWorkflows"))
                panel.changed(ServiceEvent(Other(channel, {"agentId": "other"})))
                await settle(app, pilot)
                assert len(calls(service, "getAgentWorkflows")) == before
                panel.changed(ServiceEvent(Other(channel, {"agentId": "demo-helper"})))
                await settle(app, pilot)
                assert len(calls(service, "getAgentWorkflows")) == before + 1
            await pilot.press("c")
            await settle(app, pilot)
            await assert_snapshot(app, pilot, "panel-skill-catalog")
            specs = {command.name: command for command in commands()}
            assert specs["skills"].scope == "session" and specs["skills"].needs_bot
            assert specs["skill-catalog"].scope == "any"

    asyncio.run(exercise())


@pytest.mark.parametrize("edit", [False, True])
def test_forms_confirm_cancel_and_read_only(tmp_path, monkeypatch, edit):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            run(ctx, "/skills")
            await settle(app, pilot)
            panel = app.screen
            select(panel, "demo-notes")
            await pilot.press("e" if edit else "n")
            assert isinstance(app.screen, FormPanel)
            form = app.screen
            assert [field.label for field in form.fields] == [
                "Name",
                "Description",
                "Body",
                "Schedule",
            ]
            form.query_one("#form-0", Input).value = "My skill"
            form.query_one("#form-1", Input).value = "Description"
            form.query_one("#form-2", TextArea).load_text("# Plain [bold] body")
            form.query_one("#form-3", Input).value = " daily "
            command = "updateAgentWorkflow" if edit else "createAgentWorkflow"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert app.screen.heading == "Save skill My skill?"
            assert app.screen.focused is not None
            assert app.screen.focused.id == "cancel"
            await pilot.press("escape")
            assert not calls(service, command)
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            app.read_only = True
            await accept(app, pilot)
            assert not calls(service, command)
            app.read_only = False
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert app.screen is panel
            assert calls(service, command)[0]["spec"] == {
                "name": "My skill",
                "description": "Description",
                "body": "# Plain [bold] body",
                "trigger": {"schedule": "daily", "isEnabled": True},
            }

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "key,skill,command",
    [
        ("x", "demo-notes", "deleteAgentWorkflow"),
        ("R", "demo-brief", "runAgentWorkflowNow"),
    ],
)
def test_delete_and_run(tmp_path, monkeypatch, key, skill, command):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            run(ctx, "/skills")
            await settle(app, pilot)
            select(app.screen, skill)
            await pilot.press(key)
            assert app.screen.focused is not None
            assert app.screen.focused.id == "cancel"
            await pilot.press("escape")
            assert not calls(service, command)
            await pilot.press(key)
            await accept(app, pilot)
            assert calls(service, command) == [
                {"id": "demo-helper", "workflowId": skill}
            ]

    asyncio.run(exercise())


@pytest.mark.parametrize("url", [False, True])
def test_import(tmp_path, monkeypatch, url):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    path = tmp_path / "skill.md"
    path.write_text("# Local skill", encoding="utf-8")

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            run(ctx, "/skills")
            await settle(app, pilot)
            await pilot.press("i")
            app.screen.query_one("#form-0", Input).value = (
                "https://example.test/skill" if url else f'"{path}"'
            )
            command = "importAgentWorkflowUrl" if url else "importAgentWorkflowText"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await pilot.press("escape")
            assert not calls(service, command)
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(service, command)[0] == {
                "id": "demo-helper",
                **(
                    {"url": "https://example.test/skill"}
                    if url
                    else {"markdown": "# Local skill"}
                ),
            }

    asyncio.run(exercise())


def test_catalog_cap_filter_install(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        entries = service.transport.commands["skillsCatalog"]
        assert isinstance(entries, list)
        entry = entries[0]
        service.transport.commands["skillsCatalog"] = [
            {**entry, "id": str(i), "name": f"Skill {i:03d}"} for i in range(230)
        ]
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            run(ctx, "/skill-catalog")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, _Catalog)
            assert len(panel.visible_rows) == 201
            assert panel.visible_rows[-1].label == "30 more; type to narrow"
            panel.query_one("#panel-filter", Input).value = "Skill 229"
            await pilot.pause()
            assert len(panel.visible_rows) == 1
            await pilot.press("enter")
            assert isinstance(app.screen, DetailPanel)
            assert ("Publisher", "Demo") in app.screen.detail.fields
            await pilot.press("a")
            assert app.screen.heading == "Add skill Skill 229 to Helper?"
            await pilot.press("escape")
            assert not calls(service, "importAgentWorkflowText")
            await pilot.press("a")
            await accept(app, pilot)
            assert (
                calls(service, "importAgentWorkflowText")[0]["name"] == "Weekly review"
            )
            await pilot.press("escape", "down", "a")
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.press("escape")

    asyncio.run(exercise())


def test_read_only_all_actions_and_error_notice(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False, read_only=True)
        notices = []
        monkeypatch.setattr(
            app, "notify", lambda text, **kwargs: notices.append((text, kwargs))
        )
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            run(ctx, "/skills")
            await settle(app, pilot)
            panel = app.screen
            select(panel, "demo-brief")
            for key in ("n", "e", "x", "R", "i"):
                await pilot.press(key)
                assert app.screen is panel
                assert notices[-1][0] == "Read-only mode"
            await pilot.press("c")
            await settle(app, pilot)
            await pilot.press("enter", "a")
            assert isinstance(app.screen, DetailPanel)
            assert notices[-1][0] == "Read-only mode"
            assert not [
                name
                for _, name, _ in service.transport.calls
                if name
                in {
                    "createAgentWorkflow",
                    "updateAgentWorkflow",
                    "deleteAgentWorkflow",
                    "runAgentWorkflowNow",
                    "importAgentWorkflowText",
                    "importAgentWorkflowUrl",
                }
            ]
            app.read_only = False
            service.transport.commands["importAgentWorkflowText"] = ValueError(
                "bad\x1b[2J[bold]"
            )
            await pilot.press("a")
            await accept(app, pilot)
            assert "\x1b" not in notices[-1][0]
            assert notices[-1][1] == {"severity": "error", "markup": False}

    asyncio.run(exercise())
