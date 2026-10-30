import asyncio
from functools import partial
from pathlib import Path

from textual.events import Paste
from textual.widgets import Input, Static
from tui_snapshots import assert_snapshot

from gbot.service import conversation
from gbot.service.attachments import Attachment
from gbot.service.fake import load_fake
from gbot.service.models import Entry
from gbot.tui.app import GbotApp
from gbot.tui.glyphs import ASCII
from gbot.tui.panels import DetailPanel, FormPanel, ListPanel
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, commands, run
from gbot.tui.widgets.transcript import Transcript, entry_widget


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


def file_entries():
    return [
        {
            "id": "file-user",
            "seq": 1,
            "kind": "user-attachment",
            "file_path": "/attachments/report.txt",
            "file_name": "report.txt",
            "byteSize": 12288,
        },
        {
            "id": "file-bot",
            "seq": 2,
            "kind": "send-message",
            "message": {
                "type": "attachment",
                "source_path": "/attachments/notes.txt",
                "file_name": "[bold]notes.txt",
                "byteSize": 32,
            },
        },
        {
            "id": "file-link",
            "seq": 3,
            "kind": "send-message",
            "message": {
                "type": "attachment",
                "url": "https://example.com/file",
                "file_name": "Remote file",
            },
        },
        {
            "id": "file-http",
            "seq": 4,
            "kind": "send-message",
            "message": {
                "type": "attachment",
                "url": "http://example.com/file",
                "file_name": "HTTP file",
            },
        },
    ]


def test_staging_sending_and_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    path = tmp_path / "report.txt"
    path.write_text("report", encoding="utf-8")

    async def exercise():
        service = load_fake()
        monkeypatch.setattr(
            service, "send", partial(conversation.send, service.transport)
        )
        service.transport.commands["getAgentTranscriptTail"] = {"entries": []}
        service.transport.commands["sendPrompt"] = {"accepted": True}
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            screen = SessionScreen("demo-helper")
            await app.push_screen(screen)
            await settle(app, pilot)
            ctx = SlashContext(app, screen, screen.bot_id, None)
            notices = []
            monkeypatch.setattr(
                app, "notify", lambda message, **kw: notices.append(message)
            )
            assert run(ctx, f'/attach "{path}"') is None
            await settle(app, pilot)
            assert any(c[1] == "uploadAttachmentChunk" for c in service.transport.calls)
            line = screen.query_one("#session-attachments", Static)
            assert line.display and "report.txt" in str(line.render())
            screen.uploads = 1
            await pilot.press("enter")
            assert notices[-1] == "Wait for the upload to finish"
            screen.uploads = 0
            service.transport.commands["sendPrompt"] = OSError("Send failed")
            field = screen.query_one("#session-input", Input)
            field.value = "Review"
            await pilot.press("enter")
            await settle(app, pilot)
            assert screen.attachments and field.value == "Review"
            first_nonce = screen._send_nonce
            await pilot.press("enter")
            await settle(app, pilot)
            assert first_nonce == screen._send_nonce
            screen.attachments[:] = [Attachment("/attachments/other", "report.txt")]
            await pilot.press("enter")
            await settle(app, pilot)
            assert first_nonce != screen._send_nonce
            service.transport.commands["sendPrompt"] = {"accepted": True}
            await pilot.press("enter")
            await settle(app, pilot)
            sent = [c[2] for c in service.transport.calls if c[1] == "sendPrompt"][-1]
            assert sent["attachmentPaths"] == ["/attachments/other"]
            assert sent["attachmentNames"] == ["report.txt"]
            assert not screen.attachments and not line.display
            run(ctx, f"/attach {path}")
            await settle(app, pilot)
            await pilot.press("enter")
            await settle(app, pilot)
            sent = [c[2] for c in service.transport.calls if c[1] == "sendPrompt"][-1]
            assert sent["prompt"] == "" and sent["attachmentNames"] == ["report.txt"]
            service.transport.commands["uploadAttachmentChunk"] = OSError(
                "Upload failed"
            )
            run(ctx, f"/attach {path}")
            await settle(app, pilot)
            assert not screen.attachments and notices[-1] == "Upload failed"
            run(ctx, f"/attach {tmp_path / 'absent'}")
            assert notices[-1].startswith("No such file:")

    asyncio.run(exercise())


