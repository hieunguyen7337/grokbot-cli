import asyncio
import threading
from dataclasses import replace

import pytest

from gbot import cli, context
from gbot.commands import tui
from gbot.service import events
from gbot.service.fake import load_fake
from gbot.service.models import Bot
from gbot.tui import app as app_module
from gbot.tui.app import GbotApp, ServiceEvent
from gbot.tui.model import RowState, build_rows
from gbot.tui.widgets.botlist import MoreLine
from groken.client import ConnectError


@pytest.fixture
def home_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    return tmp_path


def sweep_service():
    service = load_fake()
    original = service.pending
    service.state.rows[0]["awaitingUserResponse"] = None
    calls = []

    def pending(bot_ids=None, *, bots=None):
        ids = bot_ids
        calls.append(ids)
        if ids is None:
            ids = [b.id for b in service.roster() if b.awaiting is not None]
        return original(ids)

    service.pending = pending
    return service, calls


@pytest.mark.parametrize(
    "failure", [None, OSError("offline"), ConnectError(401, "expired")]
)
def test_sweep(home_env, monkeypatch, failure):
    async def exercise():
        service, calls = sweep_service()
        ids = [b.id for b in service.roster() if b.awaiting is None]
        every = [b.id for b in service.roster()]
        original = service.pending
        first_check: list[list[str]] = []
        if isinstance(failure, ConnectError):
            # One check at a time, so the 401 cut-off is exact; the parallel order is checked below.
            monkeypatch.setattr(app_module, "CARD_SWEEP_PARALLEL", 1)

        def pending(bot_ids=None, *, bots=None):
            selected = bot_ids
            result = original(selected)
            # The first check to start fails; the sweep must start no other check.
            if (
                isinstance(failure, ConnectError)
                and selected is not None
                and not first_check
            ):
                first_check.append(selected)
                raise failure
            if isinstance(failure, OSError) and selected == [ids[1]]:
                raise failure
            return result

        service.pending = pending
        app = GbotApp(service, animate=False)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.settled
            if isinstance(failure, ConnectError):
                assert calls == first_check
            else:
                # Checks run in parallel, so only the set of checks is fixed: each bot once,
                # waiting bots included, and never one call for every bot.
                assert None not in calls
                assert sorted(calls) == sorted([i] for i in every)
                assert (
                    next(r for r in app.home.rows if r.bot_id == ids[0]).state
                    == RowState.NEEDS_INPUT
                )
            if isinstance(failure, OSError):
                assert app.state.errors[ids[1]] == "offline"
                assert (
                    next(r for r in app.home.rows if r.bot_id == ids[1]).badge
                    == "error"
                )

    asyncio.run(exercise())


def test_event_refresh_wins(home_env):
    async def exercise():
        service, _calls = sweep_service()
        original = service.pending
        entered, release = threading.Event(), threading.Event()
        stale = original(["demo-inbox"])

        def pending(bot_ids=None, *, bots=None):
            ids = bot_ids
            if ids == ["demo-inbox"] and not entered.is_set():
                entered.set()
                release.wait(2)
                return stale
            if ids == ["demo-inbox"]:
                return [], []
            return original(ids)

        service.pending = pending
        app = GbotApp(service, animate=False)
        async with app.run_test() as pilot:
            while not entered.is_set():
                await pilot.pause()
            app.on_service_event(ServiceEvent(events.RosterResync("demo-inbox")))
            while "demo-inbox" not in app._cards_refreshed:
                await pilot.pause()
            release.set()
            await app.workers.wait_for_complete()
            assert app.state.cards["demo-inbox"] == []

    asyncio.run(exercise())


@pytest.mark.parametrize("slow", [False, True])
def test_screenshot_sweep(home_env, monkeypatch, capsys, slow):
    service, _ = sweep_service()
    service.state.rows = service.state.rows[:1]
    original = service.pending
    release = threading.Event()
    close = service.close

    def pending(bot_ids=None, *, bots=None):
        ids = bot_ids
        if slow and ids == ["demo-inbox"]:
            release.wait()
        return original(ids)

    def shutdown():
        release.set()
        close()

    service.pending = pending
    monkeypatch.setattr(service, "close", shutdown)
    monkeypatch.setattr(context, "service_factory", lambda: service)
    monkeypatch.setattr(tui, "SCREENSHOT_TIMEOUT", 0.5)
    path = home_env / "sweep.svg"
    assert cli.main(["tui", "--screenshot", str(path)]) == int(slow)
    assert path.is_file()
    if slow:
        assert "gbot tui: still loading after 20 s" in capsys.readouterr().err
    else:
        assert "Needs&#160;input" in path.read_text(encoding="utf-8")


def idle_service():
    service = load_fake()
    service.state.rows = [
        {"id": f"idle-{i:02}", "name": f"Bot-{i:02}"} for i in range(16)
    ]
    service.state.transcripts.clear()
    return service


@pytest.mark.parametrize("click", [False, True])
def test_idle_expansion(home_env, click):
    async def exercise():
        app = GbotApp(idle_service(), animate=False)
        async with app.run_test(size=(100, 16)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            listing = app.home.bot_list
            more_index = next(
                i for i, line in enumerate(listing.lines) if isinstance(line, MoreLine)
            )
            section = listing.sections[0]
            count = len(section.rows)
            listing.selected_id = section.rows[-1].bot_id
            if click:
                await pilot.click("#bot-list", offset=(4, more_index))
            else:
                await pilot.press("down")
            await pilot.pause()
            assert listing.selected_id == f"idle-{count:02}"
            assert len(listing.visible_ids) == 16
            assert not any(isinstance(line, MoreLine) for line in listing.lines)

    asyncio.run(exercise())


def test_idle_large(home_env):
    async def exercise():
        app = GbotApp(idle_service(), animate=False)
        async with app.run_test(size=(120, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            svg = app.export_screenshot()
            assert all(f"Bot-{i:02}" in svg for i in range(16))
            assert not any(
                isinstance(line, MoreLine) for line in app.home.bot_list.lines
            )

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I made [Search 2](grokbot://x) ok", "I made Search 2 ok"),
        ("![alt](https://x)", "alt"),
        ("https://x", "https://x"),
        ("[[link=x]label[/link]](https://x)", "[link=x]label[/link]"),
        ("`code` stays", "`code` stays"),
        ("`[code](url)`", "`[code](url)`"),
    ],
)
def test_summary_labels(text, expected):
    bot = replace(Bot("x", "Bot"), preview=text)
    assert build_rows([bot], [], now_ms=0)[0].summary == expected
