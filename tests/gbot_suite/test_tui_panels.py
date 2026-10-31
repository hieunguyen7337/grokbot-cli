import asyncio
import json
from threading import Event

from textual.widgets import Input, Static
from tui_snapshots import assert_snapshot

from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.panels import (
    Detail,
    DetailPanel,
    FormField,
    FormPanel,
    ListPanel,
    PanelAction,
    PanelRow,
)
from gbot.tui.screens.confirm import ConfirmScreen
from groken.client import ConnectError


def test_form_validation_and_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        app = GbotApp(load_fake(), animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            form = FormPanel(
                "Example",
                [
                    FormField("name", "Name", required=True),
                    FormField("note", "Note"),
                    FormField("secret", "Password", kind="password"),
                ],
                lambda values: None,
            )
            app.push_screen(form)
            await pilot.pause()
            form.query_one("#form-2", Input).value = "secret-value"
            await pilot.press("ctrl+s")
            assert "Required" in str(form.query_one("#form-error-0", Static).render())
            assert form.query_one("#form-2", Input).value == ""
            assert "secret-value" not in app.export_screenshot()
            await assert_snapshot(app, pilot, "panel-form")

    asyncio.run(exercise())


def test_list_loading_selection_and_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    gate = Event()
    calls = []

    def load():
        gate.wait(timeout=5)
        return [PanelRow("one", "[link=x]\x1b[31m")]

    async def exercise():
        app = GbotApp(load_fake(), animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            panel = ListPanel(
                "List",
                load,
                on_select=lambda row: calls.append(row.key),
                actions=[
                    PanelAction(
                        "d",
                        "Delete",
                        lambda row: calls.append("deleted"),
                        confirm="Delete?",
                    )
                ],
            )
            app.push_screen(panel)
            await pilot.pause()
            assert "Loading" in str(panel.query_one("#panel-rows", Static).render())
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "[link=x]" in app.export_screenshot()
            await pilot.press("enter", "d")
            assert calls == ["one"]
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.press("escape")
            assert calls == ["one"]
            await pilot.press("d", "tab", "enter")
            assert calls == ["one", "deleted"]

    asyncio.run(exercise())


def test_slash_key_focuses_the_filter(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        app = GbotApp(load_fake(), animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            panel = ListPanel(
                "List",
                lambda: [PanelRow("one", "One"), PanelRow("two", "Two")],
                filterable=True,
            )
            app.push_screen(panel)
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.set_focus(None)
            await pilot.pause()
            assert not panel.query_one("#panel-filter", Input).has_focus
            await pilot.press("slash")
            await pilot.pause()
            assert panel.query_one("#panel-filter", Input).has_focus

    asyncio.run(exercise())


def test_list_load_refusal_shows_server_sentence(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    def load():
        raise ConnectError(
            403, json.dumps({"code": "permission_denied", "message": "Teams only."})
        )

    async def exercise():
        app = GbotApp(load_fake(), animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            panel = ListPanel("List", load)
            app.push_screen(panel)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert panel.error == "Teams only."
            assert "permission_denied" not in app.export_screenshot()

    asyncio.run(exercise())


def test_detail_digit_and_form_error(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    calls = []

    async def exercise():
        app = GbotApp(load_fake(), animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app.push_screen(
                DetailPanel(
                    "Detail",
                    lambda: Detail(
                        (("Label", "[link=x]\x1b"),),
                        actions=(PanelAction("x", "Do", lambda: calls.append("done")),),
                    ),
                )
            )
            await pilot.pause()
            assert "[link=x]" in app.export_screenshot()
            await pilot.press("1")
            assert calls == ["done"]
            await pilot.press("escape")

            def fail(values):
                raise ValueError("[link=x] failure")

            form = FormPanel("Form", [FormField("name", "Name", value="kept")], fail)
            app.push_screen(form)
            await pilot.pause()
            await pilot.press("ctrl+s")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert form.query_one("#form-0", Input).value == "kept"
            assert "[link=x] failure" in str(
                form.query_one("#form-notice", Static).render()
            )

    asyncio.run(exercise())


def test_form_confirm_and_cancel(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    calls = []

    async def exercise():
        app = GbotApp(load_fake(), animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            form = FormPanel(
                "Form",
                [FormField("name", "Name", value="ok")],
                lambda values: calls.append(values) or "Saved",
                confirm="Save?",
            )
            app.push_screen(form)
            await pilot.pause()
            await pilot.press("ctrl+s")
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.press("escape")
            assert not calls
            await pilot.press("ctrl+s", "tab", "enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert calls == [{"name": "ok"}]
            assert app.screen is app.home

    asyncio.run(exercise())
