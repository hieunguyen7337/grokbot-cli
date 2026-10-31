# Review: unit M5e (team bots), branch claude/unit-m5e-review-ywqjk5

## 1. Findings

Orchestrator note: skip findings 5 and 7. Finding 5 needs `gbot/tui/panels/kit.py` (out of scope) and finding 7 is handled at merge; the orchestrator does both on gbot-tui.

No blocker or major defect found. The tests pass, the verifier is clean, and the request payloads, enum parsing,
refusal handling, read-only checks and confirm texts match the brief. The findings below are minor.

1. **minor** `gbot/commands/team.py:115-118`: the change path confirms before it validates the input or resolves the
   bot. Input: a terminal, `gbot team Bot --approve " "` (no `--yes`). The user is asked `Confirm [y/N]`, answers `y`,
   and only then gets `Give the review item ID.` (team.py:157-158). Nothing is sent, but the prompt is misleading.
   `[OBSERVED gbot/commands/team.py:115-118]`

2. **minor** `gbot/commands/team.py:157-159`: the ID is checked with `item_id.strip()` but sent unstripped. Input:
   `gbot team Bot --approve " item-1" --yes`. The request carries `itemId: " item-1"`, not `item-1`.
   `[OBSERVED gbot/commands/team.py:159]`

3. **minor** `gbot/service/team_bots.py:306-310`: `set_link_preview` returns the server's echoed `setting.enabled`,
   and False when `setting` is absent. If a reply omits `setting` after a successful `--set on`, the CLI and TUI
   report `Link previews are off`. Input: a reply `{}` to `SetGrokBotTeamLinkPreview` with `enabled: true`.
   `[INFERRED]` (the protocol note gives the reply as `setting`; the omitted-field case is not documented)
   `[OBSERVED gbot/service/team_bots.py:310]`

4. **minor** `gbot/service/team_bots.py:234`, `:204`, `:276`: the top-level reply is not checked. `team_agents`,
   `_summary` and `bot_memories` call `.get` on whatever `transport.rpc` returned. Input: a `None` or list reply, for
   example `FakeTransport(rpcs={"ListGrokBotTeamAgents": None})`. That raises `AttributeError`, though the brief says
   nothing raises on an odd shape. The CLI shows it as an error rather than a notice, and the TUI shows it as the
   worker's error text. `[OBSERVED gbot/service/team_bots.py:234]`

5. **minor** `gbot/tui/panels/kit.py:237-240` with `gbot/tui/slash/team.py:183-188`: `ListPanel.on_key` dispatches
   from `self.actions`, not from `visible_actions()`. So a key that is hidden still runs its handler. Examples: `a`
   or `r` on the summary row, and `p` with no marks. Each handler has a guard (`team.py:256-257`, `team.py:333-334`),
   so nothing bad happens today. The "shown only when they apply" rule holds only for the display. A future handler
   without a guard would act on hidden keys. `[OBSERVED kit.py:237-240]`

6. **minor** `docs/gbot.md:778`: `--role` appears only in the usage line. No prose describes it, while every other
   flag gets a sentence. `[OBSERVED docs/gbot.md:778]`

7. **minor** (process) the brief's parity comparison against `origin/gbot-tui` is out of date. That branch has three
   commits this branch lacks (`1028dfb` M5c merge, `5ece2e7`, `25b4f74` rebuilt parity). Comparing this file with the
   tip of `origin/gbot-tui` shows six publishing entries as changed (`done` to `planned`). This branch does not change
   them. The real change is the 8 entries in section 2 below, compared with the merge base `2bac1fd`. The branch
   should be rebased or merged with `origin/gbot-tui` before it lands, so the parity table picks up M5c.
   `[OBSERVED git log origin/gbot-tui..HEAD; git log HEAD..origin/gbot-tui]`

8. **minor** (test gap) `tests/gbot_suite/test_cli_team.py`: no test covers an empty or whitespace `--approve` or
   `--reject` ID, or the order of confirmation against validation (finding 1), and none covers a `--approve` ID with
   surrounding spaces (finding 2). `[OBSERVED tests/gbot_suite/test_cli_team.py]`

## 2. Parity entries changed (against merge base `2bac1fd`)

All 8 match section 4 of the brief: status `planned` to `done`, note `""` to `Implemented in gbot.service.team_bots`.

| Name | Old status | New status | New note |
|---|---|---|---|
| ListGrokBotTeamAgents | planned | done | Implemented in gbot.service.team_bots |
| GetGrokBotTeamContextSummary | planned | done | Implemented in gbot.service.team_bots |
| ListGrokBotTeamReviewItems | planned | done | Implemented in gbot.service.team_bots |
| ResolveGrokBotTeamReviewItem | planned | done | Implemented in gbot.service.team_bots |
| ListGrokBotUserBotMemories | planned | done | Implemented in gbot.service.team_bots |
| PromoteGrokBotMemoriesToTeam | planned | done | Implemented in gbot.service.team_bots |
| GetGrokBotTeamLinkPreview | planned | done | Implemented in gbot.service.team_bots |
| SetGrokBotTeamLinkPreview | planned | done | Implemented in gbot.service.team_bots |

## 3. Out-of-scope files changed

None. `git diff --stat origin/gbot-tui...HEAD` lists only in-scope files: `docs/gbot.md`, `docs/parity.json`,
`docs/tui/team.md`, `gbot/commands/team.py`, `gbot/service/team_bots.py`, `gbot/tui/slash/team.py`,
`tests/gbot_suite/test_cli_team.py`, `tests/gbot_suite/test_service_team_bots.py`,
`tests/gbot_suite/test_tui_team.py`, `tests/gbot_suite/snapshots/panel-team.svg`. Only the new snapshot was added.

## 4. Verifier output (final lines, `uv run --no-sync`)

```
$ pytest tests/gbot_suite -q -p no:cacheprovider
1519 passed in 193.16s (0:03:13)

$ ruff check groken gbot tests
All checks passed!

$ ruff format --check gbot tests/gbot_suite
215 files already formatted

$ basedpyright --level error
0 errors, 0 warnings, 0 notes

$ python -m json.tool docs/parity.json > /dev/null && echo parity ok
parity ok
```
