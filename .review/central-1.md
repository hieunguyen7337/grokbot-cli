# central-1 review

Batch: the TUI speed and progress work (unit A) and three earlier units (B, C, D)
that a stopped session wrote and nobody had reviewed. Branch
`claude/usage-optimizer-main-5yten3`, based on `gbot-tui` at f26d69a.

Every unit got a second reader, a Haiku agent that tried to refute the diff.
The main session read every diff and ran the gates in this VM.

## Unit A: speed and progress

Commits: 7487937 (the unit), 6e5e220 (fix after review).

Files and lines (final tree):
- `gbot/tui/app.py`: `CARD_SWEEP_PARALLEL = 4` (29-30), `_CardSweep` (47-86),
  `load_stage` and `sweep_progress` (144-157), `load_service` (223-244),
  `_roster_arrived` (246-248), `_install` and the sweep order (254-292),
  `_display_order`, `sweep_cards`, `_run_card_checks`, `_check_bots`
  (294-368).
- `gbot/tui/screens/home.py`: `progress_text` (31-69), the `#home-progress`
  line and its CSS (112-139), `refresh_progress` and the 0.2 s ticker
  (263-290).
- `gbot/tui/widgets/peek.py`: a loading line until the first page (100-109),
  removed on a failed page (140-146).
- `gbot/tui/screens/session.py`: the loading marker uses the ASCII ellipsis
  in `--ascii` (307-308).
- `gbot/service/api.py` (81-90), `client.py` (114-120), `fake.py` (157-168):
  `pending(bot_ids, *, bots=None)`; with `bots` the roster is not listed again.
- `docs/tui/home.md`: new; the loading lines and the sweep.

What changed for the user:
- Home shows "Connecting to Grok Bot... N s" with a spinner from mount until
  the roster arrives, adding "starting your cloud computer can take about
  30 s" after 5 s. Then, briefly, "Loading bots...". Then "Checking for cards
  n/total" with a bar until the sweep ends. The spinner holds still with
  animations off and in `--ascii`, and the ASCII bar uses `#` and `-`.
- Home lists the roster as soon as it arrives. It no longer waits for a
  one-at-a-time card check of every waiting bot.
- The sweep checks every bot, waiting bots first and then in home display
  order, with up to 4 checks at once. It reuses the loaded roster, so it no
  longer runs `listAgents` once per bot.
- Guards kept: stop on close; a 401 stops new checks with one notice; other
  errors are per-bot badges; bots refreshed by an event are skipped;
  `settled` turns true only when every check has finished. Checks run on
  daemon threads, so quitting does not wait for a blocked check.

Tests added (all with Event or Barrier waits, no fixed sleeps):
- `tests/gbot_suite/test_tui_sweep_progress.py` (11 tests): at least 4 checks
  at once (Barrier), no roster call during the sweep, the progress text shows
  and goes, exit within 2 s with checks blocked (in the app and for the whole
  process), one notice on a 401, display order, `bots=` in the fake and the
  client, the roster shown while a waiting bot's check is blocked, and a
  failed roster giving one notice and no card check.
- `tests/gbot_suite/test_tui_loading.py` (6 tests, 16 cases): line shapes,
  the static spinner, the connecting line before the roster, "Loading bots..."
  when home lists the roster, and the session and peek loading lines.
- Updated: `test_tui_live_fixes.py::test_sweep` (parallel order, no all-bots
  call) and `test_tui_home.py::test_service_errors_are_not_fatal` (a failed
  card check is now a badge, not a notice).

Snapshots changed: none.

Run history: the first worker (haiku, xhigh) wrote the code and tests but
returned without committing or finishing its checks. The main session took
it back: it released a held thread in the process-exit test, committed, and
ran every check.

Second reader found, and what changed:
- The initial card check ran one bot at a time before home listed the roster,
  so home sat on "Loading bots..." through several slow reads. Fixed in
  6e5e220: the roster is listed at once and the parallel sweep checks every
  bot, waiting bots first.
- A failed roster call led to a second roster listing (a second notice and a
  second long wait), and "Loading bots..." showed after the failure. Fixed in
  6e5e220, with a test.
