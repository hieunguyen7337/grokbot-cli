# Review: unit M5g (cloud computer, upgrade schedule, runtime settings)

Reviewed: `claude/unit-m5g-review-u8hr8h`, unit commit `151c482` (`M5g: cloud computer and runtime settings`),
diffed against `origin/gbot-tui` (merge base `2bac1fde`). 10 files, +2540 / -24.

## 1. Findings

Two major, three minor, no blockers. Each defect was reproduced with a probe script (kept in the session scratchpad,
outside the repository) unless tagged INFERRED.

### F1 (major): an out-of-range upgrade time breaks the read and leaves `/sandbox` stale

- Where: `gbot/service/sandbox.py:67-70` (`_when`; the conversion is at line 68), `:329-331` (the "Next run" row,
  which calls `_when`), `:336-343` (`fields`). Reached from `gbot/tui/slash/sandbox.py:118` (panel content) and
  `gbot/commands/sandbox.py:113-116` (text rows).
- Wrong: `_when` converts `nextFireAtMs` with `datetime.fromtimestamp`, which raises once the instant passes year
  9999. Nothing catches it, so one odd reply breaks the whole read.
- Input: `GetSandBoxUpgradeSchedule` replies `{"schedule": {"state": "SAND_BOX_UPGRADE_SCHEDULE_STATE_SCHEDULED",
  "nextFireAtMs": "1000000000000000"}}`. Values from 253402300800000 ms up raise; 253402300799999 is the last valid
  one. [OBSERVED]
  - `service.fields(...)` raises `ValueError: year 33658 is out of range`. [OBSERVED]
  - `gbot sandbox` exits 1 and prints no status. [OBSERVED]
  - `/sandbox`: `SandboxPanel.loaded` (`gbot/tui/slash/sandbox.py:127-130`) raises at `self.redraw()` (line 130)
    before the detail is replaced. The panel keeps its empty defaults (State unknown, Image unknown,
    Upgrade none scheduled) with no notice, although the server reported a running computer. [OBSERVED]
  - The error is silent because `_worker` calls `ctx.app.call_from_thread(done, result)` (`gbot/tui/slash/sandbox.py:44`)
    outside its `try`, and the worker runs with `exit_on_error=False` (line 46). `gbot/tui/slash/teams.py:34` has the
    same shape, so the fix belongs at the shared worker boundary. [OBSERVED behaviour; mechanism read from code]
- Brief rule broken: "nothing raises on an odd reply" (service rules).
- Test gap: `tests/gbot_suite/test_service_sandbox.py:341-363` uses only the 2027 timestamp. No test sends an
  out-of-range value, so the suite passes with this defect.

### F2 (major): refused reads show default values as facts

- Where: `gbot/service/sandbox.py:271-283` (`overview` leaves `schedule` as `None` on a refusal), `:322`
  (`return (("Upgrade", "none scheduled"),)`), `:346-360` (`settings_fields`). `gbot/tui/slash/sandbox.py:293-300`
  (`_read_settings`, `return service.RuntimeSettings(), found.message`). `gbot/commands/sandbox.py:110` (JSON
  `upgrade_schedule`) and `:113-116` (text rows).
