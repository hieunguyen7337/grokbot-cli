import asyncio
import base64
from pathlib import Path

import pytest
from textual.widgets import Input, Select, Static
from tui_snapshots import assert_snapshot

from gbot.service.avatar_voice import DEMO_COMMANDS
from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.panels import DetailPanel, FormPanel, ListPanel
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, commands, run


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


@pytest.mark.parametrize("temporal", [False, True])
def test_voice(tmp_path, monkeypatch, temporal):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        row = next(row for row in service.state.rows if row["id"] == "demo-helper")
        row.update(voiceId="future-voice", voiceSpeed=1.24, voiceLanguage="EN_us")
        if temporal:
            row["harness"] = "temporal"
            service.transport.rpcs["ListGrokBotAgents"] = {
                "agents": [
                    dict(row, agentId=row["id"], voiceSpeed=0.74, voiceLanguage="pt_br")
                ]
            }
        app = GbotApp(service, animate=False)
        notices = []
        monkeypatch.setattr(app, "notify", lambda text, **kw: notices.append(text))
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            assert run(ctx, "/voice") is None
            await settle(app, pilot)
            assert isinstance(app.screen, FormPanel)
            assert [
                app.screen.query_one(f"#form-{i}", Select).value for i in range(3)
            ] == [
                "future-voice",
                "0.75x" if temporal else "1.25x",
                "pt-BR" if temporal else "en",
            ]
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert notices[-1] == "Nothing to change"
            app.screen.query_one("#form-1", Select).value = "2x"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.press("escape")
            name = "SetGrokBotAgentVoice" if temporal else "setAgentVoice"
            assert not calls(service, name)
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(service, name) == [{"id": "demo-helper", "voiceSpeed": 2}]
            run(ctx, "/voice")
            await settle(app, pilot)
            app.screen.query_one("#form-0", Select).value = "Ara"
            app.screen.query_one("#form-2", Select).value = "fr"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(service, name)[-1] == {
                "id": "demo-helper",
                "voiceId": "ara",
                "voiceLanguage": "fr",
            }
            run(ctx, "/voice")
            await settle(app, pilot)
            app.read_only = True
            await pilot.press("ctrl+s")
            assert notices[-1] == "Read-only mode"
            assert len(calls(service, name)) == 2

    asyncio.run(exercise())


