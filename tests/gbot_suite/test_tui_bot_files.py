import asyncio
import json
from typing import Any
from unittest.mock import Mock

from tui_snapshots import assert_snapshot

from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, commands, run
from gbot.tui.slash.bot_files import BotFilesPanel, LibraryPanel
from groken.client import ConnectError

FILES = {
    "files": [
        {
            "name": f"{name}.txt",
            "path": f"/f/{name}.txt",
            "sizeBytes": str(size),
            "contentType": "text/plain",
            "updatedAtMs": "1700000000000",
        }
        for name, size in (("notes", 1200), ("report", 2048000), ("todo", 90))
    ],
    "totalBytes": "2049290",
    "canEdit": True,
}
STORE = {
    "files": [{"name": "prefs.json", "path": "/store/prefs.json", "sizeBytes": "300"}]
}
DOCS = {
    "docs": [
        {
            "key": "k1",
            "provider": "notion",
            "externalId": "ext1",
            "url": "https://example.invalid/d",
            "title": "Plan",
            "kind": "page",
            "lastTouchedAtMs": "1700000000000",
        },
        {"key": "k2", "provider": "gdocs", "externalId": "ext2", "kind": "doc"},
    ]
}
PINS = {"pins": [{"externalDocKey": "k1"}, {"appKey": "app-1"}]}


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
    assert app.screen.focused is not None and app.screen.focused.id == "cancel"
    await pilot.click("#confirm")
    await settle(app, pilot)


def top(app) -> Any:
    return app.screen


def field(app) -> Any:
    return app.screen.query_one("#form-0")


def calls(service, rpc):
    return [p for _, n, p in service.transport.calls if n == rpc]


def footer(panel):
    return str(panel.query_one(".panel-footer").content)


def fake_files(can_edit=True):
    service = load_fake()
    service.transport.rpcs["ListGrokBotAgentFiles"] = {**FILES, "canEdit": can_edit}
    service.transport.rpcs["ListGrokBotUserStoreFiles"] = STORE
    service.transport.rpcs["DeleteGrokBotAgentFile"] = {}
    service.transport.rpcs["DeleteGrokBotUserStoreFile"] = {}
    service.transport.rpcs["BeginGrokBotAgentFileUpload"] = {
        "uploadToken": "SECRET-TOKEN",
        "url": "https://storage.invalid/SECRET-URL",
        "headers": {"h": "SECRET-HEADER"},
    }
    service.transport.rpcs["FinishGrokBotAgentFileUpload"] = {"file": FILES["files"][0]}
    return service


def test_registered():
    specs = {c.name: c for c in commands()}
    for name in ("bot-files", "library"):
        assert specs[name].scope == "session" and specs[name].needs_bot


def test_panel_snapshot_and_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = fake_files()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/bot-files")
            await settle(app, pilot)
            panel = top(app)
            assert isinstance(panel, BotFilesPanel)
            labels = [r.label for r in panel.rows]
            assert labels[:4] == ["notes.txt", "report.txt", "todo.txt", "prefs.json"]
            assert panel.rows[3].status == "user store"
            assert "Total 2.0 MB" in labels[-1]
            assert "u upload" in footer(panel) and "x delete" in footer(panel)
            assert calls(service, "ListGrokBotAgentFiles")[0]["pageToken"] == ""
            await assert_snapshot(app, pilot, "panel-bot-files")

    asyncio.run(exercise())