- docs/tui/home.md did not name the ASCII bar characters. Fixed in 6e5e220.

Unresolved (low risk, not changed):
- If a check thread fails to start (the OS refuses a new thread), `settled`
  never turns true. Not reproduced.
- `_install` runs once per app today. If a later change made it run twice,
  two sweeps would share `_sweep_finished`. No guard exists yet.
- The count moves to n/total just before that bot's cards are drawn.
- The sweep uses the roster from install time, so a bot's
  `awaitingSessionIds` can be stale until the next roster event.
- Answering a card (`refresh_cards`) still lists the roster once per answer.
- The session screen already showed "Loading..." for the first page; the
  brief's premise was not accurate. Only the ASCII ellipsis changed there.
- `cards.tail()` reads each bot's whole transcript history, page by page
  (`docs/protocol-0.72.md:106`). That is the documented design, so it is left
  for the owner to decide (see the report).

## Unit B: TUI defects

Commits: 3f30b90 (the unit), 7cfe830 and 669cacf (fixes after review).

Files and lines:
- `gbot/tui/slash/rooms.py` (44, 92-101): one nonce per distinct request for
  the life of the `/newgroup` form.
- `gbot/tui/panels/kit.py` (234): the filter opens on key `slash` or the
  character `/`.
- `gbot/tui/slash/runs.py` (14-22, 52, 94-95): `/fresh`, `/rollback` and
  `/interrupt` refuse in read-only mode before any confirm or service call.
- Tests: `test_tui_rooms.py` (79-134), `test_tui_panels.py` (95-123),
  `test_tui_runs.py` (73-107).

Snapshots changed: none.

Second reader found, and what changed:
- The nonce changed whenever the request changed, so going back to an earlier
  request after an edit sent it with a fresh nonce. A create whose reply was
  lost could still make a second group. Fixed in 7cfe830: each distinct
  request keeps its first nonce, and a changed request never reuses another
  request's nonce. The retry test covers the A, B, A case and failed first.
- The `/` character branch of the filter key had no test. Added in 669cacf.

Unresolved: none.

## Unit C: CLI and service defects

Commit: 1830363.

Files and lines:
- `gbot/service/handoff.py` (9-11, 45): every handoff event wait is capped at
  50 ms, as `docs/tui/handoff.md` (13-14) says.
- `gbot/commands/computer.py` (46-51), `gbot/tui/slash/computer.py`
  (105-110), `gbot/tui/slash/bot_files.py` (382-386): a failed browser open
  is reported (the CLI exits 1) and the URL is never shown.
- Tests: `test_handoff.py` (79-107), `test_cli_inboxes_computer.py`
  (100-136), `test_tui_inboxes_computer.py` (199-245),
  `test_tui_bot_files.py` (400-432), `test_tui_vault.py` (129-201).

Snapshots changed: none.

Second reader found: nothing against the spec. The `/vault` test is a guard
test; `vault.py` did not change, so it also passes on the old code.

Unresolved: `gbot/tui/slash/trays.py:171`, `gbot/tui/slash/attachments.py:180`
and `gbot/commands/login.py:22` also ignore the result of `webbrowser.open`.
They do not open live-view URLs, so they were out of scope.

## Unit D: docs

Commit: b641e65.

Files and lines: `docs/gbot.md` (88-190, 580-581), `docs/tui/channels.md`
(15-17, 49-51).

Second reader found: nothing. Every claim matched the code. The listeners
JSON also has `platform`, which the doc already lists.

Unresolved: none.

## Also on this branch

927e013: `CLAUDE.md` and `AGENTS.md` now let the main cloud session merge
its reviewed, gated branch into `main` and push it (owner approval in chat,
2026-10-31).

## Gates (final tree, Linux VM, Python 3.13)

- pytest, 110 `tests/gbot_suite` modules in 4 shards: `731 passed`,
  `501 passed`, `514 passed`, `434 passed` (2,180 in all, every shard exit 0).
- `ruff check groken gbot tests`: `All checks passed!`
- `ruff format --check gbot tests/gbot_suite`: `261 files already formatted`
- `basedpyright --level error`: `0 errors, 0 warnings, 0 notes`
- `gbot tui --demo --screenshot`: exit 0, settled.
