import asyncio
import re
import threading
from time import monotonic
from unittest.mock import Mock

import pytest
from textual.widgets import Static

from gbot.service import cards, client, conversation
from gbot.service.broker import CredentialBroker
from gbot.service.fake import FakeService, load_fake
from gbot.service.models import Bot
from gbot.tui import app as app_module
from gbot.tui.app import GbotApp
from groken.client import ConnectError


@pytest.fixture
def home_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    return tmp_path


def sweep_service(count: int = 12) -> FakeService:
    service = load_fake()
    service.state.rows = [
        {"id": f"idle-{i:02}", "name": f"Bot-{i:02}"} for i in range(count)
    ]
    service.state.transcripts.clear()
    return service


def call_original(original, bot_ids, bots, recent_pages=None):
    # The real client takes the roster as `bots`; the fake only sees it when the sweep passes it.
    if bots is None:
        return original(bot_ids)
    return original(bot_ids, bots=bots, recent_pages=recent_pages)


def home_progress(app: GbotApp) -> str:
    line = app.home.query_one("#home-progress", Static)
    return str(line.render()) if line.display else ""


async def wait_until(pilot, condition, message: str) -> None:
    deadline = monotonic() + 5
    while not condition():
        assert monotonic() < deadline, f"timed out waiting for {message}"
        await pilot.pause()


def test_card_checks_run_in_parallel(home_env):
    async def exercise():
        service = sweep_service(12)
        original = service.pending
        barrier = threading.Barrier(4, timeout=5)
        lock = threading.Lock()
        state = {"checks": 0, "in_flight": 0, "peak": 0}

        def pending(bot_ids=None, *, bots=None, recent_pages=None):
            if bot_ids is None:
                return call_original(original, bot_ids, bots, recent_pages)
            with lock:
                state["checks"] += 1
                state["in_flight"] += 1
                state["peak"] = max(state["peak"], state["in_flight"])
                first_four = state["checks"] <= 4
            try:
                # The first four checks must all be in flight at once to pass the barrier.
                if first_four:
                    barrier.wait()
                return call_original(original, bot_ids, bots, recent_pages)
            finally:
                with lock:
                    state["in_flight"] -= 1

        service.pending = pending
        app = GbotApp(service, animate=False)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.settled
        assert not barrier.broken
        assert state["peak"] >= 4
        assert state["checks"] == 12

    asyncio.run(exercise())


def test_sweep_never_lists_the_roster(home_env):
    async def exercise():
        service = sweep_service(12)
        original = service.pending
        roster = service.roster
        calls = {"roster": 0}

        def counting_roster():
            calls["roster"] += 1
            return roster()

        def pending(bot_ids=None, *, bots=None, recent_pages=None):
            if bots is None:
                # The gateway client re-runs listAgents on every call that is not handed the roster.
                counting_roster()
            return call_original(original, bot_ids, bots, recent_pages)

        service.roster = counting_roster
        service.pending = pending
        app = GbotApp(service, animate=False)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.settled
        # Only the initial load lists the roster; the sweep of 12 bots adds nothing.
        assert calls["roster"] == 1

    asyncio.run(exercise())


def test_sweep_progress_shows_then_goes(home_env):
    async def exercise():
        service = sweep_service(12)
        original = service.pending
        release = threading.Event()

        def pending(bot_ids=None, *, bots=None, recent_pages=None):
            if bot_ids is not None:
                release.wait(5)
            return call_original(original, bot_ids, bots, recent_pages)

        service.pending = pending
        app = GbotApp(service, animate=False)
        try:
            async with app.run_test() as pilot:
                await wait_until(
                    pilot,
                    lambda: "Checking for cards" in home_progress(app),
                    "the sweep progress line",
                )
                shown = home_progress(app)
                assert re.search(r"Checking for cards \d+/12", shown), shown
                # The bar is drawn in brackets; markup must not swallow them.
                assert shown.count("[") == 1 and shown.count("]") == 1, shown
                # The list keeps working while the sweep runs.
                before = app.home.bot_list.selected_id
                await pilot.press("down")
                assert app.home.bot_list.selected_id != before
                release.set()
                await wait_until(pilot, lambda: app.settled, "the sweep to settle")
                await pilot.pause()
                assert home_progress(app) == ""
        finally:
            release.set()

    asyncio.run(exercise())


def test_exit_is_prompt_while_checks_are_blocked(home_env):
    async def exercise():
        service = sweep_service(12)
        original = service.pending
        entered = threading.Event()
        release = threading.Event()

        def pending(bot_ids=None, *, bots=None, recent_pages=None):
            if bot_ids is not None:
                entered.set()
                release.wait(10)
            return call_original(original, bot_ids, bots, recent_pages)

        service.pending = pending
        app = GbotApp(service, animate=False)
        try:
            async with app.run_test() as pilot:
                await wait_until(pilot, entered.is_set, "a blocked check")
                started = monotonic()
                app.action_palette_quit()
            elapsed = monotonic() - started
        finally:
            release.set()
        assert elapsed < 2

    asyncio.run(exercise())