def test_delete_user_store_and_cancel(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = fake_files()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/bot-files")
            await settle(app, pilot)
            await pilot.press("x")
            assert top(app).heading == "Delete notes.txt from Helper?"
            await pilot.press("enter")
            assert not calls(service, "DeleteGrokBotAgentFile")
            await pilot.press("x")
            await accept(app, pilot)
            assert calls(service, "DeleteGrokBotAgentFile") == [
                {"agentId": "demo-helper", "name": "notes.txt"}
            ]
            panel = top(app)
            for _ in range(3):
                await pilot.press("down")
            await pilot.press("x")
            await accept(app, pilot)
            assert calls(service, "DeleteGrokBotUserStoreFile") == [
                {"agentId": "demo-helper", "path": "/store/prefs.json"}
            ]
            assert len(calls(service, "ListGrokBotAgentFiles")) == 3
            assert panel is app.screen

    asyncio.run(exercise())


def test_upload_confirm_cancel_and_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr(
        "gbot.service.bot_files._storage_put", lambda u, h, b: 200, raising=True
    )
    upload = tmp_path / "up.txt"
    upload.write_text("hello")

    async def exercise():
        service = fake_files()
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/bot-files")
            await settle(app, pilot)
            await pilot.press("u")
            await settle(app, pilot)
            field(app).value = str(tmp_path / "missing")
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert not isinstance(app.screen, ConfirmScreen)
            field(app).value = str(upload)
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert isinstance(app.screen, ConfirmScreen)
            assert top(app).heading == "Upload up.txt (5 B) to Helper?"
            await pilot.press("enter")
            assert not calls(service, "BeginGrokBotAgentFileUpload")
            panel = top(app)
            panel.upload()
            await settle(app, pilot)
            field(app).value = str(upload)
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            await accept(app, pilot)
            assert len(calls(service, "BeginGrokBotAgentFileUpload")) == 1
            assert (
                calls(service, "FinishGrokBotAgentFileUpload")[0]["uploadToken"]
                == "SECRET-TOKEN"
            )
            text = json.dumps([c.args for c in notice.call_args_list])
            assert "SECRET" not in text and "SECRET" not in footer(app.screen)

    asyncio.run(exercise())


def test_read_only_and_cannot_edit(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = fake_files(can_edit=False)
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/bot-files")
            await settle(app, pilot)
            panel = top(app)
            assert (
                "u upload" not in footer(panel) and "read only" in panel.rows[-1].label
            )
            await pilot.press("u")
            assert app.screen is panel
            service.transport.rpcs["ListGrokBotAgentFiles"] = FILES
            await pilot.press("g")
            await settle(app, pilot)
            assert "u upload" in footer(panel)
            app.read_only = True
            before = len(service.transport.calls)
            panel.upload()
            assert notice.call_args.args[0] == "Read-only mode"
            await pilot.press("x")
            assert notice.call_args.args[0] == "Read-only mode"
            assert app.screen is panel
            assert len(service.transport.calls) == before

    asyncio.run(exercise())


def test_empty_and_refused_states(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["ListGrokBotAgentFiles"] = ConnectError(
            403, json.dumps({"code": "permission_denied", "message": "Not for you."})
        )
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/bot-files")
            await settle(app, pilot)
            assert [r.label for r in top(app).rows] == ["Not for you."]
            app.pop_screen()
            service.transport.rpcs["ListGrokBotAgentFiles"] = {}
            run(ctx, "/bot-files")
            await settle(app, pilot)
            assert top(app).rows == []
            assert "no files" in top(app).empty
            assert "x delete" not in footer(app.screen)

    asyncio.run(exercise())


def fake_library():
    service = load_fake()
    service.transport.rpcs["ListGrokBotLibraryDocs"] = DOCS
    service.transport.rpcs["ListGrokBotLibraryPins"] = PINS
    service.transport.rpcs["SetGrokBotLibraryPin"] = {}
    return service


def test_library_panel_pin_open_and_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    opened = Mock()
    monkeypatch.setattr("gbot.tui.slash.bot_files.webbrowser.open", opened)

    async def exercise():
        service = fake_library()
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/library")
            await settle(app, pilot)
            panel = top(app)
            assert isinstance(panel, LibraryPanel)
            assert [(r.label, r.status) for r in panel.rows] == [
                ("Plan", "pinned"),
                ("ext2", ""),
                ("app-1", "pinned"),
            ]
            assert "p unpin" in footer(panel) and "o open" in footer(panel)
            await pilot.press("p")
            assert top(app).heading == "Unpin Plan for Helper?"
            await pilot.press("enter")
            assert not calls(service, "SetGrokBotLibraryPin")
            await pilot.press("p")
            await accept(app, pilot)
            assert calls(service, "SetGrokBotLibraryPin")[0]["isPinned"] is False
            await pilot.press("o")
            await settle(app, pilot)
            opened.assert_called_once_with("https://example.invalid/d")
            await pilot.press("down")
            assert "p pin" in footer(panel) and "o open" not in footer(panel)
            await pilot.press("p")
            await accept(app, pilot)
            assert calls(service, "SetGrokBotLibraryPin")[1]["isPinned"] is True
            await pilot.press("down")
            assert "p " not in footer(panel).replace("esc", "")
            app.read_only = True
            before = len(service.transport.calls)
            panel.toggle_pin(panel.docs["k1"])
            assert notice.call_args.args[0] == "Read-only mode"
            assert len(service.transport.calls) == before

    asyncio.run(exercise())


def test_library_empty_and_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["ListGrokBotLibraryDocs"] = ConnectError(
            403, json.dumps({"code": "permission_denied", "message": "Team only."})
        )
        service.transport.rpcs["ListGrokBotLibraryPins"] = {}
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/library")
            await settle(app, pilot)
            assert [r.label for r in top(app).rows] == ["Team only."]
            app.pop_screen()
            service.transport.rpcs["ListGrokBotLibraryDocs"] = {}
            run(ctx, "/library")
            await settle(app, pilot)
            assert top(app).rows == [] and "no library" in top(app).empty

    asyncio.run(exercise())


def test_delete_hides_bot_file_keys_when_cannot_edit(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = fake_files(can_edit=False)
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/bot-files")
            await settle(app, pilot)
            panel = top(app)
            assert "x delete" not in footer(panel)
            await pilot.press("x")
            assert top(app) is panel
            assert not calls(service, "DeleteGrokBotAgentFile")
            for _ in range(3):
                await pilot.press("down")
            assert "x delete" in footer(panel)
            await pilot.press("x")
            assert top(app).heading == "Delete /store/prefs.json from Helper?"

    asyncio.run(exercise())


def test_delete_user_store_confirm_names_the_path(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    store = {
        "files": [
            {"name": "prefs.json", "path": "/a/prefs.json", "sizeBytes": "1"},
            {"name": "prefs.json", "path": "/b/prefs.json", "sizeBytes": "2"},
        ]
    }

    async def exercise():
        service = fake_files()
        service.transport.rpcs["ListGrokBotUserStoreFiles"] = store
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/bot-files")
            await settle(app, pilot)
            for _ in range(4):
                await pilot.press("down")
            await pilot.press("x")
            assert top(app).heading == "Delete /b/prefs.json from Helper?"

    asyncio.run(exercise())
