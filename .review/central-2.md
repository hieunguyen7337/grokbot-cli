# central-2 review

Batch: one unit (E). The home card sweep reads only a bot's newest transcript page
when the roster does not show that bot as waiting. Owner's go in chat, 2026-10-31.
Branch `c2/unit-e`, based on `364c827`, merged into
`claude/usage-optimizer-main-5yten3`.

The worker was a Sonnet (high) subagent. The second reader was a Haiku (medium)
subagent that tried to refute the diff. The main session read every diff and
ran the gates in this VM.

## Unit E: recent pages for bots that are not waiting

Commits: e633968 (the unit), 8d689ca, dc0b6f7 and the docstring commit after it
(fixes after review).

Files and lines (final tree):
- `gbot/service/cards.py`: `waiting(row)` (245-255), `tail(..., max_pages=)`
  (258-289), and the `discover(..., recent_pages=)` cap (292-336, the cap at
  315).
- `gbot/service/api.py` (85, 91-93), `client.py` (118, 127-132), `fake.py`
  (162, 177-179): `pending(..., recent_pages=None)`. `None` reads every bot in
  full, as before.
- `gbot/tui/app.py`: `HOME_RECENT_PAGES = 1` (31-32). `_check_bots` passes it
  (350-352). `refresh_cards` is unchanged and still reads in full.
- `docs/protocol-0.72.md` (110-115) and `docs/tui/home.md` (30-37).

What changed for the user:
- On home, a bot that is not waiting costs one transcript read (100 entries)
  per check instead of one read per 100 entries of its history.
- A bot counts as waiting when `awaitingUserResponse` is anything but absent,
  null or false, or when the roster lists a waiting session. A waiting bot is
  read in full.
- What is unchanged: `gbot approvals`, `gbot ask`, the re-check after an
  answer or an event, and the check just before an answer. All of these read
  in full.
- The trade-off: a card more than 100 entries back, on a bot that is not
  waiting, does not show on home until that bot's cards are read in full. That
  happens when the bot adds a card, when an entry arrives while the bot is
  flagged, after a resync, or at the next start if the bot is waiting then.

Tests added:
- `tests/gbot_suite/test_cards_service.py`: `test_tail_max_pages`,
  `test_tail_max_pages_still_checks_advance`, `test_waiting` (9 cases),
  `test_discover_recent_pages`,
  `test_discover_recent_pages_card_on_second_page`, and
  `test_discover_recent_pages_keeps_auth_failure`.
- `tests/gbot_suite/test_tui_sweep_progress.py`:
  `test_sweep_passes_recent_pages_and_refresh_does_not`,
  `test_fake_pending_honours_recent_pages`, and
  `test_client_pending_passes_recent_pages`.
- Updated: the `pending` wrappers in `test_tui_sweep_progress.py` and
  `test_tui_live_fixes.py` take `recent_pages`. The keyword pin in
  `test_service_client.py::test_cards_and_background` now includes
  `recent_pages=None`.

Snapshots changed: none.

What the main session found and fixed:
- `docs/tui/home.md` said that a card further back would show "once the list
  flags the bot or the bot is opened". Neither re-reads cards
  (`gbot/tui/state.py:39-45`; a session reads cards from memory). Fixed in
  8d689ca to name the events that do re-read.
- The fake returned no entries for a cap below one, where `cards.tail` still
  reads one page. Fixed in 8d689ca.

What the second reader found, and what changed:
- `test_service_client.py::test_cards_and_background` failed, because it pins
  the exact keywords passed to `discover`. That module was not in the worker's
  verifier list. Fixed in dc0b6f7.
- An empty `awaitingUserResponse` mapping was capped, but the model treats
  every mapping as waiting (`gbot/service/models.py:98-101`). Fixed in dc0b6f7
  with `cards.waiting`.
- A bot that listed waiting sessions without the bot-level flag had those
  sessions capped. It now counts as waiting (dc0b6f7). The brief had left this
  gap, not the worker.
- Not changed: the fake has no sessions, so it caps a bot's single transcript.
  Its order (oldest to newest) matches the real client's newest page.

Unresolved (low risk, not changed):
- A raw `awaitingUserResponse: true` counts as waiting here. The TUI's
  entry-event refresh uses `bot.awaiting`, which is set only for a mapping.
  The protocol sends a mapping (`docs/protocol-tui.md:160-161`).
- The reader did not run the new tests against the old code. They pass keyword
  arguments that the old signatures reject, so they cannot pass there.

## Gates (final tree, Linux VM, Python 3.13)

GATES_PLACEHOLDER