def test_paste_detach_form_and_readonly(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    path = tmp_path / "notes.txt"
    path.write_text("notes", encoding="utf-8")

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            screen = SessionScreen("demo-helper")
            await app.push_screen(screen)
            await settle(app, pilot)
            ctx = SlashContext(app, screen, screen.bot_id, None)
            notices = []
            monkeypatch.setattr(
                app, "notify", lambda message, **kw: notices.append(message)
            )
            field = screen.query_one("#session-input", Input)
            for text in (f'"{path}"', path.as_uri()):
                field.post_message(Paste(text))
                await settle(app, pilot)
                assert field.value == "" and screen.attachments
            run(ctx, "/detach notes.txt")
            assert (
                not screen.attachments
                and notices[-1] == "Removed notes.txt · notes.txt"
            )
            run(ctx, "/detach")
            assert notices[-1] == "Nothing attached"
            field.post_message(Paste("ordinary text"))
            await settle(app, pilot)
            assert field.value == "ordinary text"
            field.value = ""
            field.post_message(Paste("~gbot-nonexistent-user/path"))
            await settle(app, pilot)
            assert field.value == "~gbot-nonexistent-user/path"
            field.value = ""
            run(ctx, "/attach")
            await settle(app, pilot)
            assert isinstance(app.screen, FormPanel)
            app.screen.query_one("#form-0", Input).value = str(path)
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert app.screen is screen and screen.attachments
            run(ctx, "/detach")
            assert not screen.attachments
            app.read_only = True
            run(ctx, f"/attach {path}")
            assert notices[-1] == "Read-only mode"
            field.post_message(Paste(str(path)))
            await settle(app, pilot)
            assert not screen.attachments and field.value == str(path)
            await pilot.press("enter")
            await settle(app, pilot)
            assert not service.sent and notices[-1] == "Read-only mode"
            specs = {c.name: c for c in commands()}
            assert all(
                specs[n].scope == "session" and specs[n].needs_bot
                for n in ("attach", "detach", "files")
            )

    asyncio.run(exercise())


def test_files_preview_save_links_and_readonly(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    async def exercise():
        service = load_fake()
        service.state.transcripts["demo-helper"] = file_entries()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            screen = SessionScreen("demo-helper")
            await app.push_screen(screen)
            await settle(app, pilot)
            ctx = SlashContext(app, screen, screen.bot_id, None)
            notices = []
            monkeypatch.setattr(
                app, "notify", lambda message, **kw: notices.append(message)
            )
            history = screen.query_one(Transcript)
            user = history.entries["file-user"]
            assert ">" in str(user.render()) and "12 KB" in str(user.render())
            bot = history.entries["file-bot"]
            assert any("[bold]notes.txt" in str(w.render()) for w in bot.query(Static))
            assert not bot.query("CardEntry")
            run(ctx, "/files")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, ListPanel)
            assert [r.label for r in panel.rows] == [
                "HTTP file",
                "Remote file",
                "[bold]notes.txt",
                "report.txt",
            ]
            assert panel.rows[-1].detail == "you · 12 KB"
            await pilot.press("o")
            assert notices[-1] == "Only https links open" and not opened
            await pilot.press("down", "o")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen) and not opened
            await pilot.press("escape")
            await pilot.press("o")
            await pilot.pause()
            await pilot.click("#confirm")
            assert opened == ["https://example.com/file"]
            await pilot.press("down", "enter")
            await settle(app, pilot)
            assert isinstance(app.screen, DetailPanel)
            assert "Hello from the bot." in str(
                app.screen.query_one("#detail-content", Static).render()
            )
            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.click("#confirm")
            await settle(app, pilot)
            assert (
                tmp_path / "Downloads" / "[bold]notes.txt"
            ).read_text() == "Hello from the bot.\n"
            assert notices[-1].startswith("Saved to ")
            app.read_only = True
            await pilot.press("s")
            assert notices[-1] == "Read-only mode" and isinstance(
                app.screen, DetailPanel
            )
            await pilot.press("escape", "escape")
            run(ctx, "/files")
            await settle(app, pilot)
            assert isinstance(app.screen, ListPanel)
            await pilot.press("s")
            assert notices[-1] == "Read-only mode"
            await pilot.press("down", "down")
            service.transport.commands["readAttachmentText"] = {
                "kind": "text",
                "bytes": 3,
                "text": "abc",
                "truncated": True,
            }
            await pilot.press("enter")
            await settle(app, pilot)
            assert "(truncated)" in str(
                app.screen.query_one("#detail-content", Static).render()
            )
            await pilot.press("escape")
            service.transport.commands["readAttachmentText"] = {
                "kind": "binary",
                "bytes": 1024,
            }
            await pilot.press("enter")
            await settle(app, pilot)
            assert "Binary file · 1 KB · s to save" in str(
                app.screen.query_one("#detail-content", Static).render()
            )
            await pilot.press("escape", "escape")
            await history.reset_entries([])
            run(ctx, "/files")
            await settle(app, pilot)
            assert "No files in the loaded messages · pgup loads earlier ones" in str(
                app.screen.query_one("#panel-rows", Static).render()
            )

    asyncio.run(exercise())


def test_attachment_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.state.transcripts["demo-helper"] = file_entries()[:2]
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            screen = SessionScreen("demo-helper", bot_name="Helper")
            await app.push_screen(screen)
            await settle(app, pilot)
            screen.attachments[:] = [
                Attachment("/a", "report.pdf"),
                Attachment("/b", "notes.txt"),
            ]
            screen.refresh_attachments()
            await assert_snapshot(app, pilot, "session-attachments")
            run(SlashContext(app, screen, screen.bot_id, None), "/files")
            await settle(app, pilot)
            await assert_snapshot(app, pilot, "panel-files")

    asyncio.run(exercise())


def test_ascii_hostile_file_name():
    entry = Entry.from_raw(
        "bot", dict(file_entries()[0], file_name="[link=x]evil.txt\x1b[31m")
    )
    assert entry is not None
    widget = entry_widget(entry, ASCII)
    assert isinstance(widget, Static)
    rendered = str(widget.content)
    assert "> + [link=x]evil.txt" in rendered and "\x1b" not in rendered
