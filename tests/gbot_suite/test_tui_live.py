import asyncio
import threading
import time

import pytest

from gbot import cli, context
from gbot.commands import tui
from gbot.service.errors import SignedOutError
from gbot.service.fake import FakeService
from gbot.service.hub import EventHub
from gbot.service.transport import FakeTransport
from gbot.tui.app import GbotApp


@pytest.fixture
def home_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize("bot", [None, "Planner"])
def test_live_screenshot(home_env, monkeypatch, bot):
    service = FakeService()
    closed, calls = [], []
    original = service.transcript
    original_close = service.close

    def close():
        closed.append(True)
        original_close()

    def transcript(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("Screenshot attempted a write")

    monkeypatch.setattr(service, "open", forbidden)
    monkeypatch.setattr(service, "send", forbidden)
    monkeypatch.setattr(service, "answer", forbidden)
    monkeypatch.setattr(service, "transcript", transcript)
    monkeypatch.setattr(service, "close", close)
    monkeypatch.setattr(context, "service_factory", lambda: service)
    path = home_env / "home.svg"
    args = ["tui", "--screenshot", str(path)]
    if bot:
        args.extend(["--bot", bot])
    assert cli.main(args) == 0
    svg = path.read_text(encoding="utf-8")
    assert ("Planner" if bot else "Grok&#160;Bot") in svg
    assert closed == [True]
    assert not service.sent and not service.answered
    if bot:
        assert calls and calls[0][1]["limit"] == 200
    else:
        assert calls == []


def test_screenshot_deadline(home_env, monkeypatch, capsys):
    release = threading.Event()

    class BlockedService(FakeService):
        def roster(self):
            release.wait()
            return []

        def close(self):
            release.set()
            super().close()

    monkeypatch.setattr(context, "service_factory", BlockedService)
    monkeypatch.setattr(tui, "SCREENSHOT_TIMEOUT", 0.5)
    path = home_env / "loading.svg"
    started = time.monotonic()
    assert cli.main(["tui", "--screenshot", str(path)]) == 1
    assert time.monotonic() - started < 3
    assert path.is_file()
    assert "gbot tui: still loading after 20 s" in capsys.readouterr().err
    assert release.is_set()


def test_signed_out(home_env, monkeypatch, capsys):
    def signed_out():
        raise SignedOutError("signed out")

    monkeypatch.setattr(context, "service_factory", signed_out)
    assert cli.main(["tui"]) == 3
    assert "gbot login" in capsys.readouterr().err


def test_quit_unblocks_event_hub(home_env, monkeypatch):
    reading, closed = threading.Event(), threading.Event()

    class Feed:
        def next_frame(self, timeout_s):
            reading.set()
            closed.wait()
            raise EOFError

        def close(self):
            closed.set()

    class Opener:
        def open_stream(self):
            return Feed()

    service = FakeService()
    hub = EventHub(Opener(), FakeTransport({"listAgents": {"agents": []}}))
    monkeypatch.setattr(service, "event_source", lambda: hub)
    closes = []

    def close():
        closes.append(True)
        hub.close()

    monkeypatch.setattr(service, "close", close)
    monkeypatch.setattr(context, "service_factory", lambda: service)
    started = 0.0

    async def exercise(app):
        nonlocal started
        async with app.run_test() as pilot:
            deadline = time.monotonic() + 2
            while not reading.is_set():
                assert time.monotonic() < deadline
                await pilot.pause()
            started = time.monotonic()
            app.action_palette_quit()

    monkeypatch.setattr(GbotApp, "run", lambda self: asyncio.run(exercise(self)))
    assert cli.main(["tui"]) == 0
    assert time.monotonic() - started < 2
    assert closed.is_set() and closes == [True]
