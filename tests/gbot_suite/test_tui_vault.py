import asyncio
import re

from textual.widgets import Input, Static
from tui_snapshots import assert_snapshot

from gbot.service import vault as v
from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.panels import DetailPanel, FormPanel, ListPanel
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, commands, run
from gbot.tui.slash.vault import onepassword


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


def test_vault(tmp_path, monkeypatch):
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
            assert run(ctx, "/vault") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, ListPanel)
            assert [r.label for r in panel.rows] == [
                "Logins",
                "Example",
                "Cards",
                "Travel card",
                "Contacts",
                "Home",
                "Payment methods",
                "Link card",
            ]
            assert panel.rows[1].detail == "demo@example.com · example.com"
            assert panel.rows[3].detail == "Visa ··4242 · 12/30"
            await pilot.press("a")
            await settle(app, pilot)
            form = app.screen
            assert isinstance(form, FormPanel)
            form.query_one("#form-0", Input).value = "New"
            form.query_one("#form-1", Input).value = "user"
            password = "unique-tui-password"
            form.query_one("#form-2", Input).value = password
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert isinstance(app.screen, ConfirmScreen)
            assert form.query_one("#form-2", Input).value == ""
            await pilot.press("escape")
            assert not calls(service, v.RPCS[1])
            form.query_one("#form-2", Input).value = password
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(service, v.RPCS[1])[-1]["password"] == password
            assert "id" not in calls(service, v.RPCS[1])[-1]
            assert app.screen is panel
            panel.index = 1
            await pilot.press("e")
            await settle(app, pilot)
            form = app.screen
            assert isinstance(form, FormPanel)
            assert form.query_one("#form-0", Input).value == "Example"
            assert form.query_one("#form-2", Input).value == ""
            form.query_one("#form-2", Input).value = password
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(service, v.RPCS[1])[-1]["id"] == "demo-login"
            panel.index = 1
            await pilot.press("d")
            await settle(app, pilot)
            await pilot.press("escape")
            assert not calls(service, v.RPCS[2])
            await pilot.press("d")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(service, v.RPCS[2]) == [{"id": "demo-login"}]
            panel.index = 3
            await pilot.press("e")
            assert notices[-1][0] == "Add or edit cards in the Grok Bot app"
            app.read_only = True
            before = len(service.transport.calls)
            for key in ("a", "e", "d"):
                await pilot.press(key)
                assert notices[-1][0] == "Read-only mode"
            assert len(service.transport.calls) == before
            assert password not in str(notices)

    asyncio.run(exercise())


def test_card_rows_never_show_card_numbers(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    full = "4929123456785678"
    long_digits = "5500005555555559"

    async def exercise():
        service = load_fake()
        # The models have no full-number field, so plant digits in every field a
        # row could render, including ones no row shows today.
        card = {
            "brand": "Visa",
            "last4": "5678",
            "expMonth": 3,
            "expYear": 2032,
            "holderName": full,
            "nickname": full,
            "number": full,
            "cardNumber": full,
            "pan": full,
        }
        service.transport.rpcs[v.RPCS[0]] = {
            "credentials": [
                {
                    "id": "secret-card",
                    "kind": 2,
                    "title": "Work card",
                    "notes": full,
                    "card": card,
                }
            ]
        }
        service.transport.rpcs[v.RPCS[3]] = {
            "outcome": 1,
            "paymentMethods": [
                {
                    "id": "pm",
                    "name": "Spend card",
                    "kind": 1,
                    "brand": "Mastercard",
                    "last4": "9559",
                    "expMonth": 1,
                    "expYear": 2033,
                    "number": long_digits,
                    "cardNumber": long_digits,
                }
            ],
        }
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            assert run(ctx, "/vault") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, ListPanel)
            rows = {r.key: r for r in panel.rows}
            assert rows["secret-card"].detail == "Visa ··5678 · 03/32"
            assert rows["payment:pm"].detail == "Mastercard ··9559 · 01/33"
            texts = [
                text
                for r in panel.rows
                for text in (r.key, r.label, r.detail, r.status)
            ]
            shown = str(panel.query_one("#panel-rows", Static).render())
            assert "5678" in shown and "9559" in shown
            for text in [*texts, shown]:
                # Join digits split by a space or dash, so "4929 1234 5678" still counts.
                joined = re.sub(r"(?<=\d)[ -](?=\d)", "", text)
                assert not re.search(r"\d{8,}", joined), text
                assert full not in text and long_digits not in text

    asyncio.run(exercise())


def test_passkeys_onepassword(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs[v.RPCS[7]] = v.DEMO_RPCS[v.RPCS[6]]
        app = GbotApp(service, animate=False)
        notices = []
        monkeypatch.setattr(app, "notify", lambda text, **kw: notices.append(text))
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            run(ctx, "/passkeys")
            await settle(app, pilot)
            assert isinstance(app.screen, ListPanel)
            assert (
                "single_device · backed up: no · last used 2027-01-15"
                == app.screen.rows[0].detail
            )
            await pilot.press("x")
            await settle(app, pilot)
            await pilot.press("escape")
            assert not calls(service, v.RPCS[5])
            await pilot.press("x")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(service, v.RPCS[5]) == [{"credentialId": "demo-passkey"}]
            app.read_only = True
            await pilot.press("x")
            assert notices[-1] == "Read-only mode"
            app.read_only = False
            await pilot.press("escape")
            onepassword(ctx, "")
            await settle(app, pilot)
            assert isinstance(app.screen, DetailPanel)
            assert ("Vault", "Personal") in app.screen.detail.fields
            for key, name in (("s", v.RPCS[7]), ("x", v.RPCS[8])):
                app.read_only = True
                await pilot.press(key)
                assert notices[-1] == "Read-only mode"
                app.read_only = False
                await pilot.press(key)
                await settle(app, pilot)
                await pilot.press("escape")
                assert not calls(service, name)
                await pilot.press(key)
                await settle(app, pilot)
                await accept(app, pilot)
                assert calls(service, name)
            service.transport.rpcs[v.RPCS[6]] = {}
            onepassword(ctx, "")
            await settle(app, pilot)
            assert app.screen.detail.body == "Connect 1Password in the Grok Bot app"
            assert all(
                c.scope == "any"
                for c in commands()
                if c.name in ("vault", "passkeys", "1password")
            )

    asyncio.run(exercise())


def test_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        app = GbotApp(load_fake(), animate=False, read_only=True)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            for name in ("vault", "passkeys"):
                run(ctx, "/" + name)
                await settle(app, pilot)
                await assert_snapshot(app, pilot, "panel-" + name)
                await pilot.press("escape")

    asyncio.run(exercise())


def test_payment_status(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs[v.RPCS[3]] = {"outcome": 2}
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            run(ctx, "/vault")
            await settle(app, pilot)
            assert "needs_auth" in str(
                app.screen.query_one("#panel-rows", Static).render()
            )

    asyncio.run(exercise())
