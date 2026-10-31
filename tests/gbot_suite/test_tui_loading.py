import asyncio
import re
import threading
from time import monotonic
from typing import cast

import pytest
from textual.widgets import Static

from gbot.service.api import Service
from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.screens.home import progress_text
from gbot.tui.screens.session import SessionScreen
from gbot.tui.widgets.transcript import Transcript

# Home keeps a two-column gutter on each side of an 80-column terminal.
MAX_LINE = 76


@pytest.fixture
def home_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    return tmp_path


def home_progress(app: GbotApp) -> str:
    line = app.home.query_one("#home-progress", Static)
    return str(line.render()) if line.display else ""


async def wait_until(pilot, condition, message: str) -> None:
    deadline = monotonic() + 5
    while not condition():
        assert monotonic() < deadline, f"timed out waiting for {message}"
        await pilot.pause()


def text(stage, *, ascii_only: bool, **options) -> str:
    values = {"elapsed": 0, "done": 0, "total": 0, "frame": 0, "animate": False}
    values.update(options)
    return progress_text(stage, ascii_only=ascii_only, **values)


@pytest.mark.parametrize("ascii_only", [False, True])
def test_progress_text_shapes(ascii_only):
    assert text(None, ascii_only=ascii_only) == ""
    early = text("connecting", ascii_only=ascii_only, elapsed=4)
    late = text("connecting", ascii_only=ascii_only, elapsed=12)
    assert "Connecting to Grok Bot... 4 s" in early
    assert "starting your cloud computer" not in early
    assert "Connecting to Grok Bot... 12 s" in late
    assert "starting your cloud computer can take about 30 s" in late
    assert "Loading bots..." in text("loading", ascii_only=ascii_only)
    sweeping = text("sweeping", ascii_only=ascii_only, done=5, total=16)
    assert "Checking for cards 5/16" in sweeping
    assert sweeping.count("[") == 1 and sweeping.count("]") == 1
    lines = [
        *late.splitlines(),
        *sweeping.splitlines(),
        *text("loading", ascii_only=ascii_only).splitlines(),
        *text("sweeping", ascii_only=ascii_only, done=999, total=999).splitlines(),
    ]
    assert all(len(line) <= MAX_LINE for line in lines)
    if ascii_only:
        assert all(
            text(stage, ascii_only=True, done=5, total=16, elapsed=12).isascii()
            for stage in ("connecting", "loading", "sweeping")
        )


def test_spinner_is_static_without_animation_or_ascii():
    def spinner(**options) -> set[str]:
        return {
            text("loading", **options, frame=frame).split(" ", 1)[0]
            for frame in range(6)
        }

    assert len(spinner(ascii_only=False, animate=False)) == 1
    assert len(spinner(ascii_only=False, animate=True)) == 6
    assert len(spinner(ascii_only=True, animate=True)) == 1


@pytest.mark.parametrize("ascii_only", [False, True])
def test_connecting_line_until_roster(home_env, ascii_only):
    async def exercise():
        service = load_fake()
        original = service.roster
        release = threading.Event()

        def roster():
            release.wait(5)
            return original()

        service.roster = roster
        app = GbotApp(service, ascii_only=ascii_only, animate=False)
        try:
            async with app.run_test() as pilot:
                await wait_until(
                    pilot,
                    lambda: "Connecting to Grok Bot" in home_progress(app),
                    "the connecting line",
                )
                shown = home_progress(app)
                assert re.search(r"Connecting to Grok Bot\.\.\. \d+ s", shown), shown
                assert shown.isascii() == ascii_only
                release.set()
                await wait_until(pilot, lambda: app.settled, "the load to settle")
                await pilot.pause()
                assert home_progress(app) == ""
        finally:
            release.set()

    asyncio.run(exercise())


def test_loading_bots_line_while_initial_checks_run(home_env):
    async def exercise():
        service = load_fake()
        original = service.pending
        release = threading.Event()

        def pending(bot_ids=None, *, bots=None):
            if bot_ids is None:
                release.wait(5)
            return original(bot_ids) if bots is None else original(bot_ids, bots=bots)

        service.pending = pending
        app = GbotApp(service, animate=False)
        try:
            async with app.run_test() as pilot:
                await wait_until(
                    pilot,
                    lambda: "Loading bots..." in home_progress(app),
                    "the loading line",
                )
                release.set()
                await wait_until(pilot, lambda: app.settled, "the load to settle")
                await pilot.pause()
                assert home_progress(app) == ""
        finally:
            release.set()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "ascii_only,loading", [(False, "Loading…"), (True, "Loading...")]
)
def test_session_shows_loading_until_first_page(home_env, ascii_only, loading):
    async def exercise():
        service = load_fake()
        original = service.open
        release = threading.Event()

        def open(bot_id, *, session_id=None, limit=200):
            release.wait(5)
            return original(bot_id, session_id=session_id, limit=limit)

        service.open = open
        app = GbotApp(
            cast(Service, service), bot="Inbox", ascii_only=ascii_only, animate=False
        )
        try:
            async with app.run_test() as pilot:
                await wait_until(
                    pilot,
                    lambda: isinstance(app.screen, SessionScreen),
                    "the session screen",
                )
                screen = cast(SessionScreen, app.screen)
                marker = screen.query_one(Transcript).marker
                assert str(marker.render()) == loading
                release.set()
                await wait_until(pilot, lambda: screen.loaded, "the first page")
                await pilot.pause()
                assert "Loading" not in str(marker.render())
        finally:
            release.set()

    asyncio.run(exercise())


def test_peek_shows_loading_until_first_page(home_env):
    async def exercise():
        service = load_fake()
        original = service.transcript
        release = threading.Event()

        def transcript(bot_id, *, before_seq=None, limit=50, session_id=None):
            # Peek reads 8 entries; the session screen reads other sizes.
            if limit == 8:
                release.wait(5)
            return original(
                bot_id, before_seq=before_seq, limit=limit, session_id=session_id
            )

        service.transcript = transcript
        app = GbotApp(service, animate=False)
        try:
            async with app.run_test() as pilot:
                await wait_until(pilot, lambda: app.settled, "the home list")
                await pilot.press("space")
                peek = app.home.peek
                await wait_until(
                    pilot,
                    lambda: len(peek.query(".peek-loading")) == 1,
                    "the peek loading line",
                )
                loading = peek.query_one(".peek-loading", Static)
                assert str(loading.render()) == "Loading…"
                release.set()
                await wait_until(
                    pilot,
                    lambda: len(peek.query(".peek-loading")) == 0,
                    "the peek first page",
                )
        finally:
            release.set()

    asyncio.run(exercise())
