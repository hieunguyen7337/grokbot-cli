# Review: unit M5a (sharing and access for a bot)

Branch `claude/unit-m5a-review-eq0b9w`, reviewed at HEAD `f0c620c` (lane start commit; no code changed).
Branch base: merge-base `2bac1fd` with `origin/gbot-tui`. The tip of `origin/gbot-tui` (`dc17c7e`) is 21 files
ahead of that base; the unit's own diff (`git diff --stat origin/gbot-tui...HEAD`) is unaffected by that.

## 1. Findings

Most severe first. `[OBSERVED path:line]` means read in this branch and, where stated, run; `[INFERRED]` means
reasoned from the code or the protocol note without a run.

### Major

1. **`--team-row on` without `--role` silently demotes an existing manager team row to user.**
   - `gbot/commands/share.py:304` passes `args.role or "user"` to `with_team_row`.
   - `gbot/service/sharing.py:537-542`: when a team row already exists, `with_team_row(..., on=True, role)` replaces
     its role with the argument, so the default `user` overwrites `manager`.
   - Input: a bot whose team row is `manager`; `gbot share BOT --team-row on --yes`. The access list sent to
     `UpdateGrokBotAgentAccess` has the team row as `user`. No `--role` was given, so the demotion was not requested.
   - Verified by running `sharing.with_team_row(AccessState(team_row_on=True, team_row_off_allowed=True,
     principals=(Principal('team', None, 'manager'),)), True)`; it returned `Principal(kind='team', ref=None, role='user')`.
   - [OBSERVED gbot/commands/share.py:304] [OBSERVED gbot/service/sharing.py:541]

### Minor

2. **Non-refusal change outcomes exit 1 with the sentence on stdout, not as the error message.**
   - `gbot/commands/share.py:319-324` (`_outcome`) writes the sentence through `ctx.out.write` and returns 1 for any
     outcome other than the good one.
   - The brief asks that a refused single change exit 1 with the server's message as the error message. A
     `NO_TEAM`, `UNSUPPORTED_HARNESS`, `BUSY`, `INELIGIBLE` or `UNSUPPORTED` reply on `--team-visible`, `--clone-to-team`
     or `--share-in-place` therefore prints the message on stdout and leaves the error channel empty. The
     permission-denied refusals do use the error channel (`share.py:558-562`).
   - Input: `gbot share BOT --team-visible --yes` on this personal account, where the reply is `NO_TEAM`. Exit code 1,
     message on stdout.
   - [OBSERVED gbot/commands/share.py:319-324] [OBSERVED gbot/commands/share.py:558-562]

3. **`t` never turns the team row on as manager, so the manager-team-row question is not reachable from `t`.**
   - `gbot/tui/slash/sharing.py:505-520` (`toggle_team`) always calls `with_team_row(state, on)` with the default
     role `user`.
   - The brief's `t` key says a manager team row asks `Make everyone in the team a manager of <bot>?`. In this branch
     that question is reached only through `a` (`sharing.py:419-423` via `add_access`) or `r` on the team row.
     `docs/tui/sharing.md:36` documents the same narrower behaviour, so the doc and code agree with each other but not
     with the brief.
   - Input: this account has no team row; press `t`. The row is added as `user`, with no manager question.
   - [OBSERVED gbot/tui/slash/sharing.py:505-520] [OBSERVED gbot/tui/slash/sharing.py:419-423]

4. **The TUI doc says a failure is retried with `r`; no retry exists.**
   - `docs/tui/sharing.md:26` says a failure that is not a refusal shows the error line "with `r` to retry".
   - In `gbot/tui/slash/sharing.py:337-348` (`_failed`, `_finished`) a failure only shows a notice and, for refusals,
     reloads the panel. `r` is "change role" (`sharing.py:241` in `key_handlers`).
   - Input: a `busy` or network failure on `v`. The panel shows the notice; pressing `r` opens the role picker for the
     selected row, not a retry.
   - [OBSERVED docs/tui/sharing.md:26] [OBSERVED gbot/tui/slash/sharing.py:337-348]

5. **The `/invite` doc describes the accept condition more narrowly than the code.**
   - `docs/tui/sharing.md:78` says `a` appears only when the invite "was sent to you and your account is eligible".
   - `gbot/tui/slash/sharing.py:830-838` (`acceptable`) allows a recipient match of `unknown` and an eligibility of
     `None` (the reply did not report eligibility).
   - Input: a preview whose `recipient_match` is `UNKNOWN` (or that has no `eligibility` object) shows `a` Accept, which
     the doc says should not appear.
   - [OBSERVED docs/tui/sharing.md:78] [OBSERVED gbot/tui/slash/sharing.py:830-838]

