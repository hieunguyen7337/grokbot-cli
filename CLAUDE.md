# grokbot-cli

@AGENTS.md

## Main cloud session (Claude Usage Optimizer)
- The session started by `lane main` may commit to and push its own branch (the claude/... branch it is on),
  including empty marker commits whose subject starts with "orch: ".
- No session pushes main or a release branch, a tag or a pull request, and none force-pushes. `gbot-windows` and
  `gbot-tui` are integration branches: only the owner's local session merges into them.
- Never call the live Grok Bot API from tests or workers, and never read token files (`~/.config/groken`,
  `%LOCALAPPDATA%\grokbot-cli`). Tests use fakes.
