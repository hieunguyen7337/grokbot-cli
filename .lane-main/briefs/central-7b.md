# central-7b: build automation and connector-settings rows (parity group a)

Repository: grokbot-cli. Work at the arm's effort.

## 1. Goal

Build these planned rows of `docs/parity.json` against fakes and move them to `done`:
- `ListGrokBotAgentRoutines`, `SetGrokBotAgentRoutineEnabled` (backend RPCs, area automations):
  `gbot/service/automations.py`, `gbot/commands/automations.py`, `gbot/tui/slash/automations.py`.
  Docs: `docs/protocol-m4a.md:306` (cover the documented unsupported-account error too).
- `GetGrokBotUserMcpSettings`, `SetGrokBotUserMcpSettings` (backend RPCs, area connectors):
  `gbot/service/connectors.py`, `gbot/commands/connectors.py` (or `connector.py`, whichever holds settings verbs),
  `gbot/tui/slash/connectors.py`. Docs: `docs/protocol-m4a.md:20` and `:112` (the keep-disabled-tools flag).
Done means: all four rows `done`, tests green, docs updated.

## 2. Files

In scope: the area modules named above under `gbot/service/`, `gbot/commands/`, `gbot/tui/slash/`; their tests in
`tests/gbot_suite/` (the existing `test_service_<area>.py`, `test_cli_<area>.py`, `test_tui_<area>.py` files, or new
ones with those names); `docs/gbot.md` (the area's section) and `docs/tui/<area>.md` if it exists; and in
`docs/parity.json` ONLY the rows listed above (set `status` to `done`, clear the `triage ...` note to `""`).
Out of scope: every other module and row, `gbot/protocol.py` (each area module registers itself through its own
module-level `COMMANDS` / `RPCS` and `DEMO_COMMANDS` / `DEMO_RPCS`; copy that pattern), `groken/`, other areas'
files, and Textual SVG snapshots other than ones your change itself breaks (list any you update).

## 3. Constraints

- SAFETY: tests use fakes, `FakeService`, the area's `DEMO_*` data and `httpx.MockTransport` only. NEVER run `gbot`
  without `--demo`, NEVER run any command with `--yes` outside a test, NEVER call the live Grok Bot or Cursor API
  (`api2.cursor.sh` or any gateway URL), NEVER read token files (`~/.config/groken`, `%LOCALAPPDATA%\grokbot-cli`).
  Never print or log a secret value; demo data uses obvious placeholders.
- Read first: the row's doc reference in `.review/central-6.md` (and `docs/protocol*.md` around it) and the area's
  existing service module. Build only what the docs state; where a reply field is unknown, keep it as a raw mapping
  and say so in the return.
- For each row: service method (with its argument mapping and reply parsing), a CLI verb where it helps an agent
  (stable `--json`, exit codes, non-interactive flags; anything that writes takes `--yes` or a confirmation, matching
  the area's existing write verbs), a TUI surface only where the area's slash panel already has a natural place, demo
  data, docs, and tests. Failing test first.
- Every `done` row must be declared by code (`COMMANDS` / `RPCS`), or
  `tests/gbot_suite/test_service_core.py::test_parity_file_matches_the_code` fails.
- `docs/parity.json`: write it only through Python (`json.load`, edit, `json.dumps(data, indent=2) + "\n"`, UTF-8,
  LF). Validate with `python -m json.tool docs/parity.json`.
- No fixed sleeps. Plain English, short sentences, no emoji; UTF-8 without BOM, LF line endings.
- Verifier (Windows; run only these, never the full suite):
  `.venv/Scripts/python -m pytest -q tests/gbot_suite/test_service_core.py <the area test files you touched>`
  `.venv/Scripts/ruff check <touched .py files>` and `.venv/Scripts/ruff format --check <touched .py files>`
  `.venv/Scripts/python -m json.tool docs/parity.json` (exit 0).

## 4. Return contract (at most 60 lines)

- Files changed, with file:line of each new service method and CLI verb.
- Per row: done, or not done with the reason.
- The verifier commands with their real output (last lines).
- Snapshots updated (or "none"), and anything unresolved, marked `[OBSERVED path:line]` or `[INFERRED]`.