6. **Test quality: one TUI timer test reads a private Textual attribute.**
   - `tests/gbot_suite/test_tui_sharing.py:685-703` asserts `panel._timer._interval == 1.0`. It does fail if the first
     delay changes, but it depends on a private attribute of Textual's `Timer`, so a Textual upgrade can break it
     without any behaviour change.
   - [OBSERVED tests/gbot_suite/test_tui_sharing.py:685-703]

## 2. Parity entries changed

Compared with the branch's merge-base `2bac1fd` (the unit's own change). Exactly 15 entries changed, all to status
`done` with note `Implemented in gbot.service.sharing`. All 15 are the entries the brief lists; the old status was
`planned` and the old note was empty in each case.

| Name | Old status | New status | Note |
|---|---|---|---|
| AcceptGrokBotAgentAccessInvite | planned | done | Implemented in gbot.service.sharing |
| AddGrokBotAgentManager | planned | done | Implemented in gbot.service.sharing |
| CloneGrokBotAgentToTeam | planned | done | Implemented in gbot.service.sharing |
| CreateGrokBotAgentAccessInvite | planned | done | Implemented in gbot.service.sharing |
| GetGrokBotAgentAccess | planned | done | Implemented in gbot.service.sharing |
| GetGrokBotAgentInPlaceShareStatus | planned | done | Implemented in gbot.service.sharing |
| GetGrokBotAgentLinkAccess | planned | done | Implemented in gbot.service.sharing |
| ListGrokBotAgentAccessInvites | planned | done | Implemented in gbot.service.sharing |
| ListGrokBotAgentManagers | planned | done | Implemented in gbot.service.sharing |
| PreviewGrokBotAgentAccessInvite | planned | done | Implemented in gbot.service.sharing |
| RemoveGrokBotAgentManager | planned | done | Implemented in gbot.service.sharing |
| RevokeGrokBotAgentAccessInvite | planned | done | Implemented in gbot.service.sharing |
| SetGrokBotAgentVisibility | planned | done | Implemented in gbot.service.sharing |
| ShareGrokBotAgentInPlace | planned | done | Implemented in gbot.service.sharing |
| UpdateGrokBotAgentAccess | planned | done | Implemented in gbot.service.sharing |

Note on the tip: comparing against the tip `origin/gbot-tui:docs/parity.json` instead shows 28 changed entries. The
other 13 (publishing entries such as `PublishGrokBotAgent`, `publishSkill`, `unpublishSkill`) differ only because the
tip has moved past this branch's base (`dc17c7e` "Rebuild parity table after M5b"). They are not changes made by this
branch. The branch's `docs/parity.json` diff against its base is the 15 entries above, with no other entry touched.
[OBSERVED via merge-base comparison]

## 3. Out-of-scope files changed

None. `git diff --numstat origin/gbot-tui...HEAD` lists only the brief's files: `docs/gbot.md` (+58), `docs/parity.json`
(15 entries), `docs/tui/sharing.md` (+91), `gbot/commands/share.py`, `gbot/service/sharing.py`, `gbot/tui/slash/sharing.py`,
`tests/gbot_suite/snapshots/panel-share.svg` (+180, new), `tests/gbot_suite/test_cli_share.py`,
`tests/gbot_suite/test_service_sharing.py`, `tests/gbot_suite/test_tui_sharing.py`. No existing snapshot was modified
(`git diff` shows only additions under `snapshots/`).

## 4. Verifier commands (final output lines, run on HEAD)

Command: `uv run --no-sync pytest tests/gbot_suite -q -p no:cacheprovider`

```
1602 passed in 242.85s (0:04:02)
```

Command: `uv run --no-sync ruff check groken gbot tests`

```
All checks passed!
```

Command: `uv run --no-sync ruff format --check gbot tests/gbot_suite`

```
215 files already formatted
```

Command: `uv run --no-sync basedpyright --level error`

```
0 errors, 0 warnings, 0 notes
```

Command: `uv run --no-sync python -m json.tool docs/parity.json > /dev/null && echo parity ok`

```
parity ok
```

(Each run also printed a `warning: The UV_NATIVE_TLS environment variable is deprecated` line on stderr; it is not part
of the tool's result.)

## Summary

The service, CLI and TUI cover the brief's commands, keys, confirms, refusal handling, secret handling and parity
entries, and every verifier passes. One defect is major: `--team-row on` without `--role` silently demotes a manager
team row (finding 1). The rest are minor: exit-code and message channel for non-refusal outcomes (2), the `t` key not
offering the manager question the brief describes (3), two doc statements that do not match the code (4, 5), and one
test that depends on a private Textual attribute (6).