- Wrong: a refused part is drawn as an ordinary value, with the refusal as a notice beside it. The brief says a refused
  part shows as that one sentence ("Empty and refused states are one plain sentence, not an empty list"; "shows a
  refused part as that sentence").
- Input, probed with both reads refused. `GetSandBoxUpgradeSchedule` returns `invalid_argument` "Pick a schedule
  first."; `GetGrokBotUserRuntimeSettings` returns `permission_denied` "Team bots only.":
  - `/sandbox` fields show `Upgrade: none scheduled`, with body `Pick a schedule first.`. [OBSERVED]
  - `gbot sandbox` prints `Upgrade: none scheduled`, then the notice, and exits 0. JSON gives
    `"upgrade_schedule": null` plus the notice. [OBSERVED]
  - `/runtime` fields show `Pinned bots: none`, `Auto-review: off`, `Onboarding: not seen`, `Main bot: none`,
    `Email provider: none`, with body `Team bots only.`. [OBSERVED]
- Effect on the real account [INFERRED]: `docs/protocol-m5-live.md:53` records `GetSandBoxUpgradeSchedule {}` →
  `invalid_argument` on this account. So `/sandbox` and `gbot sandbox` would always state "none scheduled". `/sandbox`
  would then offer "Schedule upgrade" (`gbot/tui/slash/sandbox.py:111`), and `schedule()` would create rather than
  reschedule (`:221-222`).
- Docs contradict the code: `docs/tui/sandbox.md:6` says "A schedule the server refuses to show appears as one plain
  sentence above the actions."
- Test gap: `tests/gbot_suite/test_tui_sandbox.py:97` and `:335-358`, and `tests/gbot_suite/test_cli_sandbox.py:97-110`,
  assert only the notice. None asserts that the default rows are absent, so all pass with this defect.

### F3 (minor): an explicit empty `--timezone` is sent as UTC

- Where: `gbot/commands/sandbox.py:163`, `timezone = args.timezone or "UTC"`.
- Input: `gbot sandbox --schedule-upgrade 03:30 --timezone "" --yes --json` exits 0 and sends
  `ScheduleSandBoxUpgrade {"timezone": "UTC", "localTime": "03:30", "recurring": false}`. [OBSERVED]
- Brief rule: "a bad value raises `ValueError` before any call". An empty zone is a bad value. Here it is replaced
  silently, so the upgrade is scheduled in a zone the person did not name.

### F4 (minor): docs state unverified upgrade behaviour as fact

- Where: `docs/gbot.md:792`, "`--recurring` repeats the upgrade every day." And `docs/gbot.md:789`,
  "`--acknowledge-schedule` lets a recreate proceed past a terminal upgrade schedule."
- The protocol gives no cadence. `docs/protocol-m5c.md:102` says `recurring` "says whether it repeats (INFERRED)".
  `docs/protocol-m5c.md:99` marks the acknowledge meaning "(INFERRED)". The docs should carry the same uncertainty
  or be narrowed to what the protocol says. [OBSERVED docs text; INFERRED protocol status]

### F5 (minor): doc wording differs from the brief

- Where: `docs/tui/sandbox.md:38`, "Host settings (the desktop computer) and update-now stay in the Grok Bot app."
  The brief asks this file to say "the desktop app". The parity note uses "Grok Bot app", so the author should pick
  one. [OBSERVED]

## 2. Parity entries changed

Checked by loading both files and comparing every entry by name. Exactly 12 entries changed, all `status` and `note`
only. No entry was added or removed, and the file layout is unchanged.

| Name | Old status | New status | Note |
|---|---|---|---|
| CancelSandBoxUpgrade | planned | done | Implemented in gbot.service.sandbox |
| ForceRecreateSandBox | planned | done | Implemented in gbot.service.sandbox |
| GetSandBoxRunState | planned | done | Implemented in gbot.service.sandbox |
| GetSandBoxUpgradeSchedule | planned | done | Implemented in gbot.service.sandbox |
| RecreateSandBox | planned | done | Implemented in gbot.service.sandbox |
| RescheduleSandBoxUpgrade | planned | done | Implemented in gbot.service.sandbox |
| ScheduleSandBoxUpgrade | planned | done | Implemented in gbot.service.sandbox |
| UpdateGrokBotUserRuntimeSettings | planned | done | Implemented in gbot.service.sandbox |
| getHostSettings | planned | declined | Desktop-machine setting; gbot works with backend-hosted bots. |
| isEgressTunnelAvailable | planned | declined | Desktop-machine setting; gbot works with backend-hosted bots. |
| setHostSettings | planned | declined | Desktop-machine setting; gbot works with backend-hosted bots. |
| updateHostNow | planned | handoff | Updates a desktop host computer; use the Grok Bot app. |

All 12 match the brief's names, statuses and notes.

## 3. Out-of-scope files changed

None. The 10 changed files are all in the brief's scope: `docs/gbot.md`, `docs/parity.json`, `docs/tui/sandbox.md`,
`gbot/commands/sandbox.py`, `gbot/service/sandbox.py`, `gbot/tui/slash/sandbox.py`,
`tests/gbot_suite/snapshots/panel-sandbox.svg`, `tests/gbot_suite/test_cli_sandbox.py`,
`tests/gbot_suite/test_service_sandbox.py`, `tests/gbot_suite/test_tui_sandbox.py`. No existing snapshot changed.

## 4. Verifier output

Each command was run from the repository root after `uv sync --locked --all-extras --group dev`. Final lines:

```
$ uv run --no-sync pytest tests/gbot_suite -q -p no:cacheprovider
...............................                                          [100%]
1543 passed in 195.61s (0:03:15)
(exit 0)

$ uv run --no-sync ruff check groken gbot tests
All checks passed!

$ uv run --no-sync ruff format --check gbot tests/gbot_suite
215 files already formatted

$ uv run --no-sync basedpyright --level error
0 errors, 0 warnings, 0 notes

$ uv run --no-sync python -m json.tool docs/parity.json > /dev/null && echo parity ok
parity ok
```

The pytest run passes all tests, including the three new suites and the new snapshot. The gates pass, which is why
F1 and F2 are not visible to them.

## Checked and matching the brief

- Names and fields: every dataclass, function and signature the brief names exists with the stated shape. `RPCS`
  matches the eight names. `DEMO_RPCS` is discovered without collisions (no other module defines these RPC names).
- Enums: `RUN_STATES` and `SCHEDULE_STATES` match the orders in `docs/protocol-m5c.md` section 6, and all three
  forms (number, short name, full name) parse to the same value. Unknown values become `unknown`.
- Request payloads: `recreate` sends `preserveData`, `force` and `acknowledgeTerminalUpgradeSchedule`; `force` sends
  `{}`; schedule changes send `timezone`, `localTime`, `recurring`; `cancel` sends `dismissTerminalOutcome`. These
  match section 6, whose fields are non-optional. `update_runtime_settings` sends only the changed field, sends the
  whole `pinnedAgents.agentIds` list, and keeps the allow and block lists when `isEnabled` changes.
- Validation before any call: `check_schedule` runs before every schedule call in the service, the CLI and the TUI
  form (confirmed by call counts: 0 calls on each bad value).
- CLI: every change needs `--yes`, which `_require_confirmation` enforces (`gbot/commands/approvals.py:64-66`). A
  discard or force in a terminal asks for the word `recreate`. A refused change exits 1 with the server's message.
- TUI: every change calls `_writable` or `_Form.submit` (read-only refuses with "Read-only mode"). `ConfirmScreen`
  focuses Cancel (`gbot/tui/screens/confirm.py`). Work runs in a thread worker. Notices go through `terminal_safe`
  with `markup=False`. `DetailPanel` runs body, fields and actions through `terminal_safe` too.
- Refusals: they go through `gbot.service.errors.refusal`, and all three layers show them as plain notices.
- Secrets: none in M5g's scope. `RuntimeSettings.raw_auto_review` holds the user's instruction text. It is
  `repr=False` and never reaches CLI JSON or the TUI.
- Docs: every CLI flag of `gbot sandbox` and `gbot settings` is documented in `docs/gbot.md`. The TUI keys and
  confirm texts in `docs/tui/sandbox.md` match the code, except for the claim in F2.
- Snapshot: only `panel-sandbox.svg` was added. `assert_snapshot` compares strictly and never auto-creates.

## Unresolved (not counted as findings)

- The TUI recreate has no control for `acknowledgeTerminalUpgradeSchedule`; the CLI has `--acknowledge-schedule`.
  The brief names no TUI control for it. Under a terminal schedule, the TUI shows only the server's reason.
- `pinnedAgents.agentIds` receives the roster `bot.id` values (`gbot/tui/slash/sandbox.py:314-315`,
  `gbot/commands/sandbox.py:196`). The protocol gives no id type for `pinnedAgents` in `GetGrokBotUserRuntimeSettings`,
  so whether roster ids are accepted is untested here. [INFERRED]
- `tests/gbot_suite/test_docs.py:41-42` checks documented flags against the parser in one direction only. The new
  docs happen to cover every flag, which was checked by hand.
