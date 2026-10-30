import asyncio

import pytest
from textual.widgets import Input, Static
from tui_snapshots import assert_snapshot

from gbot.service.events import BoxChanged
from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp, ServiceEvent
from gbot.tui.panels.kit import DetailPanel, FormPanel, ListPanel
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, commands, run

URL = "https://viewer.invalid/?token=private"


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
    return [
        payload for _, command, payload in service.transport.calls if command == name
    ]


async def accept(app, pilot):
    assert isinstance(app.screen, ConfirmScreen)
    assert app.screen.focused is not None
    assert app.screen.focused.id == "cancel"
    await pilot.click("#confirm")
    await settle(app, pilot)


def test_inboxes(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notices = []
        monkeypatch.setattr(
            app, "notify", lambda text, **kw: notices.append((text, kw))
        )
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            assert run(ctx, "/inboxes") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, ListPanel)
            assert panel.heading == "Email inboxes"
            assert panel.rows[0].detail == "assigned"
            await assert_snapshot(app, pilot, "panel-inboxes")
            service.transport.rpcs["ListGrokBotEmailInboxes"] = {}
            await pilot.press("r")
            await settle(app, pilot)
            assert "No inboxes" in str(panel.query_one("#panel-rows", Static).render())
            await pilot.press("n")
            assert isinstance(app.screen, FormPanel)
            app.screen.query_one("#form-0", Input).value = " ALPHA "
            await settle(app, pilot)
            assert "alpha@mail.grokbot.com" in str(
                app.screen.query_one("#form-error-0", Static).render()
            )
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert isinstance(app.screen, ConfirmScreen)
            assert "Create inbox alpha@mail.grokbot.com?" in app.screen.heading
            assert app.screen.focused is not None
            assert app.screen.focused.id == "cancel"
            await pilot.press("escape")
            assert not calls(service, "CreateGrokBotEmailInbox")
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert app.screen is panel
            assert calls(service, "CreateGrokBotEmailInbox") == [
                {"username": "alpha", "displayName": ""}
            ]
            app.read_only = True
            await pilot.press("n")
            assert notices[-1][0] == "Read-only mode"
            assert app.screen is panel
            app.read_only = False
            await pilot.press("n")
            app.read_only = True
            await pilot.press("ctrl+s")
            assert notices[-1][0] == "Read-only mode"
            await pilot.press("escape")
            app.read_only = False
            await pilot.press("n")
            app.screen.query_one("#form-0", Input).value = "bravo"
            service.transport.rpcs["CreateGrokBotEmailInbox"] = ValueError(
                "bad\x1b[2J[bold]"
            )
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert "\x1b" not in notices[-1][0]
            assert notices[-1][1] == {"severity": "error", "markup": False}

    asyncio.run(exercise())


@pytest.mark.parametrize("temporal", [False, True])
def test_computer(tmp_path, monkeypatch, temporal):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)

    async def exercise():
        service = load_fake()
        if temporal:
            next(row for row in service.state.rows if row["id"] == "demo-helper")[
                "harness"
            ] = "temporal"
        app = GbotApp(service, animate=False)
        notices = []
        monkeypatch.setattr(app, "notify", lambda text, **kw: notices.append(text))
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            assert run(ctx, "/computer") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, DetailPanel)
            assert ("State", "running") in panel.detail.fields
            assert ("Host version", "0.77.0") in panel.detail.fields
            assert panel.detail.body == "Review the desktop"
            if not temporal:
                await assert_snapshot(app, pilot, "panel-computer")
            for key, name, title in [
                ("w", "ensureForeverBox", "Wake Helper's computer?"),
                ("u", "updateForeverBox", "Update Helper's computer? It restarts."),
                (
                    "h",
                    "EndGrokBotBoxHandoff" if temporal else "handBackForeverBox",
                    "Hand the computer back to Helper?",
                ),
            ]:
                await pilot.press(key)
                assert isinstance(app.screen, ConfirmScreen)
                assert app.screen.heading == title
                assert app.screen.focused is not None
                assert app.screen.focused.id == "cancel"
                await pilot.press("escape")
                assert not calls(service, name)
                await pilot.press(key)
                await accept(app, pilot)
                assert len(calls(service, name)) == 1
                app.read_only = True
                await pilot.press(key)
                assert notices[-1] == "Read-only mode"
                assert app.screen is panel
                assert len(calls(service, name)) == 1
                app.read_only = False
            service.transport.commands["getForeverBoxStatus"] = {
                "state": "hibernated",
                "vncUrl": URL,
                "diskPressure": {"level": "soft"},
            }
            before = len(calls(service, "getForeverBoxStatus"))
            app.post_message(ServiceEvent(BoxChanged("another", "hibernated")))
            await settle(app, pilot)
            assert len(calls(service, "getForeverBoxStatus")) == before
            app.post_message(ServiceEvent(BoxChanged("demo-helper", "hibernated")))
            await settle(app, pilot)
            assert len(calls(service, "getForeverBoxStatus")) == before + 1
            assert ("Phase", "sleeping") in panel.detail.fields
            assert ("Disk pressure", "soft") in panel.detail.fields
            assert {a.key for a in panel.detail.actions} == {"w", "o", "r"}
            app.read_only = True
            await pilot.press("o")
            await settle(app, pilot)
            assert opened == [URL]
            assert notices[-1] == "Opened the live view."
            assert URL not in str(panel.query_one("#detail-content", Static).render())
            service.transport.commands["getForeverBoxStatus"] = None
            await pilot.press("r")
            await settle(app, pilot)
            assert {a.key for a in panel.detail.actions} == {"w", "r"}
            assert ("State", "absent") in panel.detail.fields
            specs = {c.name: c for c in commands()}
            assert specs["computer"].scope == "session" and specs["computer"].needs_bot
            assert specs["inboxes"].scope == "any"

    asyncio.run(exercise())
