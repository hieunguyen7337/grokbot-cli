import asyncio
from dataclasses import replace
from threading import Event

import pytest
from textual.widgets import Input, Static
from tui_snapshots import assert_snapshot

from gbot.output import terminal_safe
from gbot.service import events
from gbot.service.fake import load_fake
from gbot.service.models import Entry, SendResult, TranscriptPage
from gbot.tui.app import GbotApp
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.widgets.prompt import CardPrompt
from gbot.tui.widgets.transcript import BotEntry, NewEntries, Transcript, UserEntry


@pytest.fixture(autouse=True)
def session_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr("gbot.tui.screens.home.time", lambda: 1_800_000_000)


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


def test_follow_before_open_and_unfollow(monkeypatch):
    async def exercise():
        service = load_fake()
        source = service.event_source()
        monkeypatch.setattr(service, "event_source", lambda: source)
        original = service.open

        def opened(bot_id, **kwargs):
            assert (bot_id, kwargs["session_id"]) in source.followed
            return original(bot_id, **kwargs)

        monkeypatch.setattr(service, "open", opened)
        app = GbotApp(service, bot="Helper", animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            assert source.followed == {("demo-helper", None)}
            await pilot.press("escape")
            await pilot.pause()
            assert not source.followed and not app._followed

    asyncio.run(exercise())


def test_late_source_follows_queued_events_and_open_stack(monkeypatch):
    async def exercise():
        service = load_fake()
        source = service.event_source()
        entered, release = Event(), Event()

        def delayed_source():
            entered.set()
            assert release.wait(5)
            return source

        monkeypatch.setattr(service, "event_source", delayed_source)
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            assert await asyncio.to_thread(entered.wait, 2)
            main = SessionScreen("demo-helper")
            other = SessionScreen("demo-helper", session_id="s1")
            await app.push_screen(main)
            await app.push_screen(other)
            entry = Entry("demo-helper", "queued", 101, "send-message", text="queued")
            app._receive_event(events.EntryAdded(entry))
            app._receive_event(events.EntryAdded(replace(entry, session_id="s1")))
            await pilot.pause()
            assert not app._loaded
            release.set()
            await settle(app, pilot)
            assert source.followed == {("demo-helper", None), ("demo-helper", "s1")}
            assert "queued" in main.query_one(Transcript).entries
            assert "queued" in other.query_one(Transcript).entries
            service.set_box("demo-helper", "running")
            await settle(app, pilot)
            for screen in (main, other):
                assert "computer running" in str(
                    screen.query_one("#session-status", Static).render()
                )
            await pilot.press("escape")
            await pilot.pause()
            assert source.followed == {("demo-helper", None)}

    asyncio.run(exercise())


def test_follow_errors_are_service_errors(monkeypatch):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        errors = []
        monkeypatch.setattr(app, "service_error", errors.append)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            source = service._sources[0]

            def failed(*args):
                raise ValueError("source failed")

            monkeypatch.setattr(source, "follow", failed)
            monkeypatch.setattr(source, "unfollow", failed)
            app.follow("demo-helper")
            app.unfollow("demo-helper")
            assert [str(error) for error in errors] == [
                "source failed",
                "source failed",
            ]
            assert not app._followed

    asyncio.run(exercise())


@pytest.mark.parametrize("session_id", [None, "s1"])
def test_send_and_live_reply(monkeypatch, session_id):
    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        acted = []
        monkeypatch.setattr(app, "user_acted", lambda: acted.append(True))
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            screen = SessionScreen("demo-helper", session_id=session_id)
            await app.push_screen(screen)
            await settle(app, pilot)
            field = screen.query_one(Input)
            field.value = "  hello  "
            await pilot.press("enter")
            await settle(app, pilot)
            assert service.sent == [("demo-helper", "hello", session_id)]
            assert field.value == "" and acted
            assert "working" in str(
                screen.query_one("#session-status", Static).render()
            )
            history = screen.query_one(Transcript)
            # FakeService emits main-session entries even for sends to a named session.
            sent = [w for w in history.query(UserEntry) if "hello" in str(w.render())]
            assert len(sent) == (1 if session_id is None else 0)
            service.reply("demo-helper", "A live reply")
            await settle(app, pilot)
            replies = [w for w in history.query(BotEntry) if w.text == "A live reply"]
            assert len(replies) == (1 if session_id is None else 0)
            assert "new reply" in str(
                screen.query_one("#session-status", Static).render()
            )
            assert not history.new_count

    asyncio.run(exercise())


def test_send_failure_nonce_and_in_flight(monkeypatch):
    async def exercise():
        service = load_fake()
        send = service.send
        calls = []
        entered, release = Event(), Event()

        def flaky(bot_id, text, **kwargs):
            calls.append(kwargs["nonce"])
            if len(calls) == 1:
                raise ValueError("[link=x]\x1b[31m offline")
            entered.set()
            assert release.wait(5)
            return send(bot_id, text, **kwargs)

        monkeypatch.setattr(service, "send", flaky)
        app = GbotApp(service, bot="Helper", animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            screen = app.screen
            assert isinstance(screen, SessionScreen)
            field = screen.query_one(Input)
            await pilot.press("enter")
            assert not calls
            field.value = "retry me"
            await pilot.press("enter")
            await settle(app, pilot)
            assert field.value == "retry me"
            notice = screen.query_one("#session-notice", Static)
            assert terminal_safe("[link=x]\x1b[31m offline") in str(notice.render())
            assert "demo-helper" in app.state.errors
            await pilot.press("enter")
            assert await asyncio.to_thread(entered.wait, 2)
            assert "Sending…" in str(notice.render())
            await pilot.press("enter", "enter")
            assert len(calls) == 2 and calls[0] == calls[1]
            release.set()
            await settle(app, pilot)
            assert not field.value and not str(notice.content)
            assert "demo-helper" not in app.state.errors
            assert len(service.sent) == 1
            field.value = "different"
            await pilot.press("enter")
            await settle(app, pilot)
            assert calls[2] != calls[1]

    asyncio.run(exercise())


def test_unaccepted_send_and_changed_retry(monkeypatch):
    async def exercise():
        service = load_fake()
        calls = []

        def refused(bot_id, text, **kwargs):
            calls.append(kwargs["nonce"])
            return SendResult(False, kwargs["nonce"])

        monkeypatch.setattr(service, "send", refused)
        app = GbotApp(service, bot="Helper", animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            field = app.screen.query_one(Input)
            field.value = "first"
            await pilot.press("enter")
            await settle(app, pilot)
            assert field.value == "first"
            assert "Message was not accepted" in str(
                app.screen.query_one("#session-notice", Static).render()
            )
            field.value = "changed"
            await pilot.press("enter")
            await settle(app, pilot)
            assert calls[0] != calls[1]
            assert not service.sent

    asyncio.run(exercise())


def test_keyed_events_and_reset_paging(monkeypatch):
    async def exercise():
        service = load_fake()
        source = service.event_source()
        monkeypatch.setattr(service, "event_source", lambda: source)
        pages = []

        def transcript(bot_id, **kwargs):
            pages.append(kwargs["before_seq"])
            return TranscriptPage(())

        monkeypatch.setattr(service, "transcript", transcript)
        app = GbotApp(service, bot="Helper", animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            screen = app.screen
            assert isinstance(screen, SessionScreen)
            history = screen.query_one(Transcript)
            ids = list(history.entries)
            original = service.open("demo-helper").entries[0]
            source.push(
                events.EntryChanged(replace(original, text="streamed", streaming=True))
            )
            await settle(app, pilot)
            assert list(history.entries) == ids
            assert "streamed" in str(history.entries[original.id].render())
            extra = Entry("demo-helper", "extra", 99, "send-message", text="new")
            for event in (
                events.EntryAdded(extra),
                events.EntryAdded(replace(extra, text="backfill")),
                events.EntryChanged(replace(extra, id="unknown", text="unknown")),
                events.EntryAdded(replace(extra, id="foreign", bot_id="demo-inbox")),
                events.EntryChanged(replace(extra, id="foreign", session_id="s1")),
                events.EntryRemoved("demo-helper", "s1", original.id),
                events.TranscriptReset("demo-inbox", None),
            ):
                source.push(event)
            await settle(app, pilot)
            assert list(history.entries) == [*ids, "extra", "unknown"]
            widget = history.entries["extra"]
            assert isinstance(widget, BotEntry) and widget.text == "backfill"
            assert len(history.children) == len(history.entries) + 1
            source.push(events.EntryRemoved("demo-helper", None, "extra"))
            await settle(app, pilot)
            assert "extra" not in history.entries
            source.push(events.TranscriptReset("demo-helper", None, (extra,)))
            await settle(app, pilot)
            assert list(history.entries) == ["extra"]
            assert screen.next_before_seq == 99
            await pilot.press("pageup")
            await settle(app, pilot)
            assert pages == [99]
            for entries in ((replace(extra, seq=1),), ()):
                source.push(events.TranscriptReset("demo-helper", None, entries))
                await settle(app, pilot)
                assert screen.next_before_seq is None
                assert len(history.entries) == len(entries)
                await pilot.press("pageup")
            assert pages == [99]

    asyncio.run(exercise())


def test_events_buffered_before_open(monkeypatch):
    async def exercise():
        service = load_fake()
        source = service.event_source()
        monkeypatch.setattr(service, "event_source", lambda: source)
        opened = service.open
        entered, release = Event(), Event()

        def blocked(bot_id, **kwargs):
            page = opened(bot_id, **kwargs)
            entered.set()
            assert release.wait(5)
            return page

        monkeypatch.setattr(service, "open", blocked)
        app = GbotApp(service, bot="Helper", animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            assert await asyncio.to_thread(entered.wait, 2)
            entry = Entry("demo-helper", "early", 20, "send-message", text="first")
            source.push(events.TranscriptReset("demo-helper", None, (entry,)))
            source.push(events.EntryChanged(replace(entry, text="second")))
            source.push(events.EntryAdded(replace(entry, id="removed")))
            source.push(events.EntryRemoved("demo-helper", None, "removed"))
            await pilot.pause()
            assert not app.screen.query_one(Transcript).entries
            release.set()
            await settle(app, pilot)
            history = app.screen.query_one(Transcript)
            assert list(history.entries) == ["early"]
            widget = history.entries["early"]
            assert isinstance(widget, BotEntry) and widget.text == "second"

    asyncio.run(exercise())


def test_live_events_during_earlier_page_and_stale_reset(monkeypatch):
    async def exercise():
        service = load_fake()
        entered, release = Event(), Event()
        old = Entry("demo-helper", "old", 49, "notice", text="stale history")

        def blocked(bot_id, **kwargs):
            entered.set()
            assert release.wait(5)
            return TranscriptPage((old,))

        monkeypatch.setattr(service, "transcript", blocked)
        app = GbotApp(service, bot="Helper", animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            screen = app.screen
            assert isinstance(screen, SessionScreen)
            entry = replace(old, id="current", seq=50)
            service._emit(events.TranscriptReset("demo-helper", None, (entry,)))
            await settle(app, pilot)
            await pilot.press("pageup")
            assert await asyncio.to_thread(entered.wait, 2)
            service._emit(events.EntryAdded(replace(entry, id="live", seq=51)))
            await pilot.pause()
            history = screen.query_one(Transcript)
            assert "live" in history.entries
            service._emit(events.TranscriptReset("demo-helper", None))
            await pilot.pause()
            assert not history.entries and screen.next_before_seq is None
            release.set()
            await settle(app, pilot)
            assert not history.entries

    asyncio.run(exercise())


@pytest.mark.parametrize("ascii_only", [False, True])
def test_new_pill_and_latest(ascii_only):
    async def exercise():
        service = load_fake()
        service.state.transcripts["demo-helper"] = [
            {"id": str(n), "seq": n, "kind": "notice", "text": f"History line {n}"}
            for n in range(1, 61)
        ]
        app = GbotApp(service, bot="Helper", animate=False, ascii_only=ascii_only)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            history = app.screen.query_one(Transcript)
            assert history.at_bottom
            service.reply("demo-helper", "Pinned reply")
            await settle(app, pilot)
            assert history.at_bottom and not history.query(NewEntries)
            history.scroll_to(y=10, animate=False, immediate=True)
            await pilot.pause()
            service.reply("demo-helper", "First unseen reply")
            service.reply("demo-helper", "Second unseen reply")
            await settle(app, pilot)
            assert history.new_count == 2 and history.scroll_y == 10
            assert str(history.pill.content) == f"2 new {'v' if ascii_only else '↓'}"
            if not ascii_only:
                await assert_snapshot(app, pilot, "session-live-pill")
            field = app.screen.query_one(Input)
            field.value = "editing"
            await pilot.press("end")
            assert history.new_count == 2
            field.value = ""
            await pilot.press("end")
            await pilot.pause()
            assert history.at_bottom and not history.new_count
            assert not history.query(NewEntries)
            for click in (True, False):
                history.scroll_to(y=10, animate=False, immediate=True)
                await pilot.pause()
                service.reply("demo-helper", "Another unseen reply")
                await settle(app, pilot)
                assert history.new_count == 1
                if click:
                    await pilot.click(NewEntries)
                else:
                    history.scroll_end(animate=False, immediate=True)
                await pilot.pause()
                assert history.at_bottom and not history.new_count
                assert not history.query(NewEntries)
            tail = service.open("demo-helper").entries[-1]
            service._emit(
                events.EntryChanged(
                    replace(
                        tail, text="\n\n".join(["Growing reply"] * 30), streaming=True
                    )
                )
            )
            await settle(app, pilot)
            assert history.at_bottom and not history.new_count
            history.scroll_to(y=history.max_scroll_y - 1, animate=False, immediate=True)
            service.reply("demo-helper", "Within one line of the bottom")
            await settle(app, pilot)
            assert history.at_bottom and not history.new_count

    asyncio.run(exercise())


def test_planner_prompt_focus_and_answer():
    async def exercise():
        service = load_fake()
        app = GbotApp(service, bot="Planner", animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            screen = app.screen
            assert isinstance(screen, SessionScreen)
            prompt = screen.query_one(CardPrompt)
            assert prompt.has_focus and not service.answered
            screen.refresh_state()
            assert screen.query_one(CardPrompt) is prompt
            await assert_snapshot(app, pilot, "session-live-prompt")
            await pilot.press("tab")
            assert screen.query_one(Input).has_focus
            await pilot.press("tab")
            assert prompt.has_focus
            prompt.post_message(CardPrompt.Later(prompt.card))
            await pilot.pause()
            assert screen.query_one(Input).has_focus
            assert screen.query_one(CardPrompt) is prompt
            await pilot.press("tab", "2")
            await settle(app, pilot)
            assert service.answered[-1][2].value == "City Loft"
            assert not isinstance(app.screen, ConfirmScreen)
            assert not screen.query(CardPrompt)
            assert screen.query_one(Input).has_focus
            assert "tab prompt" not in str(
                screen.query_one("#session-footer", Static).render()
            )

    asyncio.run(exercise())


def test_card_arriving_mid_sentence_keeps_composer_focus():
    async def exercise():
        service = load_fake()
        app = GbotApp(service, bot="Planner", animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            screen = app.screen
            assert isinstance(screen, SessionScreen)
            composer = screen.query_one("#session-input", Input)
            card = app.state.cards["demo-planner"][0]

            async def set_cards(cards):
                app.state.cards["demo-planner"] = cards
                app.refresh_home()
                await pilot.pause()

            await set_cards([])
            assert composer.has_focus
            await pilot.press("1")
            await set_cards([card])
            assert screen.query(CardPrompt)
            assert composer.has_focus
            await pilot.press("2")
            assert composer.value == "12" and not service.answered
            composer.value = ""
            await set_cards([])
            await set_cards([card])
            assert isinstance(app.focused, CardPrompt)

    asyncio.run(exercise())


def test_draft_confirm_cancel_and_session_filter():
    async def exercise():
        service = load_fake()
        app = GbotApp(service, bot="Inbox", animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            screen = app.screen
            await pilot.press("1")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.click("#cancel")
            await settle(app, pilot)
            assert not service.answered and screen.query(CardPrompt)
            card = app.state.cards["demo-inbox"][0]
            app.state.cards["demo-inbox"] = [replace(card, session_id="s1")]
            app.refresh_home()
            await pilot.pause()
            assert not screen.query(CardPrompt)
            await app.push_screen(SessionScreen("demo-inbox", session_id="s1"))
            await settle(app, pilot)
            assert app.screen.query_one(CardPrompt).card.session_id == "s1"

    asyncio.run(exercise())


def test_hostile_stream_and_box_state():
    async def exercise():
        service = load_fake()
        app = GbotApp(service, bot="Helper", animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            service.reply("demo-helper", "[link=x]\x1b[31m literal")
            service.set_box("demo-helper", "running")
            await settle(app, pilot)
            assert any("[link=x]" in w.text for w in app.screen.query(BotEntry))
            svg = app.export_screenshot()
            assert "[link=x]" in svg and "\\u001b[31m" in svg
            assert "\x1b" not in svg and 'href="x"' not in svg
            status = app.screen.query_one("#session-status", Static)
            assert "computer running" in str(status.render())
            service.set_box("demo-inbox", "hibernated")
            await settle(app, pilot)
            assert "computer running" in str(status.render())

    asyncio.run(exercise())
