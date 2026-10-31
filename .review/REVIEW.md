# Review of unit M5f (bot files, user-store files and library)

Scope: `git diff --stat origin/gbot-tui...HEAD` (12 files, all in the brief's scope). Each finding was checked by reading
the file and, where marked OBSERVED, by running the function or the test in this checkout.

## 1. Findings

Most severe first.

1. **major**: `gbot/commands/files.py:194` (`Merged {len(wanted)} pins. {len(pins)} pins now.`), with
   `gbot/service/library.py:186-188` (a `not_found` refusal returns `()`).
   - Wrong: `gbot library BOT --merge-pins FILE --yes` on a refused merge prints a success line and exits 0. The
     brief says a refused single change exits 1 with the server's message. The service-level empty tuple is what the
     brief asks for, but the CLI turns it into a success that nothing confirmed.
   - Input: `MergeGrokBotLibraryPins` replies `ConnectError(404, {"code": "not_found"})` and the file holds one pin.
     Output: `Merged 1 pins. 0 pins now.`, exit 0.
   - The test locks this in: `tests/gbot_suite/test_cli_files.py:212-214` asserts `== 0` for the `not_found` case.
   - [OBSERVED tests/gbot_suite/test_cli_files.py:212]

2. **minor**: `gbot/commands/files.py:153-157` (`_pin_from_json`).
   - Wrong: the "each pin needs a kind" check at line 158 is unreachable when the row has no `kind`. The dataclass
     constructor fails first with its own message.
   - Input: a merge file holding `[{"key": "k1"}]`.
   - Output: `Pin.__init__() missing 1 required positional argument: 'kind'`, exit 1, not the intended sentence.
   - [OBSERVED: called `_pin_from_json({"key": "k1"})` in a scratch run]

3. **minor**: `gbot/service/library.py:112-129` (`pin_from_wire`, the page and media branches).
   - Wrong: a pin with an empty target object is kept. The brief says pins with no known target are dropped.
   - Input: `{"page": {}, "pinnedAtMs": "1"}` returns `Pin(kind='page', ...)` with every field empty;
     `{"media": {}}` returns `Pin(kind='media', media_kind='unspecified')`.
   - Consequence: the CLI prints a blank `page` line in `gbot library` (`gbot/commands/files.py:209`), and a merge
     sends the empty target back to the server.
   - Not covered: `tests/gbot_suite/test_service_library.py:47-49` only tests `{}`, `{"pinnedAtMs": "1"}`, `"x"`,
     `None` and `{"page": 3}`.
   - [OBSERVED by calling `pin_from_wire` in a scratch run]

4. **minor**: `gbot/service/library.py:61` (`"kind": MEDIA_PREFIX + self.media_kind.upper()`) with
   `gbot/service/library.py:98-104` (`_media_kind` returns `unknown` for unrecognised values).
   - Wrong: an unrecognised media kind read from the server is written back as a non-enum value.
   - Input: `{"media": {"kind": 99}}` read, then `to_wire()`, gives
     `GROK_BOT_LIBRARY_PIN_MEDIA_KIND_UNKNOWN`. A merge of that pin sends the invalid enum to the server.
   - The brief says unknown values become `unknown` and enums are sent as full names; a value that parsed to
     `unknown` should not be sent as a full name.
   - [OBSERVED by calling `to_wire()` in a scratch run]

5. **minor**: `gbot/service/library.py:152` (`bool(row.get("createdByBot"))`).
   - Wrong: the parse is not defensive about a string bool.
   - Input: a doc row with `"createdByBot": "false"` gives `created_by_bot=True`.
   - [OBSERVED by calling `library_docs` in a scratch run]. The protocol note says `bool`, so the server is probably
     not sending strings: [INFERRED] this is a hardening gap, not a known server behaviour.

6. **minor**: `gbot/tui/slash/bot_files.py:244` (`f"Delete {row.label} from {self.bot.name}?"`) with the row label
   built at `gbot/tui/slash/bot_files.py:159-164` (`f.name or f.path`).
   - Wrong: for a user-store row the confirmation names the file name, but the call deletes by path (`target` at
     line 240). The brief asks for the user-store path on those rows.
   - Input: two user-store files `/a/prefs.json` and `/b/prefs.json`. Both confirms read `Delete prefs.json from Helper?`
     and the user cannot tell which one will go.
   - [OBSERVED by reading the code and the row construction]

7. **minor**: `gbot/tui/slash/bot_files.py:187-189` and `gbot/tui/slash/bot_files.py:197-198`.
   - Wrong: `x` delete is offered and sent for bot files when `listing.can_edit` is False. Only `u` is gated on
     `can_edit`.
   - Input: a bot whose listing replies `canEdit: false` with one file. The footer shows `x delete`, and `x` plus
     confirm sends `DeleteGrokBotAgentFile`.
   - The brief says actions appear only when they apply. [INFERRED] deleting a bot file needs the same edit right as
     uploading one, so the server would refuse. No test covers `x` on a read-only listing.
   - [OBSERVED by reading the code]

8. **minor**: `gbot/tui/slash/bot_files.py:376` (`webbrowser.open(url)`).
   - Wrong: the brief asks for "the shared opener the M4 panels use". No such shared helper is used by the M4 panels:
     `gbot/tui/slash/attachments.py:180`, `gbot/tui/slash/computer.py:105` and `gbot/tui/slash/trays.py:171` each call
     `webbrowser.open` directly. The https check is local to this panel.
   - [OBSERVED by grep]. The brief's wording cannot be matched as written; the behaviour matches the other panels.

9. **minor**: tests that cannot catch the defects above or that assert nothing.
   - `tests/gbot_suite/test_service_bot_files.py:97` and `:104` (`real = httpx.put` / `assert real is httpx.put`): a
     tautology. `monkeypatch` on line 87 is unused.
   - `tests/gbot_suite/test_service_bot_files.py:122-136` (the default PUT test) asserts the content type, timeout and
     body but never that `headers` are passed to `httpx.put`. The brief requires the exact returned headers on the PUT.
   - No test for `_pin_from_json` on a row without `kind` (finding 2) or for `{"page": {}}` (finding 3).
   - No test for the read-only refusal inside the confirmed worker (`gbot/tui/slash/bot_files.py:73-74`).

Checked and correct (no finding): the six bot-file and four library RPC names and payloads; `agentId` on every call;
`sizeBytes` and `contentType` sent as the brief says; `sha256Hex` lowercase; the `Storage refused the upload (HTTP
<status>).` sentence with no URL or headers; the storage network error replaced without its cause; finish with the
token; a finish reply without `file` is an error; pagination from `""` with the repeated-token and 100-page stops;
`--yes` on every CLI change (`files` and `library`); refusals to notices in the TUI and CLI; `terminal_safe` on
TUI and CLI output; `Upload <file> (<size>) to <bot>?`, `Delete <file> from <bot>?` and the pin/unpin confirms;
Cancel focused in `ConfirmScreen`; read-only refusal before the confirm; the `o` key on https links only; the docs
sections list every flag (`--upload`, `--delete`, `--delete-user-file`, `--pin`, `--unpin`, `--merge-pins`, `--yes`,
`--json`).

## 2. Parity entries changed

All ten entries match the brief (status `planned` to `done`; note as the brief says). Changes are in
`docs/parity.json` only, and the diff is exactly these ten entries (20 insertions, 20 deletions).

| Name | Old status | New status | Note |
|---|---|---|---|
| ListGrokBotAgentFiles | planned | done | Implemented in gbot.service.bot_files |
| BeginGrokBotAgentFileUpload | planned | done | Implemented in gbot.service.bot_files |
| FinishGrokBotAgentFileUpload | planned | done | Implemented in gbot.service.bot_files |
| DeleteGrokBotAgentFile | planned | done | Implemented in gbot.service.bot_files |
| ListGrokBotUserStoreFiles | planned | done | Implemented in gbot.service.bot_files |
| DeleteGrokBotUserStoreFile | planned | done | Implemented in gbot.service.bot_files |
| ListGrokBotLibraryDocs | planned | done | Implemented in gbot.service.library |
| ListGrokBotLibraryPins | planned | done | Implemented in gbot.service.library |
| SetGrokBotLibraryPin | planned | done | Implemented in gbot.service.library |
| MergeGrokBotLibraryPins | planned | done | Implemented in gbot.service.library |

## 3. Out-of-scope files changed

None. The twelve changed files are `docs/gbot.md`, `docs/parity.json`, `docs/tui/bot-files.md`,
`gbot/commands/files.py`, `gbot/service/bot_files.py`, `gbot/service/library.py`, `gbot/tui/slash/bot_files.py`,
`tests/gbot_suite/snapshots/panel-bot-files.svg` (new, the only snapshot added), and the four new test files.

## 4. Verifier commands (final output lines)

- `uv run --no-sync pytest tests/gbot_suite -q -p no:cacheprovider`
  ```
  ........................................................................ [ 95%]
  ................................................................         [100%]
  1504 passed in 183.07s (0:03:03)
  ```
- `uv run --no-sync ruff check groken gbot tests`
  ```
  All checks passed!
  ```
- `uv run --no-sync ruff format --check gbot tests/gbot_suite`
  ```
  217 files already formatted
  ```
- `uv run --no-sync basedpyright --level error`
  ```
  0 errors, 0 warnings, 0 notes
  ```
- `uv run --no-sync python -m json.tool docs/parity.json > /dev/null && echo parity ok`
  ```
  parity ok
  ```

The pytest run is the full `tests/gbot_suite` directory, not only the four new files. All 1504 tests pass, so the
defects above are not caught by the existing suite.
