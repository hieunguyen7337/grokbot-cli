# central-5: two hardening fixes (gbot TUI and card service)

Repository: grokbot-cli (Python 3.11-3.13, ruff 0.16.2, basedpyright --level error). Work at the arm's effort.

## 1. Goal

Two small defensive fixes, each with a failing test written first:

A. `GbotApp._install` (`gbot/tui/app.py`, around lines 317-341) starts a card sweep with `self.sweep_cards(...)`.
   Today `_install` runs once per app. If it ever ran twice, two sweeps would share `self._sweep_finished`: the first
   sweep to end would set it True while the second still runs, and `settled` / `load_stage` would lie. Make a second
   `_install` replace the running sweep cleanly: only the newest sweep may set `_sweep_finished = True`, and starting
   a new sweep resets `_sweep_finished` to False. Prefer the smallest change: for example, `sweep_cards` sets
   `_sweep_finished` only when `sweep is self._sweep`, `_install` resets `_sweep_finished = False` before it starts
   the new one, and the Textual worker group `card-sweep` is cancelled or made `exclusive=True` so the old coroutine
   does not keep waiting. The old sweep's threads may finish their in-flight checks; they must not install cards for
   a sweep that was replaced if that is simple to guard (check how `_install_sweep_cards` is called), otherwise leave
   that and say so.

B. `gbot/service/cards.py::waiting` counts any `awaitingUserResponse` that is not absent/None/False as waiting
   (so a raw `true` counts). `gbot/service/models.py` (around lines 98-106) sets `Bot.awaiting` only when the value
   is a Mapping, and the TUI's entry-event refresh (`gbot/tui/state.py`, around line 44) uses `bot.awaiting`. Make the
   two agree through ONE helper in `gbot/service/models.py` (for example `awaiting_flag(value: object) -> bool`, true
   unless the value is None or False), used by both `cards.waiting` and the Bot parser. For a non-Mapping truthy
   value the Bot gets `Awaiting("awaiting", None, None)` (the same default reason the Mapping path uses). Keep the
   current behaviour for Mappings and for `awaitingSessionIds`.

## 2. Files

In scope: `gbot/tui/app.py`, `gbot/service/cards.py`, `gbot/service/models.py`, and tests in
`tests/gbot_suite/test_tui_sweep_progress.py` (A) and `tests/gbot_suite/test_cards_service.py` or
`tests/gbot_suite/test_service_core.py` (B). You may add one new test file `tests/gbot_suite/test_tui_hardening.py`
instead if that is cleaner.
Out of scope: everything else. Do not touch `docs/parity.json`, Textual SVG snapshots, `groken/`, or any doc.

## 3. Constraints

- SAFETY: tests use `FakeService` / fakes and `httpx.MockTransport` only. NEVER run `gbot` without `--demo`, never run
  any command with `--yes`, never call the live Grok Bot or Cursor API (`api2.cursor.sh` or any gateway URL), and never
  read token files (`~/.config/groken`, `%LOCALAPPDATA%\grokbot-cli`).
- No fixed sleeps in code or tests: use events, `pilot.pause()`, or condition-based waits as the existing sweep tests
  do (read `tests/gbot_suite/test_tui_sweep_progress.py` first and copy its harness).
- Failing test first: show each new test failing on the old code, then passing.
- Style: plain English comments, short; UTF-8 without BOM, LF line endings; keep public names.
- Verifier (Windows, run only these, never the full suite):
  `.venv/Scripts/python -m pytest -q tests/gbot_suite/test_tui_sweep_progress.py tests/gbot_suite/test_cards_service.py tests/gbot_suite/test_service_core.py`
  (plus the new test file if you add one), and
  `.venv/Scripts/ruff check gbot/tui/app.py gbot/service/cards.py gbot/service/models.py <test files touched>` and
  `.venv/Scripts/ruff format --check` on the same files.

## 4. Return contract (at most 60 lines)

- Files changed, with file:line of each change.
- For each new test: its name, the failing output on the old code (one line), and the passing run.
- The verifier commands with their real output (last lines).
- Anything unresolved, marked `[OBSERVED path:line]` or `[INFERRED]`.
