# central-5: two hardening fixes

Main session 20261102-125331-main. Unit run by the local session (Codex sol low), then reviewed and fixed here.

## Changes

- `gbot/service/models.py`: new `awaiting_flag(value)`, true unless the value is absent, None or False.
  `Bot.from_row` uses it, so a non-mapping value such as `true` now gives `Awaiting("awaiting", None, None)`.
- `gbot/service/cards.py`: `waiting` uses the same helper, so card discovery and `Bot.awaiting` agree.
- `gbot/tui/app.py`: a second `_install` replaces the running card sweep. `sweep_cards` is an exclusive worker,
  `_install` resets `_sweep_finished`, and only the current sweep may set it. Check threads of a replaced sweep stop
  taking work, and their results and failures are dropped (`_install_sweep_cards`, `_check_failed`).

## Tests

- `test_service_core.py::test_awaiting_flag_matches_card_discovery` (8 values).
- `test_tui_sweep_progress.py::test_reinstall_replaces_sweep` (2 cases).
- `test_tui_sweep_progress.py::test_replaced_sweep_failure_leaves_no_badge` (added in review).
  The second reader ran the first two against 659aae5: 7 of the new cases fail there. The third failed here before
  the `_check_failed` guard.

## Review

- Second reader (Haiku): no refutation of the main claims. It found that a failed check of a replaced sweep still
  set an error badge (or the auth notice). Fixed in review with the guard and test above.
- Off-schema values `0`, `""` and `[]` now count as waiting in `Bot.awaiting`, matching the documented rule
  (`docs/protocol-0.72.md:111-114`, `docs/protocol-tui.md:161`). `gbot/commands/bots.py:21`,
  `gbot/service/cards.py:309` and `groken/gateway.py:562` still use plain truthiness; off-schema only, left as is.
- The local session saw two timing failures in `test_tui_sweep_progress.py` on Windows under load, one also on
  unchanged main. Not reproduced here (6 parallel runs of the file, all green). Possible cause (inferred): tests that
  call `app.workers.wait_for_complete()` before the sweep worker exists.

No SVG snapshots changed. Nothing here needs a Windows-only check.
