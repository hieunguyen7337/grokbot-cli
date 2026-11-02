# central-6-triage: sort the 43 planned rows of docs/parity.json

Repository: grokbot-cli. Work at the arm's effort. This unit changes NO code.

## 1. Goal

For every entry in `docs/parity.json` whose `status` is `planned` (43 rows: M4 26, M1 6, M2 6, M3 5), decide one group:
- (a) buildable against fakes from what the docs and existing service code already say;
- (b) needs the owner's live check or an account action: OAuth or connect completion (for example
  `completeGithubConnect`, `completeMcpOAuth`), passkeys, or anything that returns a credential or secret (for example
  `getAutomationWebhookCredential`);
- (c) should be declined or become a handoff (the app does it in a web view, the desktop only, no use to an agent).
Give each a one-line reason in plain English. Done means: every planned row has a note starting with `triage (a):`,
`triage (b):` or `triage (c):` followed by the reason, and `.review/central-6.md` holds the table.

## 2. Files

In scope (write): `docs/parity.json` (only the `note` field of the 43 planned rows; keep `status` as `planned`, keep
every other field and row byte-for-byte), and a new `.review/central-6.md`.
Read: `docs/protocol*.md`, `docs/parity.json`, `gbot/service/*.py`, `gbot/commands/*.py`, `gbot/tui/` (bounded: only
to see whether a nearby command is already built). Search with `grep -rn <name> docs gbot` per row; if a name has no
hit in `docs/`, say "not in our protocol notes" in the reason and lean to (c) or (b).
Out of scope: any `.py` file, tests, snapshots, other docs.

## 3. Constraints

- SAFETY: never call the live Grok Bot or Cursor API, never run `gbot` (not even `--demo` is needed here), never read
  token files (`~/.config/groken`, `%LOCALAPPDATA%\grokbot-cli`), never open the Grok Bot app bundle.
- Write `docs/parity.json` only through Python: load with `json.load`, change the notes, write with
  `json.dumps(data, indent=2) + "\n"` (UTF-8, LF). That is the file's current exact format; check it round-trips
  unchanged before you edit (`python -c "import json;s=open('docs/parity.json',encoding='utf-8').read();print(s==json.dumps(json.loads(s),indent=2)+'\n')"` prints True).
- Notes must not contain secrets, bot names, ids, URLs with tokens, or account data. Plain English, no emoji.
- `.review/central-6.md`: a short intro, then one Markdown table with columns: name, milestone, area, group, reason,
  doc reference (`docs/<file>.md:<line>` or "none"). Then a count per group, and for group (a) a suggested batch
  order by area, smallest first.
- Verifiers (Windows): `.venv/Scripts/python -m json.tool docs/parity.json > NUL` (exit 0), the round-trip check
  above (True), and `.venv/Scripts/python -m pytest -q tests/gbot_suite/test_service_core.py -k parity`.
  Also: `git diff --stat` must show only those two files.

## 4. Return contract (at most 60 lines)

- Files changed.
- The count per group, and the names in group (b).
- The verifier commands with their real output.
- Anything unresolved (rows you could not decide), marked `[OBSERVED path:line]` or `[INFERRED]`.
