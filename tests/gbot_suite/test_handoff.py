import asyncio
from io import StringIO
from threading import Event
from unittest.mock import Mock

import pytest
from textual.widgets import Static
from tui_snapshots import assert_snapshot

from gbot.handoff import run_handoff
from gbot.output import terminal_safe
from gbot.service import events
from gbot.service.fake import load_fake
from gbot.service.handoff import HandoffResult, wait_until
from gbot.tui.app import GbotApp, ServiceEvent
from gbot.tui.screens.handoff import HandoffScreen

URL = "https://example.test/connect?step=1"


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeEvent(Event):
    def __init__(self, clock, on_wait=None):
        super().__init__()
        self.clock = clock
        self.flag = False
        self.waits = []
        self.on_wait = on_wait

    def is_set(self):
        return self.flag

    def set(self):
        self.flag = True

    def clear(self):
        self.flag = False

    def wait(self, timeout=None):
        assert timeout is not None
        self.waits.append(timeout)
        if self.on_wait:
            self.on_wait()
        if not self.flag:
            self.clock.now += timeout
        return self.flag


def test_wait_first_done_and_exception():
    clock = FakeClock()
    cancel = FakeEvent(clock)
    assert wait_until(lambda: False, cancel=cancel, wake=None, clock=clock) == (
        HandoffResult("done", False)
    )
    assert cancel.waits == []
    with pytest.raises(ValueError, match="offline"):
        wait_until(
            Mock(side_effect=ValueError("offline")),
            cancel=cancel,
            wake=None,
            clock=clock,
        )


def test_wait_backoff_and_timeout():
    clock = FakeClock()
    cancel = FakeEvent(clock)
    check = Mock(side_effect=[None] * 6 + ["complete"])
    assert wait_until(check, cancel=cancel, wake=None, clock=clock) == (
        HandoffResult("done", "complete")
    )
    assert cancel.waits == [1, 2, 3, 5, 5, 5]
    cancel.waits.clear()
    assert wait_until(
        lambda: None, cancel=cancel, wake=None, timeout_s=2.5, clock=clock
    ) == HandoffResult("timeout")
    assert cancel.waits == [1, 1.5]


def test_wait_cancel_and_wake():
    clock = FakeClock()
    cancel = FakeEvent(clock)
    wake = FakeEvent(clock, cancel.set)
    check = Mock(return_value=None)
    assert wait_until(check, cancel=cancel, wake=wake, clock=clock) == (
        HandoffResult("cancelled")
    )
    assert check.call_count == 1
    cancel.clear()
    wake = FakeEvent(clock)
    wake.on_wait = wake.set
    check = Mock(side_effect=[None, "ready"])
    start = clock()
    assert wait_until(check, cancel=cancel, wake=wake, clock=clock) == (
        HandoffResult("done", "ready")
    )
    assert clock() == start
    assert not wake.is_set()


def test_cli_handoff():
    err, opener = StringIO(), Mock()
    assert run_handoff(URL, lambda: "ready", err=err, opener=opener) == (
        HandoffResult("done", "ready")
    )
    assert err.getvalue() == f"Open this link to continue:\n{URL}\n"
    opener.assert_called_once_with(URL)
    opener.reset_mock()
    assert (
        run_handoff(
            URL, lambda: True, err=err, opener=opener, open_browser=False
        ).status
        == "done"
    )
    opener.assert_not_called()
    assert run_handoff(
        URL,
        Mock(side_effect=KeyboardInterrupt),
        err=err,
        opener=opener,
    ) == HandoffResult("cancelled")


@pytest.fixture(autouse=True)
def session_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr("gbot.tui.screens.home.time", lambda: 1_800_000_000)


