# central-4 review

Batch: one unit (H). The owner asked, 2026-11-01: "speed up the card check for
waiting bots too". Branch `c4/unit-h`, based on `c7cd701`, merged into
`claude/usage-optimizer-main-5yten3`.

The worker was a Haiku (high) subagent. A Haiku (medium) second reader tried to
refute the diff. The main session read every diff and ran the gates in this VM.

## Unit H: waiting bots get their newest cards first, then a full read

Commits: e5606c4 (the unit, with the main session's fixes; see below), a68f658
and d63538d (fixes after review).

- `gbot/service/cards.py` `discover`, and `pending` in `api.py`, `client.py`
  and `fake.py`: a new keyword `waiting_in_full` (default True, which keeps
  the old behaviour). With False, `recent_pages` caps waiting bots too.
- `gbot/tui/app.py`: the home sweep has two passes. Every bot first gets a
  quick check of its newest page, waiting bots first, then in display order.
  When a waiting bot's quick result is on home, the thread that installed it
  queues that bot's full read at the end of the queue. A failed quick check
  still queues it (a 401 stops the sweep instead). A bot whose cards were
  refreshed meanwhile gets no full read, and that full read counts as done.
  The waiting bots are those `cards.waiting(bot.raw)` picks, the same test
  `discover` uses for its full read.
- `gbot/tui/screens/home.py`: after the quick pass, while full reads run, the
  line reads `Checking older cards n/W` with the same spinner and bar.
- Docs: `docs/tui/home.md` and `docs/protocol-0.72.md` describe the two passes.
- Tests: the newest card shows while the full read is held open; a failed
  quick check still gets its full read (and when that fails too, the badge
  stays); the quick pass reaches every bot before any full read; a user
  refresh is not replaced by a quick result that lands later; a warning both
  reads report shows once. Plus the keyword in `discover`, the client and the
  fake, and the new progress line in Unicode and ASCII within 76 cells.

The main session's fixes before review:
- The worker's verifier was red because `tests/gbot_suite/test_tui_live_fixes.py`
  had fakes without the new keyword. The brief named that file in the verifier
  but left it out of scope, so the worker did not edit it. The main session
  added the keyword to its four fakes, and `test_sweep` now expects a full read
  of each waiting bot too.
- The worker's line, `Checking older cards of waiting bots n/W`, ran to 77
  cells, over the 76-cell limit. It is now `Checking older cards n/W`.
- The worker created a remote cloud session by mistake, with the prompt
  "noop". It did no work in the repository.

What the second reader found, and what changed (a68f658, d63538d):
- A waiting bot whose quick check failed got no full read, so a card the old
  sweep's full read would find could be missed, and a test pinned that. Now
  the full read is still queued; the test expects it and covers a second
  failure.
- `refresh_cards` (after an answer, or from a session) installed a full read
  without marking the bot refreshed, so a capped sweep result landing later
  could replace it. This was already true for bots that are not waiting. Now
  the refresh marks the bot when it installs.
- A waiting bot's quick and full reads can report the same warning, which
  showed twice. Each sweep now shows a bot's warning once.
- Each new test fails with its fix reverted (checked by the main session).
- Not changed: a thread that finds the queue empty leaves, even when another
  thread is about to queue a full read. That thread then runs the full read
  itself, so nothing is lost, but the last full reads can run with fewer than 4
  at once. A waiting bot whose newest page is its whole history is read twice.

## Measured (slowed fake service, this VM)

Same set-up as the 2026-10-31 check: 15 bots (6 waiting), 60 to 1,500 entries
each, 3 s to connect, 1 s per roster listing, 0.5 s per page of 100 entries, 4
checks at once. Five waiting bots also have a pending card on an older page,
which only a full read finds.

| | Before (c7cd701) | Unit H |
|---|---|---|
| Waiting bots' newest cards on home | 14.1 s | 5.2 s |
| Loading finished | 14.1 s | 16.3 s |
| Pages read | 65 | 71 |
| Older cards found | 5 of 5 | 5 of 5 |

The full reads cost one more page per waiting bot (its newest page is read
twice) and start after the quick pass, so loading ends about 2 s later. The
unit H numbers are from the merge result.

## Gates (merge result 8b6baab, Linux VM, Python 3.13)

- pytest, `tests/gbot_suite` in 4 shards (110 modules): 745 + 503 + 531 + 442 =
  2,221 passed, 0 failed.
- `ruff check groken gbot tests`: all checks passed.
- `ruff format --check gbot tests/gbot_suite`: 261 files already formatted.
- `basedpyright --level error`: 0 errors, 0 warnings, 0 notes.

The commit that adds this file changes nothing else, so the gates were not run
again for it.
