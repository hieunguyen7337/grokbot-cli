# central-7c: build secrets-vault and skill rows (parity group a)

Repository: grokbot-cli. Work at the arm's effort.

## 1. Goal

Build these planned rows of `docs/parity.json` against fakes and move them to `done`:
- `setBoxSecrets` (gateway command, area secrets-vault): `gbot/service/secrets.py`, `gbot/commands/secrets.py`,
  `gbot/tui/slash/secrets.py`. Docs: `docs/protocol-m4b.md:179`. It writes secrets: the CLI verb takes values from
  stdin or a file (never from argv), needs `--yes`, and never prints a value, in output, errors or logs. The reply is
  status only.
- `NudgeOnePasswordAccessRequest` (backend RPC, area secrets-vault): `gbot/service/vault.py`,
  `gbot/commands/vault.py`, `gbot/tui/slash/vault.py`. Docs: `docs/protocol-m4b.md:255`.
- `AddGrokBotAgentSkill`, `RemoveGrokBotAgentSkill`, `UpdateGrokBotAgentSkill` (backend RPCs, area plugins-skills):
  find the module that holds the skill and plugin projections (grep `Skill` in `gbot/service/plugins.py` and
  `gbot/service/workflows.py`), with `gbot/commands/skills.py` and `gbot/tui/slash/skills.py`.
  Docs: `docs/protocol-m4a.md:168`. Remove and update need `--yes` like the area's other write verbs.
Done means: all five rows `done`, tests green, docs updated.

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