async def ready(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


@pytest.mark.parametrize("close", ["escape", "unmount"])
def test_screen_waiting_copy_cancel_snapshot(monkeypatch, close):
    stopped = Event()

    def tracked_wait(check, **kwargs):
        try:
            return wait_until(check, **kwargs)
        finally:
            stopped.set()

    monkeypatch.setattr("gbot.tui.screens.handoff.wait_until", tracked_wait)

    async def exercise():
        app = GbotApp(load_fake(), animate=False)
        opener, check, result = Mock(return_value=True), Mock(return_value=None), Mock()
        copy, notice = Mock(), Mock()
        monkeypatch.setattr(app, "copy_to_clipboard", copy)
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            await ready(app, pilot)
            screen = HandoffScreen("Connect account", URL, check, opener=opener)
            await app.push_screen(screen, result)
            await pilot.pause()
            opener.assert_called_once_with(URL)
            await assert_snapshot(app, pilot, "handoff-waiting")
            await pilot.press("c")
            copy.assert_called_once_with(URL)
            notice.assert_called_with("Link copied", markup=False)
            if close == "escape":
                await pilot.press("escape")
            else:
                await app.pop_screen()
            await ready(app, pilot)
            if close == "escape":
                result.assert_called_once_with(HandoffResult("cancelled"))
            assert screen.cancel.is_set()
            assert await asyncio.to_thread(stopped.wait, 1)
            assert all(worker.is_finished for worker in screen.workers)

    asyncio.run(exercise())


def test_screen_done_on_mount():
    async def exercise():
        app = GbotApp(load_fake(), animate=False)
        opener, result = Mock(return_value=True), Mock()
        async with app.run_test() as pilot:
            await ready(app, pilot)
            await app.push_screen(
                HandoffScreen("Connect", URL, lambda: {"ok": True}, opener=opener),
                result,
            )
            await ready(app, pilot)
            opener.assert_called_once_with(URL)
            result.assert_called_once_with(HandoffResult("done", {"ok": True}))

    asyncio.run(exercise())


def test_screen_service_event_wakes_every_handoff(monkeypatch):
    def long_wait(check, **kwargs):
        return wait_until(check, intervals=(3600.0,), **kwargs)

    monkeypatch.setattr("gbot.tui.screens.handoff.wait_until", long_wait)

    async def exercise():
        app = GbotApp(load_fake(), animate=False)
        complete = Event()
        checked = Event()
        result = Mock()

        def check():
            checked.set()
            return "ready" if complete.is_set() else None

        async with app.run_test() as pilot:
            await ready(app, pilot)
            lower = HandoffScreen("Lower", URL, lambda: None, opener=Mock())
            await app.push_screen(lower)
            screen = HandoffScreen("Connect", URL, check, opener=Mock())
            await app.push_screen(screen, result)
            await pilot.pause()
            assert checked.is_set()
            # Freeze the backoff at an hour: only a service event can complete it.
            complete.set()
            poke = Mock(wraps=lower.poke)
            lower.poke = poke
            app.post_message(ServiceEvent(events.Other("test", {})))
            await pilot.pause()
            result.assert_called_once_with(HandoffResult("done", "ready"))
            poke.assert_called_once()
            await pilot.press("escape")
            await ready(app, pilot)

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", [False, OSError("browser failed")])
def test_screen_opener_failure(failure):
    async def exercise():
        app = GbotApp(load_fake(), animate=False)
        opener = Mock(side_effect=failure) if failure else Mock(return_value=False)
        async with app.run_test() as pilot:
            await ready(app, pilot)
            screen = HandoffScreen("Connect", URL, lambda: None, opener=opener)
            await app.push_screen(screen)
            await pilot.pause()
            assert "Could not open a browser; copy the link instead." in str(
                screen.query_one("#handoff-status", Static).render()
            )
            await pilot.press("escape")
            await ready(app, pilot)

    asyncio.run(exercise())


@pytest.mark.parametrize("error", [None, ValueError("offline\x1b[31m[bold]")])
def test_screen_timeout_or_error_then_retry(error):
    async def exercise():
        app = GbotApp(load_fake(), animate=False)
        check = Mock(side_effect=error) if error else Mock(return_value=None)
        opener, result = Mock(return_value=True), Mock()
        async with app.run_test() as pilot:
            await ready(app, pilot)
            screen = HandoffScreen("Connect", URL, check, timeout_s=0, opener=opener)
            await app.push_screen(screen, result)
            await ready(app, pilot)
            text = str(screen.query_one("#handoff-status", Static).render())
            assert (
                terminal_safe(str(error))
                if error
                else "Timed out waiting; press o to try again or esc to close."
            ) in text
            check.side_effect = None
            check.return_value = "retried"
            await pilot.press("o")
            await ready(app, pilot)
            assert opener.call_count == 2
            result.assert_called_once_with(HandoffResult("done", "retried"))

    asyncio.run(exercise())