def test_process_exit_does_not_wait_for_blocked_checks(home_env):
    hold = threading.Event()

    async def exercise():
        service = sweep_service(12)
        original = service.pending
        entered = threading.Event()

        def pending(bot_ids=None, *, bots=None, recent_pages=None):
            if bot_ids is not None:
                entered.set()
                # Held for a bounded 3 s, so the check outlives the app and a bad exit shows up as a slow one.
                hold.wait(3)
            return call_original(original, bot_ids, bots, recent_pages)

        service.pending = pending
        app = GbotApp(service, animate=False)
        async with app.run_test() as pilot:
            await wait_until(pilot, entered.is_set, "a blocked check")
            app.action_palette_quit()

    started = monotonic()
    try:
        asyncio.run(exercise())
        elapsed = monotonic() - started
    finally:
        # Let the held check end now, so its thread does not run into later tests.
        hold.set()
    assert elapsed < 2


def test_auth_failure_stops_new_checks_with_one_notice(home_env, monkeypatch):
    async def exercise():
        service = sweep_service(12)
        original = service.pending
        gate = threading.Event()
        lock = threading.Lock()
        requested: list[str] = []
        notices: list[Exception] = []

        def pending(bot_ids=None, *, bots=None, recent_pages=None):
            if bot_ids is None:
                return call_original(original, bot_ids, bots, recent_pages)
            with lock:
                requested.append(bot_ids[0])
            if bot_ids == ["idle-00"]:
                raise ConnectError(401, "expired")
            # Other checks are already in flight when the first 401 lands.
            gate.wait(5)
            return call_original(original, bot_ids, bots, recent_pages)

        def record_error(self, error):
            notices.append(error)

        monkeypatch.setattr(GbotApp, "service_error", record_error)
        service.pending = pending
        app = GbotApp(service, animate=False)
        try:
            async with app.run_test() as pilot:
                await wait_until(pilot, lambda: bool(notices), "the 401 notice")
                gate.set()
                await wait_until(pilot, lambda: app.settled, "the sweep to settle")
                await pilot.pause()
        finally:
            gate.set()
        assert len(notices) == 1
        assert isinstance(notices[0], ConnectError) and notices[0].status == 401
        # Only the first four checks start; none starts after the 401.
        assert "idle-00" in requested
        assert set(requested) <= {f"idle-{i:02}" for i in range(4)}

    asyncio.run(exercise())


def test_sweep_checks_in_display_order(home_env, monkeypatch):
    async def exercise():
        service = sweep_service(12)
        # Make the last bot a new reply so the home list shows it above the idle bots.
        service.state.rows[-1]["hasUnread"] = True
        service.state.rows[-1]["unreadCount"] = 1
        original = service.pending
        checked: list[str] = []

        def pending(bot_ids=None, *, bots=None, recent_pages=None):
            if bot_ids is not None:
                checked.extend(bot_ids)
            return call_original(original, bot_ids, bots, recent_pages)

        service.pending = pending
        monkeypatch.setattr(app_module, "CARD_SWEEP_PARALLEL", 1)
        app = GbotApp(service, animate=False)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.settled
            shown = app.home.bot_list.visible_ids
        gateway = [f"idle-{i:02}" for i in range(12)]
        assert shown[0] == "idle-11" and shown != gateway[: len(shown)]
        assert checked == [*shown, *(i for i in gateway if i not in shown)]

    asyncio.run(exercise())


def test_fake_pending_honours_bots():
    service = load_fake()
    bot = next(b for b in service.roster() if b.id == "demo-inbox")
    assert service.pending(bots=[]) == ([], [])
    scoped, _ = service.pending(["demo-inbox"], bots=[bot])
    assert scoped and all(card.bot_id == "demo-inbox" for card in scoped)
    assert scoped == service.pending(["demo-inbox"])[0]
    everything, _ = service.pending(bots=[bot])
    assert everything == scoped


def test_sweep_passes_recent_pages_and_refresh_does_not(home_env):
    async def exercise():
        service = sweep_service(5)
        original = service.pending
        seen: list[tuple[list[str] | None, int | None]] = []

        def pending(bot_ids=None, *, bots=None, recent_pages=None):
            seen.append((bot_ids, recent_pages))
            return call_original(original, bot_ids, bots, recent_pages)

        service.pending = pending
        app = GbotApp(service, animate=False)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.settled
            swept = [item for item in seen if item[0] is not None]
            assert len(swept) == 5
            assert {recent for _, recent in swept} == {app_module.HOME_RECENT_PAGES}
            seen.clear()
            app.refresh_cards("idle-00")
            await app.workers.wait_for_complete()
            assert seen == [(["idle-00"], None)]

    asyncio.run(exercise())


