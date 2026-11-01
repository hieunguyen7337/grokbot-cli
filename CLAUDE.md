# grokbot-cli

@AGENTS.md

## Main cloud session (Claude Usage Optimizer)
- The session started by `lane main` may commit to and push its own branch (the claude/... branch it is on),
  including empty marker commits whose subject starts with "orch: ".
- That session may also merge its own branch into `main` and push `main`, once the batch is reviewed and every gate
  passes on the merge result (owner approval, 2026-10-31). It merges with a merge commit and never force-pushes.
- A compaction never retires that session; only the owner does (owner's call, 2026-10-31). This overrides the kit's
  compaction ceiling (POLICY.md, "Main cloud sessions"): the session does not push `orch: STATUS <n>: replace me`
  after its second compaction, and "past its compaction ceiling" is never a `--side` reason here. After every
  compaction it rebuilds its state from its branch's `orch:` markers, the `.review/` files and the lane ledger before
  it starts new work. If work under way cannot be rebuilt from them, it says so in chat and in an `orch: STATUS`
  marker and redoes that unit rather than guess.
- No session or worker on this repository starts a cloud session with the `create_session` tool, because workers
  were leaving empty sessions behind (owner's call, 2026-11-01). `.claude/settings.json` denies that tool. The rule
  also covers subagents, which share the session's permission rules, and it takes effect without a restart. A side
  session starts only through `lane <claude lane> --cloud --side "<reason>"`, which runs the `claude --cloud`
  command and not the tool.
- No other session pushes `main`. No session pushes a release branch, a tag or a pull request, and none force-pushes.
  `gbot-windows` and `gbot-tui` are integration branches: only the owner's local session merges into them.
- Never call the live Grok Bot API from tests or workers, and never read token files (`~/.config/groken`,
  `%LOCALAPPDATA%\grokbot-cli`). Tests use fakes.