def test_avatar(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    png = base64.b64decode(DEMO_COMMANDS["generateAgentAvatarImage"]["imageBase64"])
    path = tmp_path / "image.png"
    path.write_bytes(png)

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notices = []
        monkeypatch.setattr(app, "notify", lambda text, **kw: notices.append(text))
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            run(ctx, "/avatar")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, DetailPanel)
            assert panel.detail.body == "Image: none"
            service.transport.commands["getAgentAvatar"] = {
                "dataUrl": "data:image/png;base64," + base64.b64encode(png).decode()
            }
            await pilot.press("escape")
            run(ctx, "/avatar")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, DetailPanel)
            assert "Image: image/png · 1x1" in panel.detail.body
            await pilot.press("s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert (tmp_path / "Downloads" / "avatar.png").read_bytes() == png
            for data, error in [
                (b"not PNG", "Invalid PNG"),
                (b"x" * (2 * 1024 * 1024 + 1), "Avatar exceeds"),
            ]:
                path.write_bytes(data)
                await pilot.press("f")
                await settle(app, pilot)
                app.screen.query_one("#form-0", Input).value = str(path)
                await pilot.press("ctrl+s")
                await settle(app, pilot)
                assert notices[-1].startswith(error)
                assert not calls(service, "setAgentAvatarBytes")
                await pilot.press("escape")
            path.write_bytes(png)
            await pilot.press("f")
            await settle(app, pilot)
            app.screen.query_one("#form-0", Input).value = str(path)
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.press("escape")
            assert not calls(service, "setAgentAvatarBytes")
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert (
                base64.b64decode(
                    str(calls(service, "setAgentAvatarBytes")[-1]["pngBase64"])
                )
                == png
            )
            assert "Image: image/png · 1x1" in panel.detail.body
            await pilot.press("g")
            await settle(app, pilot)
            app.screen.query_one("#form-0", Input).value = "A blue star"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert len(calls(service, "setAgentAvatarBytes")) == 2
            service.transport.commands["generateAgentAvatarImage"] = {
                "imageBase64": base64.b64encode(b"jpeg").decode(),
                "mimeType": "image/jpeg",
            }
            await pilot.press("g")
            await settle(app, pilot)
            app.screen.query_one("#form-0", Input).value = "A star"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert notices[-1] == "The generated image is not a PNG gbot can upload"
            assert len(calls(service, "setAgentAvatarBytes")) == 2
            await pilot.press("s")
            await settle(app, pilot)
            await accept(app, pilot)
            saved = tmp_path / "Downloads" / "avatar.jpg"
            assert saved.read_bytes() == b"jpeg"
            saved.write_bytes(b"keep")
            await pilot.press("s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert saved.read_bytes() == b"keep"
            assert (saved.parent / "avatar (1).jpg").read_bytes() == b"jpeg"
            await pilot.press("c")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(service, "setAgentAvatarBytes")[-1]["pngBase64"] is None
            await pilot.press("k")
            await settle(app, pilot)
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert notices[-1] == "Nothing to change"
            app.screen.query_one("#form-0", Select).value = "star"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(service, "updateAgent")[-1]["editedFields"] == ["avatarShape"]
            await pilot.press("k")
            await settle(app, pilot)
            app.screen.query_one("#form-1", Select).value = "red"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert calls(service, "updateAgent")[-1]["editedFields"] == ["avatarColor"]
            app.read_only = True
            before = len(service.transport.calls)
            for key in ("f", "g", "s", "c", "k"):
                await pilot.press(key)
                assert notices[-1] == "Read-only mode"
                assert app.screen is panel
            assert len(service.transport.calls) == before

    asyncio.run(exercise())


def test_templates(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        market = service.transport.rpcs["ListPublicGrokBotMarketplaceListings"]
        assert isinstance(market, dict)
        item = market["listings"][0]
        market["featuredListings"] = [
            dict(item, name="[bold]Featured", shareId="featured")
        ]
        app = GbotApp(service, animate=False)
        notices = []
        monkeypatch.setattr(app, "notify", lambda text, **kw: notices.append(text))
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            run(ctx, "/templates unknown")
            await settle(app, pilot)
            assert "No templates in unknown" in str(
                app.screen.query_one("#panel-rows", Static).render()
            )
            await pilot.press("escape")
            run(ctx, "/templates pRoDuCtIvItY")
            await settle(app, pilot)
            assert isinstance(app.screen, ListPanel)
            assert [r.label for r in app.screen.rows] == [
                "Featured",
                "[bold]Featured",
                "Productivity",
                "Helper",
            ]
            await pilot.press("down", "enter")
            await settle(app, pilot)
            detail = app.screen
            assert isinstance(detail, DetailPanel)
            assert ("Version", "1") in detail.detail.fields
            app.read_only = True
            await pilot.press("u")
            assert notices[-1] == "Read-only mode"
            app.read_only = False
            await pilot.press("u")
            await settle(app, pilot)
            await pilot.press("escape")
            assert not calls(service, "CreateGrokBotAgentFromTemplate")
            service.transport.rpcs["CreateGrokBotAgentFromTemplate"] = OSError(
                "Import failed"
            )
            await pilot.press("u")
            await settle(app, pilot)
            await accept(app, pilot)
            assert app.screen is detail and notices[-1] == "Import failed"

            def created(args):
                row = {"id": args["agentId"], "name": "Helper", "harness": "temporal"}
                service.state.rows.append(row)
                return {
                    "agent": dict(row, agentId=row["id"]),
                    "setupHandledByServer": False,
                }

            service.transport.rpcs["CreateGrokBotAgentFromTemplate"] = created
            await pilot.press("u")
            await settle(app, pilot)
            await accept(app, pilot)
            imports = calls(service, "CreateGrokBotAgentFromTemplate")
            assert imports[0]["agentId"] == imports[1]["agentId"]
            assert isinstance(app.screen, SessionScreen)
            assert app.screen.bot_id == imports[1]["agentId"]
            assert notices[-1] == "Finish this template's setup in the Grok Bot app"

    asyncio.run(exercise())


def test_panels_and_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        app = GbotApp(load_fake(), animate=False, read_only=True)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await session(app, pilot)
            for name in ("voice", "avatar", "templates"):
                assert run(ctx, f"/{name}") is None
                await settle(app, pilot)
                await assert_snapshot(app, pilot, f"panel-{name}")
                await pilot.press("escape")
            specs = {c.name: c for c in commands()}
            assert all(
                specs[name].scope == "session" and specs[name].needs_bot
                for name in ("voice", "avatar")
            )
            assert specs["templates"].scope == "any"

    asyncio.run(exercise())