def test_fake_pending_honours_recent_pages():
    service = sweep_service(2)
    entries = [
        {
            "id": f"e{i}",
            "seq": i,
            "kind": "send-message",
            "message": {"type": "widget", "widget": {}},
        }
        for i in range(1, 151)
    ]
    for bot_id in ("idle-00", "idle-01"):
        service.state.transcripts[bot_id] = [dict(e) for e in entries]
    service.state.rows[1]["awaitingUserResponse"] = {"reason": "approval"}
    full, _ = service.pending()
    assert len(full) == 300
    capped, _ = service.pending(recent_pages=1)
    # The idle bot keeps its newest 100 entries; the waiting bot is read in full.
    assert [c.bot_id for c in capped].count("idle-00") == 100
    assert [c.bot_id for c in capped].count("idle-01") == 150
    assert {c.entry_id for c in capped if c.bot_id == "idle-00"} == {
        f"e{i}" for i in range(51, 151)
    }


def test_client_pending_passes_recent_pages(monkeypatch):
    def mint():
        return {
            "gatewayUrl": "https://offline.invalid",
            "gatewayToken": "fake",
            "networkToken": "fake",
            "podId": "p",
        }

    service = client.GbotService(CredentialBroker(mint))
    bot = Bot.from_row({"id": "a", "name": "Alpha"})
    assert bot is not None
    discover = Mock(return_value=([], []))
    monkeypatch.setattr(cards, "discover", discover)
    service.pending(["a"], bots=[bot], recent_pages=1)
    assert discover.call_args.kwargs["recent_pages"] == 1
    service.pending(["a"], bots=[bot])
    assert discover.call_args.kwargs["recent_pages"] is None


def test_pending_with_bots_skips_the_listing(monkeypatch):
    def mint():
        return {
            "gatewayUrl": "https://offline.invalid",
            "gatewayToken": "fake",
            "networkToken": "fake",
            "podId": "p",
        }

    service = client.GbotService(CredentialBroker(mint))
    waiting = Bot.from_row({"id": "a", "name": "Alpha", "awaitingUserResponse": {}})
    idle = Bot.from_row({"id": "b", "name": "Beta"})
    assert waiting is not None and idle is not None
    roster = Mock(side_effect=AssertionError("listAgents must not run"))
    discover = Mock(return_value=([], []))
    monkeypatch.setattr(conversation, "roster", roster)
    monkeypatch.setattr(cards, "discover", discover)
    assert service.pending(["b"], bots=[waiting, idle]) == ([], [])
    assert discover.call_args.args[1] == [dict(idle.raw)]
    service.pending(bots=[waiting, idle])
    assert discover.call_args.args[1] == [dict(waiting.raw)]
    roster.assert_not_called()


def test_roster_shows_before_waiting_bots_are_checked(home_env, monkeypatch):
    # One check at a time, so the call order is the sweep's order.
    monkeypatch.setattr(app_module, "CARD_SWEEP_PARALLEL", 1)

    async def exercise():
        service = sweep_service(6)
        service.state.rows[5]["awaitingUserResponse"] = {"reason": "approval"}
        original = service.pending
        entered, release = threading.Event(), threading.Event()
        requested: list[object] = []

        def pending(bot_ids=None, *, bots=None, recent_pages=None):
            requested.append(None if bot_ids is None else list(bot_ids))
            if bot_ids is None or "idle-05" in bot_ids:
                entered.set()
                release.wait(5)
            return call_original(original, bot_ids, bots, recent_pages)

        service.pending = pending
        app = GbotApp(service, animate=False)
        try:
            async with app.run_test() as pilot:
                await wait_until(pilot, entered.is_set, "the waiting bot's check")
                # Home lists every bot while the waiting bot's cards are still being read.
                await wait_until(pilot, lambda: app.loaded, "the roster on home")
                assert {row.bot_id for row in app.home.rows} >= {
                    f"idle-{i:02}" for i in range(6)
                }
                assert "Checking for cards" in home_progress(app)
                release.set()
                await wait_until(pilot, lambda: app.settled, "the sweep to settle")
        finally:
            release.set()
        # The waiting bot is checked by the sweep, first, and nothing asks for every bot at once.
        assert None not in requested
        assert requested[0] == ["idle-05"]
        assert sorted(r[0] for r in requested if isinstance(r, list)) == [
            f"idle-{i:02}" for i in range(6)
        ]

    asyncio.run(exercise())


def test_failed_roster_gives_one_notice_and_no_card_check(home_env, monkeypatch):
    async def exercise():
        service = sweep_service(4)
        notices: list[Exception] = []
        stages: list[str | None] = []
        requested: list[object] = []

        def roster():
            raise ConnectError(401, "expired")

        def pending(bot_ids=None, *, bots=None, recent_pages=None):
            requested.append(bot_ids)
            # Without a roster the client would list it again and fail the same way.
            raise ConnectError(401, "expired")

        def record_error(self, error):
            notices.append(error)

        monkeypatch.setattr(GbotApp, "service_error", record_error)
        service.roster = roster
        service.pending = pending
        app = GbotApp(service, animate=False)
        async with app.run_test() as pilot:
            await wait_until(
                pilot,
                lambda: stages.append(app.load_stage) is None and app.settled,
                "the app to settle",
            )
        assert len(notices) == 1
        assert requested == []
        assert "loading" not in stages

    asyncio.run(exercise())
