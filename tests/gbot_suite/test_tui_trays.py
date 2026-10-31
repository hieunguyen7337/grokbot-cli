import asyncio

from textual.widgets import Input, Static
from tui_snapshots import assert_snapshot

from gbot.service import events
from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.panels import ListPanel
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, run


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


def fixture_trays():
    return [
        {
            "id": "new",
            "agentId": "demo-helper",
            "title": "Turn failed",
            "detail": "Try again\nTechnical details",
            "createdAt": 1_800_000_000_000,
            "count": 3,
            "actions": [
                {"kind": "start-fresh", "sessionId": "sub"},
                {"kind": "roll-back", "sessionId": "sub"},
                {"kind": "open-url", "label": "Help", "url": "https://example.com"},
                {"kind": "open-buy-credits", "label": "Buy"},
                {
                    "kind": "dashboard-action",
                    "label": "Limit",
                    "action": "requestLimitIncrease",
                },
                {"kind": "switch-model"},
            ],
        },
        {
            "id": "old",
            "agentId": "demo-research",
            "title": "Usage limit",
            "createdAt": 1_799_999_940_000,
            "severity": "info",
        },
    ]


def test_loading_events_and_indicators(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        raw = fixture_trays()
        service.transport.commands["getTrays"] = raw
        app = GbotApp(service, animate=False, read_only=True)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            assert len(app.trays) == 2
            heading = app.home.query_one("#heading", Static)
            assert "2 alerts" in str(heading.render())
            raw.append(
                dict(raw[0], id="extra", title="Newest", createdAt=1_800_000_000_001)
            )
            app._receive_event(events.Other("tray", {"anything": True}))
            await settle(app, pilot)
            assert len(app.trays) == 3
            screen = SessionScreen("demo-helper")
            await app.push_screen(screen)
            await settle(app, pilot)
            indicator = screen.query_one("#session-alert", Static)
            assert "Newest +1 more" in str(indicator.render())
            notices = []
            monkeypatch.setattr(
                app, "notify", lambda message, **kw: notices.append(message)
            )
            service.transport.commands["getTrays"] = OSError("Unsupported")
            app._receive_event(events.Other("tray", None))
            await settle(app, pilot)
            assert len(app.trays) == 3 and notices == [] and not app.state.errors
            service.transport.commands["getTrays"] = [raw[1]]
            app.refresh_trays()
            await settle(app, pilot)
            assert not indicator.display
            service.transport.commands["getTrays"] = []
            app.refresh_trays()
            await settle(app, pilot)
            assert "alert" not in str(heading.render())

    asyncio.run(exercise())


def test_home_mutations_and_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        raw = fixture_trays()
        service.transport.commands["getTrays"] = raw

        def dismissed(args):
            raw[:] = [tray for tray in raw if tray["id"] != args["id"]]

        service.transport.commands["dismissTray"] = dismissed
        service.transport.commands["clearTrays"] = lambda args: raw.clear()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            notices = []
            monkeypatch.setattr(
                app, "notify", lambda message, **kw: notices.append(message)
            )
            run(SlashContext(app, app.home, None, None), "/trays")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, ListPanel)
            await pilot.press("b")
            await pilot.pause()
            app.read_only = True
            service.transport.calls.clear()
            await pilot.click("#confirm")
            await settle(app, pilot)
            assert not service.transport.calls and notices[-1] == "Read-only mode"
            app.read_only = False
            await pilot.press("b")
            await pilot.pause()
            await pilot.click("#confirm")
            await settle(app, pilot)
            assert "Rolled back · open the bot to edit your message" in notices
            assert len(panel.rows) == 1 and len(app.trays) == 1
            assert "1 alert" in str(app.home.query_one("#heading", Static).render())
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            assert app.screen.heading == "Clear all 1 alerts?"
            await pilot.click("#confirm")
            await settle(app, pilot)
            assert not panel.rows and not app.trays
            assert "No alerts" in str(panel.query_one("#panel-rows", Static).render())

    asyncio.run(exercise())


