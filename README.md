# Claude Usage Optimizer

Claude Usage Optimizer makes every Claude Code session on a machine spend its Claude plan on planning, review and
judgement. Execution and read-only legwork go to cheaper worker lanes, and every lane's remaining
quota is visible. [IMPROVING.md](IMPROVING.md) explains how lessons become published kit improvements.

| Path | What it is |
|---|---|
| `POLICY.md` | The shared usage policy. Imported into `~/.claude/CLAUDE.md` as `@~/.claude/usage-optimizer/POLICY.md` |
| `IMPROVING.md` | How the kit records lessons, updates its research and methods, and builds and publishes releases |
| `improve/` | Reusable audit and release briefs |
| `bin/lane` | One dispatcher for nine lanes on four CLIs: luna, terra, sol and astra/codex, haiku, sonnet and opus/claude, gemini/agy, glm/cline. It checks each arm against the catalog, encodes each CLI's failure modes, masks credentials, prints a verdict, and records every run's usage, time, ETA and peak memory in a ledger; it waits for memory before launching. A Claude arm can also run as a subagent of the main session (`--subagent`) or in a cloud VM (`--cloud`, and `codex-cloud`) |
| `bin/lane-stats` | Turns the run ledger into decisions: `pick` chooses the next arm to run (with its ETA), `review` records each run's outcome, `report` shows the usable rate against usage, time and peak memory per lane, effort and class, `recommend` shows which classes have locked in, `arms` lists the catalog, `eta` estimates a run's wall-clock time, `export` and `import` pool runs across machines |
| `bin/lane-mask` | The Linux credential mask (mount namespace) that `lane` uses. Windows has no mask |
| `bin/lane-term` | Runs one command in a fresh pseudo-terminal (ConPTY on Windows, a pty elsewhere), types scripted answers to its prompts, stops it once a given text appears, and saves what the terminal showed. For programs that refuse to run without a terminal, such as `claude --cloud` |
| `bin/usage-status` | Headroom across Claude, Codex and Gemini, and this machine's memory: how many more workers of each provider fit. Codex is read live from its app-server and falls back to the newest rollout when needed |
| `bin/turn-meter` | Records every turn's list-price cost, time and the meters before and after it. The installer runs it as the `UserPromptSubmit` and `Stop` hook; `eta` records Claude's own estimate of the time left, and `current` (time so far and to go), `report` (by turn or session) and `calibrate` (cost and estimate accuracy) read the record; `census` counts every Claude Code and Codex session on the machine, kit or not |
| `bin/claude-statusline` | A two-line statusline with session context, the running turn's time and share, and the kit's name and version (`Usage Optimizer 2026-10-29.3`, or the release whose policy the session last loaded and the newer one installed) on line one, and grouped Claude/Codex quota windows on line two; colors usage by level, fits the terminal width, and logs Claude's rate limits for `usage-status` |
| `bin/claude-prompts` | Lists the questions typed in a session (`--latest`, `--session-id ID` or `--transcript PATH`; `--text` for people, JSON otherwise). Behind the mobile view's question list (`.`) |
| `mods/mobile-view/` | A Claude Code mod that makes the terminal read like the Claude mobile app (see [Mobile view](#mobile-view)). Installed to `~/.claude/skills/mobile-view/` |
| `mods/compact-at-rest/` | A Claude Code mod that compacts the conversation right after an answer once the context reaches 90% of `autoCompactWindow`, rather than mid-turn (`USAGE_OPTIMIZER_COMPACT_NEAR` sets the percent, `USAGE_OPTIMIZER_COMPACT_AT_REST=off` turns it off). Installed to `~/.claude/skills/compact-at-rest/`, with or without `--no-view` |
| `output-styles/Mobile.md` | The output style that goes with it: a sentence of narration around each batch of tool calls, no long code in replies, a self-contained final answer |
| `agents/` | `scout`, `digest`, `verifier` and `researcher` subagents (Sonnet, except verifier), and one `lane-<lane>-<effort>` worker per Claude arm for `lane --subagent`, generated from `arms.json` by `tools/make-lane-agents.py` |
| `arms.json` | The arms catalog: each arm is one lane, model and effort, with its status, classes, weight and priors. Machine-local arms go in `~/.config/lanes/arms.local.json`. Installed to `~/.claude/usage-optimizer/arms.json` |
| `LANES.md` | Each lane's raw CLI contract and gotchas, for when `bin/lane` is unavailable. Installed to `~/.claude/usage-optimizer/LANES.md` |
| `settings.fragment.json` | Settings merged into `~/.claude/settings.json`: most only where a key is absent; the view keys (`view_overwrite`) are set, unless you changed one by hand after an earlier install |
| `install.sh` | An idempotent installer that backs up what it replaces. `--dry-run` shows the plan |
| `tools/make-bundle.sh` | Builds `dist/claude-usage-optimizer-bundle.sh`, a single self-extracting file for other machines |
| `SETUP_PROMPT.md` | The prompt to paste into Claude Code on another machine |

`bin/lane-bench` is the kit's own benchmark. `run` runs a review suite across lane arms under the task-limit and meter gates. It is a capability test, so it runs only when the user approves it, and it refuses to start without `--approved "<who, when>"`. `grade` and `stats` score the runs (recall with Wilson and bootstrap intervals, false alarms, usable rate, cost against the weekly window), `compare` sets the arms against the public numbers in `findings/public.json`, and `priors` writes measured priors into an `arms.local.json`. The suite format and the rules for planted defects are in `measure/SUITE.md`. The kit ships tools and no suite items.

## Measurements and findings

- `measure/`: reproducible Claude and Codex meter probes and fits; see [the commands](measure/README.md).
- `findings/`: [measured plan sizes, weights and evidence](findings/FINDINGS.md), also in JSON.
- `lane-bench`: measure model × effort on your own review suite and write measured priors. Running a suite needs the user's approval. Its `run` works on Linux, macOS and Windows: since 2026-10-28 it starts `lane` and `usage-status` through their `.cmd` wrappers or Python on Windows and stops a run's whole process tree (before that every Windows run exited 127). `export` uses `jq` where it is installed and Python elsewhere. `lane-bench summary` lists every model and effort, with capability and usage side by side ([ours](findings/suite-r/by-arm.md)).

## Install, or update

```bash
./install.sh --dry-run && ./install.sh          # from a checkout
bash claude-usage-optimizer-bundle.sh --dry-run && bash claude-usage-optimizer-bundle.sh   # from the bundle
```

Re-running is safe. Once installed, restart any open Claude Code sessions so they load the new
settings. The installer adds these hooks to `~/.claude/settings.json`, each only once:

| Event | Command | What it does |
|---|---|---|
| `UserPromptSubmit`, `Stop` | `turn-meter hook` | Records each turn in `~/.local/state/lanes/turns.jsonl` (`USAGE_OPTIMIZER_TURNS=off` turns it off) |
| `PreCompact` (`auto`) | `turn-meter compact-gate` | Holds a mid-turn compaction until the next turn, below the 350k hard ceiling (`USAGE_OPTIMIZER_COMPACT_GATE=off`, `USAGE_OPTIMIZER_COMPACT_HARD`) |
| `SessionStart` (`compact`) | `turn-meter resume-context` | After a compaction, tells Claude which lane runs are in flight or awaiting review |
| `SessionStart` (`startup`, `resume`, `compact`) | `claude-statusline session-start` | Points the statusline's kit version at the installed release when a session restarts or compacts, since both reload the policy |
| `PostCompact` | `turn-meter hook` | Logs the compaction to `compactions.jsonl` (`turn-meter compactions` reports it) |
| `SubagentStop` (`^lane-`) | `lane hook subagent-stop` | Finishes the record of a `lane --subagent` run |

It also moves `autoCompactWindow` from the kit's old 450k default to 250k. A value you set yourself is left alone.

The installer reports each worker CLI's version but never starts `cline`: starting it, even
for `--version`, runs `npm update -g cline` in a new window, and updates from installs run close
together overwrite each other and break cline. Its version is read from npm's `package.json` instead.

On Windows, run both commands from Git Bash. The installer finds a working Python (the Microsoft
Store `python3` stub is skipped), keeps each Python tool at `~/.claude/usage-optimizer/bin/<tool>.py` behind bash
and `.cmd` wrappers in `~/.claude/usage-optimizer/bin` and `~/.local/bin`, and points the statusline at Python
explicitly. `lane` unwraps `.cmd` launchers so `cmd.exe` never re-parses a brief.

Machine-local configuration lives outside the optimizer, in `~/.config/lanes/`:
- `mask.local`: extra paths to hide from masked workers.
- `bin/`: lane-only executables. `lane` looks here before PATH, so luna and sol can use a current
  `codex` while an older research CLI stays first on PATH. Install creates the folder empty (mode 700)
  and never writes into it. The masked lane (glm) refuses a binary from this folder because
  `~/.config/lanes` is on the mask list. `usage-status` and the statusline read the Codex meter with
  the same binary: `USAGE_OPTIMIZER_CODEX_BIN` if set, else `codex` in that folder, else `codex` on
  PATH.

Reset times in the statusline and `usage-status` use the machine's time zone. A server kept on UTC
can show another zone instead: set `USAGE_OPTIMIZER_TZ` to an IANA name (e.g. `Australia/Brisbane`) in
the `env` block of that machine's `~/.claude/settings.json`.

**Codex meter.** `usage-status` makes a read-only `codex app-server` rate-limit request and caches
it in `CLAUDE_USAGE_DIR` (default `~/.claude/usage`); the statusline renders that cache and refreshes
it in the background. `USAGE_OPTIMIZER_CODEX_BIN` selects the Codex executable, `CODEX_HOME` selects
its state directory (default `~/.codex`), `USAGE_OPTIMIZER_CODEX_TIMEOUT` sets the live-read deadline
(default 30 seconds for background refreshes, 15 seconds for synchronous reads), and `USAGE_OPTIMIZER_CODEX_TTL` sets cache freshness (default 300 seconds,
minimum 60). Set `USAGE_OPTIMIZER_CODEX_LIVE=0` for rollout-only `usage-status`, or
`USAGE_OPTIMIZER_CODEX=off` to hide the statusline segment.
Set `NO_COLOR` (any value) or `USAGE_OPTIMIZER_COLOR=off` to disable statusline colors.

Rules for one particular machine go in `~/.claude/CLAUDE.md`, above the import line.

## Mobile view

The terminal reads like the Claude mobile app: your questions, the sentences Claude writes between
steps and its final answer are shown in full, while tool calls and their output fold away.

- Each tool call is one line: `● Bash  Swipe up, look for the wake prompt  ✗ exit 1`. Click a line
  to show the call and its output in place; click it again to fold it.
- Code blocks longer than 12 lines in Claude's replies fold to `▸ python · 30 lines hidden`; the
  `▸ show code` button under the reply opens them.
- Every question carries its number (`#3`). `.` typed into an empty prompt opens the list of them (the
  footer says so: `← for agents · . for questions`), with the keyboard in a filter box under the newest
  question. Type to filter (`12` or `#12` picks one by number), Enter jumps to the newest match, and Esc
  goes back to the prompt. ↑ walks up the questions with `❯` on the chosen one, Enter
  (or a click) jumps the transcript back to it, and ↓ past the newest returns to the box. In a list taller
  than the pane, ↑↓ still move `❯` and the list scrolls to keep it in view; the wheel and PgUp/PgDn scroll. A question
  from before a compaction is no longer in a reopened session's transcript, so Enter shows its text in
  the list instead (Enter again folds it). The `✕` in the list's corner and ctrl+x x also close it; if
  the list loses the keyboard (you clicked elsewhere), ctrl+x tab, a click or `.` gives it back.
- `.` opens the list over a dim suggested prompt too (Tab or → still takes the suggestion). Claude Code
  places a pane opened by a key alone on a terminal 144 columns wide, or 110 once you have opened the
  list yourself. So on a narrower terminal the first `.` is typed and says to press Enter, which opens
  the list; after that `.` alone works, in later sessions too (narrower than 110, Enter is needed each time).
  To start a message with `.`, type a space first. `.` typed anywhere else in a message is just a dot.
- Ctrl+O still shows the full transcript. `/mobile-view off` returns to Claude Code's own rendering
  (remembered across sessions); `/mobile-view on` brings the mobile view back.
- The phone view through Remote Control is unchanged; the mod only draws the terminal.

The installer sets these keys in `~/.claude/settings.json` (it backs the file up first and prints
each change): `verbose: false` (verbose prints every command and its output), `viewMode: "default"`
(not the focus view, which hides the text between tool calls), `tui: "fullscreen"` (needed for
clickable rows and the side list) and `outputStyle: "Mobile"`. A key you change by hand afterwards is
kept on later runs; `install.sh --reset-view` sets them again, and `install.sh --no-view` leaves the
whole mobile view alone. Two plugin options tune the mod: `codeLines` (fold code blocks longer than
this, default 12) and `maxGroupLines` (tool rows listed per batch before `… +N more`, default 8); they
appear in the `/config` menu and are stored under `pluginConfigs` in settings.

To remove it: `claude plugin disable mobile-view@skills-dir`, or delete `~/.claude/skills/mobile-view/`
and `~/.claude/output-styles/Mobile.md`, then change the view keys back in `~/.claude/settings.json`
(the installer's backup in `~/.claude/backups/usage-optimizer-<time>/settings.json` has the old values)
and run future installs with `--no-view`.

Developing the mod: `claude plugin validate --strict mods/mobile-view` and `claude plugin test mods/mobile-view`.
The Python tests run with `PYTHONUTF8=1 python -m unittest discover tests` (UTF-8 mode is needed on Windows).

## Publishing a new version

1. Refresh the knowledge pack on the VPS first (above) and review its diff. Bump the version line in
   `POLICY.md`; bump `catalog_version` only when the catalog changes.
2. Run the tests, confirm `lane-stats arms` loads, then run `tools/make-bundle.sh`,
   `python3 -I tools/make-page.py` and `python3 -I tools/check-release.py`. Preview with
   `bash install.sh --dry-run`.
3. When publishing from a machine other than the last publisher, compare the live bundle with the source
   using `python3 -I tools/diff-bundle.py <live bundle> [--kit DIR] [--extract DIR]` and merge differences
   before publishing.
4. Publish the `.sh` bundle as `contentType: "text/plain"` to the same Artifact URL.
5. On every other machine, re-run the setup prompt. See [IMPROVING.md](IMPROVING.md) for the full release,
   research and lessons process.
