# central-3 review

Batch: two units on separate files, run in parallel. Both close low-risk items
left open in `.review/central-1.md`. The owner's go was "continue on",
2026-10-31. Branches `c3/unit-f` and `c3/unit-g`, both based on `aacf086`,
merged into `claude/usage-optimizer-main-5yten3`.

Each worker was a subagent. A Haiku (medium) second reader tried to refute each
diff. The main session read every diff and ran the gates in this VM.

Left open on purpose, from `.review/central-1.md`:
- `refresh_cards` lists the roster once per answer. That fresh listing keeps a
  bot's waiting sessions current after an event, and it costs one call per
  answer.
- A guard against `_install` running twice. Nothing runs it twice today.
- The count moving just before a bot's cards are drawn. This is cosmetic.

## Unit F: the card sweep ends when a check thread cannot start

Worker: Sonnet (medium). Commits: 254f339 (the unit), fb5d4cf (a test fix after
review).

- `gbot/tui/app.py`: `_CardSweep.abandon(threads)` removes the threads that
  never started from the running count. `sweep_cards` counts the threads that
  start. If a `start()` raises, it logs the error, stops starting threads, and
  calls `abandon` for the rest. Whoever brings the count to zero ends the
  sweep: the last thread to leave, or `abandon`. If no thread started, one
  error notice says "Could not start the card check."
- Before: if `start()` raised, the loading line "Checking for cards n/N" never
  went away.
- Tests (`tests/gbot_suite/test_tui_sweep_progress.py`):
  `test_sweep_ends_with_one_notice_when_no_thread_starts` and
  `test_sweep_ends_when_a_later_thread_fails_to_start`. Both fail on the old
  code.

What the second reader found, and what changed:
- The second test checked the result only after the sweep settled. A fix that
  ended the sweep early (`abandon(threads)`) could still pass, because the one
  running thread was fast enough to finish every bot. Fixed in fb5d4cf: the
  test holds the first check open and asserts the sweep is still running. The
  `abandon(threads)` mutation now fails it.
- The helper's comment said the patch touched only the app. It replaces
  `threading.Thread` for the whole test, filtered by thread name. The comment
  now says so.
- Not changed: a `BaseException` raised during the start loop is not handled.
  Textual reads Ctrl+C as a key, and `SystemExit` ends the app anyway. A
  `start()` that raises after its thread ran is also not handled; CPython does
  not do that.

## Unit G: say so when a browser does not open

Worker: Haiku (low). Commits: 18726d1 (the unit), c40ddce (a login fix after
review).

- `gbot/tui/slash/trays.py` and `gbot/tui/slash/attachments.py`: when
  `webbrowser.open` returns false or raises, the bot gets the error "Could not
  open a browser for the link." (or "for the file."). The browser's exception
  is no longer passed on, since its text may contain the link. This follows
  `bot_files.py` and `commands/computer.py`.
- `gbot/commands/login.py`: when no browser opens, a plain line on stderr says
  to open the link shown above. Any exception from `webbrowser.open` counts as
  not opened. Login still waits for the sign-in, and the stdout JSON is
  unchanged.
- Tests:
  - `test_open_link_reports_browser_failure` (trays) and
    `test_open_file_link_reports_browser_failure` (attachments) each run for a
    false result and a raised error, and check that the link is absent from
    the message.
  - `test_login_reports_browser_failure` runs with and without `--json`, for a
    false result, a `webbrowser.Error`, a generic exception that carries the
    link, and a browser that opens.
- The worker left a stuck background command (a `cat` waiting on stdin) and an
  empty `/tmp/unused`. Neither touched the worktree. The main session killed
  the command and removed the file.

What the second reader found, and what changed (all in the login path; the
tray and file paths held):
- The worker reported "no browser" through `ctx.out.error`. With `--json`,
  that prints an error object with `exit_code: 1` on stderr, while login goes
  on, succeeds and exits 0. Fixed in c40ddce: it is now a plain line on
  stderr, like the notes in `gbot/commands/avatar.py`.
- Only `OSError` and `webbrowser.Error` were caught. Any other exception from
  `webbrowser.open` reached the CLI's error printer with its text, which can
  hold the link. This was unchanged from before, but it contradicted the
  unit's claim. Fixed in c40ddce: any exception counts as not opened.
- The login test did not cover a generic exception or a browser that opens.
  Both are covered now, and the test asserts that stderr has no error object.
- Not changed: `webbrowser.open` can return true when the browser later fails
  to start. Python cannot see that.

## Gates (merge of both units, Linux VM, Python 3.13)

Run on the merge of `c3/unit-f` (fb5d4cf) and `c3/unit-g` (c40ddce) into
`aacf086`, with `tests/gbot_suite` split into 4 parallel shards (110 modules):
- pytest: 738 + 503 + 528 + 442 = 2,211 passed, 0 failed (14 new tests).
- `ruff check groken gbot tests`: all checks passed.
- `ruff format --check gbot tests/gbot_suite`: 261 files already formatted.
- `basedpyright --level error`: 0 errors, 0 warnings, 0 notes.

The commit that adds this file changes nothing else, so the gates were not run
again for it.