def test_panel_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr("gbot.tui.slash.trays.time", lambda: 1_800_000_000)

    async def exercise():
        service = load_fake()
        service.transport.commands["getTrays"] = fixture_trays()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            run(SlashContext(app, app.home, None, None), "/trays")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, ListPanel)
            assert len(panel.rows) == 2
            assert panel.rows[0].label.endswith(": Turn failed")
            assert panel.rows[0].status == "×3" and panel.rows[1].tone == "muted"
            assert "Technical details" not in panel.rows[0].detail
            await assert_snapshot(app, pilot, "panel-trays")

    asyncio.run(exercise())


def test_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    opened = []
    monkeypatch.setattr("gbot.tui.slash.trays.webbrowser.open", opened.append)

    async def exercise():
        service = load_fake()
        raw = fixture_trays()
        service.transport.commands["getTrays"] = raw
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            screen = SessionScreen("demo-helper", session_id="sub")
            await app.push_screen(screen)
            await settle(app, pilot)
            notices = []
            monkeypatch.setattr(
                app, "notify", lambda message, **kw: notices.append(message)
            )
            ctx = SlashContext(app, screen, screen.bot_id, "sub")
            run(ctx, "/trays")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, ListPanel)
            assert [r.label for r in panel.rows] == ["Turn failed"]
            for key in ("f", "b", "d", "c"):
                app.read_only = True
                service.transport.calls.clear()
                await pilot.press(key)
                await settle(app, pilot)
                assert not service.transport.calls and notices[-1] == "Read-only mode"
            for key in ("$", "a", "m"):
                await pilot.press(key)
                assert notices[-1] == "Do this in the Grok Bot app"
            await pilot.press("o")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen) and opened == []
            await pilot.click("#confirm")
            await settle(app, pilot)
            assert opened == ["https://example.com"]
            raw[0]["actions"][2]["url"] = "http://example.com"
            panel.reload()
            await settle(app, pilot)
            await pilot.press("o")
            assert notices[-1] == "Only https links open"
            app.read_only = False
            for key, command in (
                ("f", "startFreshConversation"),
                ("b", "rollBackConversation"),
                ("c", "clearTrays"),
            ):
                service.transport.calls.clear()
                await pilot.press(key)
                await pilot.pause()
                assert isinstance(app.screen, ConfirmScreen)
                await pilot.press("escape")
                assert not service.transport.calls
                await pilot.press(key)
                await pilot.pause()
                await pilot.click("#confirm")
                await settle(app, pilot)
                expected = (
                    {} if key == "c" else {"id": screen.bot_id, "sessionId": "sub"}
                )
                assert ("command", command, expected) in service.transport.calls
                if key != "c":
                    assert (
                        "command",
                        "dismissTray",
                        {"id": "new"},
                    ) in service.transport.calls
                if key == "b":
                    users = [
                        e
                        for e in service.transcript(screen.bot_id).entries
                        if e.role == "user"
                    ]
                    assert (
                        screen.query_one("#session-input", Input).value
                        == max(users, key=lambda e: e.seq).text
                    )
            await pilot.press("d")
            await settle(app, pilot)
            assert ("command", "dismissTray", {"id": "new"}) in service.transport.calls
            service.transport.commands["dismissTray"] = OSError("Failed dismissal")
            await pilot.press("d")
            await settle(app, pilot)
            assert app.state.errors[screen.bot_id] == "Failed dismissal"
            service.transport.commands["clearTrays"] = OSError("Failed clear")
            await pilot.press("c")
            await pilot.pause()
            await pilot.click("#confirm")
            await settle(app, pilot)
            assert notices[-1] == "Failed clear"
            raw[0]["actions"] = []
            raw[0]["title"] = "[link=x]Title\x1b[31m"
            raw[0]["detail"] = "[link=x]Detail\x1b[31m"
            panel.reload()
            await settle(app, pilot)
            await pilot.press("f")
            assert notices[-1] == "This alert has no start fresh action"
            rendered = str(panel.query_one("#panel-rows", Static).render())
            assert "[link=x]Title" in rendered and "[link=x]Detail" in rendered
            assert "\x1b" not in rendered
            app.refresh_trays()
            await settle(app, pilot)
            indicator = str(screen.query_one("#session-alert", Static).render())
            assert "[link=x]Title" in indicator and "\x1b" not in indicator

    asyncio.run(exercise())
