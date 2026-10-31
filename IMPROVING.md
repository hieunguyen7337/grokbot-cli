# Improving the kit

## 1. The rule

Every lesson learned from using the kit goes into the kit and is published in the next release. The kit keeps
the statistics and main findings, plus the methods, tools, templates and general lessons needed to build on
them. It also keeps the resources to test new models, research and methods as they appear; those change every
week. This is how the kit improves itself over time.

## 2. What the kit keeps

Keep aggregated statistics, main findings, methods, tools, templates and lessons that help any machine using
the kit. Never ship Suite R items or another suite's item code, reviewer finding text, raw transcripts or
session extracts, per-run ledgers, personal data, project or paper names, hostnames, user ids or home paths.
Rewrite a useful machine lesson in general terms, such as “a high-performance computing (HPC) login node”
or “a research project”. A fact that is true only on one machine belongs in that machine's
`~/.claude/CLAUDE.md`.

**The full lab archive.** What the kit leaves out is kept in the owner's private GitHub repository `usage-lab`
(about 820 MB in 40,000 files): Suite R's items and answer keys, every run's raw output, the rescoring and
verification work, the meter probes, the briefs, the lane state and the memory notes behind the findings. The
kit's source, with its full commit history, is the private repository `claude-usage-optimizer`. With `gh` logged
in as the owner, `gh repo clone usage-lab` and `gh repo clone claude-usage-optimizer` fetch them. Clone the
archive only to continue evaluation work on that data, such as rerunning or rescoring Suite R; to take one part,
clone with `-- --filter=blob:none --sparse` and `git sparse-checkout set <folder>`. Its `README.md` maps the
folders. Whatever comes from it stays out of the kit.

On Windows, add `-c core.autocrlf=false` to the clone: the archive pins no line endings, and Git for Windows
otherwise checks every file out with CRLF (a patterns file with CRLF matches nothing). Git Bash also rewrites an
argument that starts with `/` into a Windows path, so `sparse-checkout set /README.md /memory/` stores
`C:/Program Files/Git/README.md` and the checkout comes out empty: prefix it with `MSYS_NO_PATHCONV=1` and check
with `git sparse-checkout list`.

To refresh the archive, stage it outside the lab with hard links (`cp -al` copies nothing), leave out build
clones whose commits are already in the source repository, commit where heavy CPU is allowed (on a shared login
node, in a batch job), and push. Before every push, scan for credentials in one combined pass
(`grep -rIlE -f <patterns>`) and attribute the hits afterwards: one pass per pattern over 820 MB took more than
15 minutes. Anchor short prefixes such as `sk-` as `(^|[^A-Za-z0-9_-])sk-`, or they match inside words like
`task-…`. Run `git status --ignored` to see what a copied `.gitignore` drops. The archive's `machine/tools/`
holds the staging and scan scripts. A document connector such as Google Drive can't carry an archive, because
its uploads pass through the conversation as inline text.

## 3. Where a lesson goes

| Lesson type | Home |
|---|---|
| Routing rule | `POLICY.md` |
| Lane quirk or orchestration lesson | `LANES.md` |
| Meter fact | `measure/*.md` |
| Measured result | `findings/FINDINGS.md` and a matching `findings/<topic>/` data directory |
| Method | `measure/*.md` or `findings/public-research/` |
| Tool or its behavior | `bin/` and `tests/` |
| Domain knowledge | `skills/`, the knowledge pack; see README “Knowledge pack” |
| Machine-only fact | That machine's `~/.claude/CLAUDE.md` |

A lesson about mirror cloud sessions goes to the "Main cloud sessions" section of `POLICY.md` when it changes what the
main session does, and to LANES.md "Mirrors, side sessions and `lane main`" when it is a quirk or a limit. The policy
section is copied into the session's prompt by `lane main`, so keep it short and ASCII: any other character stops the
command (exit 8).

## 4. Sweep for lessons

Run a lessons sweep after a substantial task, with the weekly `lane-stats recommend`, and before every release
on every machine. Use `improve/audit-brief.md` as a read-only `research` lane unit over memory notes, machine
rules and lab notes. Give it the lane class `research` and a descriptive tag. Search only named directories and
depths from the brief. Classify each candidate as KIT-MISSING, KIT-PARTIAL, PRESENT, EXCLUDED, MACHINE,
PROJECT, SUPERSEDED or OBSOLETE. Cite every claim with `[OBSERVED path:line]` or `[INFERRED]`; report absent
targets and count every class. Each kit-wide lesson ships in the next release.

With the weekly sweep, run `turn-meter census --json` on every machine and add the results up. Work that never
went through `lane` (interactive Codex or Claude sessions, other tools) still draws on the meters, and the census is
the only kit view of it: a heavy model used by hand (astra, 18.9 h in the week to 2026-10-30) or a pattern a lane
could take over shows up there first.

## 5. New models

Follow Explore steps 6 and 9 in `POLICY.md` in order. First run `lane-stats arms --discover`, then add the new
model's arms with its predecessor's classes. Forced exploration gives each arm real units. After the user
approves a capability test, rerun the kit's suite with `lane-bench`, then write measured priors with
`lane-bench priors`. Retire the predecessor only when `lane-stats recommend` shows the new arm is at least as
good in every class it serves. Keep the exploration floor so later changes can still be found.

## 6. New public research

Read both `findings/public.json` and `findings/public-research/` when updating public evidence. Each numeric
row in `public.json` records `lane`, `model`, `effort`, `metric`, `value`, `source`, `date` and `url`. The dated
research notes group results by task and benchmark; their tables record the benchmark and version, date,
model, effort, score, cost when reported, who ran it and a source link. They also record conflicts, gaps and
unverified results. Preserve those distinctions when adding evidence.

Compare public evidence with our reviewed results using `lane-bench compare`. In the current comparison,
public benchmark prices rank our review cost well (Spearman rank correlation, a measure of ranking agreement,
0.96 for v1.5 and 0.98 for v2.0), while public scores rank our recall only by tier: the v1.5 index 0.22 (18 arms),
the per-effort Intelligence Index v5.0 0.57 (37 arms), the v2.0 index 0.81 on nine max arms, mostly because luna and
terra sit below the rest (`lane-bench compare --outcomes findings/suite-r/outcomes.jsonl`, 2026-10-31; it writes its
tables to `findings/suite-r/results/`, so delete that folder unless the tables are meant to change). Trust public
prices as a starting point, not public scores as a substitute for our own measured quality.

## 7. New methods and suites

Use `measure/SUITE.md` to define a suite and `measure/ADJUDICATE.md` to resolve findings. Regrade with
`lane-bench rescore` and refresh measured priors with `lane-bench priors --score v2`. When Codex is at its
weekly ceiling, `lane-bench run --codex-at-limit wait` forces a live reading and waits instead of skipping;
`--codex-wait-max-h` bounds that wait.

Suspect the harness before the model. If an arm returns all zeros, a suspiciously round rate or an implausibly
low number, inspect raw model output first. A 2026-09-15/16 pilot found 16 harness defects; seven produced
believable numbers rather than obvious failures. Examples included a parser that recognized one code-fence
form and scored valid code as 0.0, a field that was `None` by construction but averaged as 0.0 beside 41
solved tasks, and a smoke gate that reused an id and graded the previous build.

The harness includes your own scripts. On Windows, Python writes CRLF to a redirected stdout, so a shell loop over
its output keeps a trailing `\r` on every line: all 73 lane-bench tests then "errored" as unknown names
(2026-10-23). Strip `\r` before looping.

Run each arm's assembled command end to end on a synthetic fixture before using real data. Unit tests alone
missed two first-run failures on 2026-09-04.

The next measurements already proposed in `findings/FINDINGS.md` §§9–10 are a multi-task suite and lead ×
executor pairs measured by role. The single-task suite does not settle performance on other task types, and
hybrid roles need their own evidence.

## 8. Building a release

1. Bump the version line in `POLICY.md`. Bump `catalog_version` in `arms.json` only when the catalog changes.
2. Run the tests and confirm `lane-stats arms` loads the catalog, in the cloud (from 2026-10-31.6): commit the
   candidate, `git worktree add` a clean copy (`lane` refuses untracked files), and run
   `lane haiku --cloud --verify -e low -C <copy> -b <brief>` with a brief listing the full suite (900 s) and
   `python3 bin/lane-stats arms`. To test a `lane` that is not installed yet, start the checkout's own copy as
   `python <checkout>/bin/lane …`: Git Bash on Windows has no `python3`, so its `#!` line fails. Since 2026-10-28
   every test passes on Windows too (§10), and `test_bench` runs whole in under a minute; on Windows run only the
   modules a Windows-only change touches, each with a timeout. `test_install_view` passes
   but runs the installer many times through Git Bash: its 11 tests took 14 minutes on a busy Windows machine, so
   give it a 20-minute timeout rather than read a cut-off run as a hang.
3. Build the bundle with `bash tools/make-bundle.sh`, then the page with `python3 -I tools/make-page.py`. In a
   fresh clone, pass `--url <artifact url>` once: `dist/.artifact-url` is not tracked, and without it the page
   keeps a URL placeholder instead of the link. Check that `grep -c <artifact id> dist/index.html` is above 0.
4. Run `python3 -I tools/check-release.py [--kit DIR] [--bundle PATH] [--page PATH] [--patterns FILE] [--max-bytes N]`.
   It checks `version`, `catalog`, `json`, `bundle` size (at most 16,000,000 bytes), `fresh` (bundle matches
   the tree), `patterns`, `eol` and `untracked`; exit 0 means clean and exit 1 means at least one FAIL.
   `untracked` fails on a shipped file that git does not track, because `make-bundle.sh` ships untracked,
   non-ignored files. Release 2026-10-29.3 was first built with a Codex CLI `error.log` holding an account id,
   which a warning let through; `.gitignore` now ignores `error.log`.
   `eol` fails on a file git stores with LF whose working copy has CRLF. Editors on Windows save CRLF, and
   `.gitattributes` normalises it on commit, so `git diff` shows nothing; but the bundle carries working-tree
   bytes, and `fresh` compares the bundle with that same tree. Release 2026-10-24.1 first shipped two Python
   files with CRLF this way and was rebuilt from a clean `git worktree add --detach <dir> <commit>`. Convert
   such files to LF; if `git status` still lists them with no diff, `git add` them. Patterns are
   regexes for project names, hosts and home paths in a local, never-shipped file, defaulting to
   `~/.config/lanes/release-patterns.local`. A `!glob` line excludes paths. A hit prints only
   `path:line pattern#N`. The current bundle is 13.9 MB, leaving about 2.1 MB of headroom.
5. Preview installation with `bash install.sh --dry-run` and run `improve/release-brief.md` before publishing.

Build workers write JSON only through the tool's own output or `--write`; never rewrite it with `jq` or a
heredoc. Check `[.. | objects | select(has("measured") and .measured==null)] | length` is 0. Recompute
before/after tables from `git show HEAD:` because a worker's table can repeat the new value on both sides.

`tools/make-bundle.sh` includes untracked, non-ignored files. Keep scratch workspaces git-ignored and install
from the clone that built the bundle. If a commit is requested, use the neutral identity `kit <kit@localhost>`,
never a personal address.

## 9. Publishing from any machine

Before publishing from a machine other than the last publisher, compare the live bundle with that machine's
source and merge differences first:

```bash
python3 -I tools/diff-bundle.py <live bundle> [--kit DIR] [--extract DIR]
```

This comparison never runs the bundle: exit 0 means identical, 1 means differences and 2 means an error.

**Taking over on another machine.** That machine's old kit folder may be a bundle extract or a checkout of an
older release; never build or publish from it, or the release reverts every later one. Find its release's commit
(`git log --oneline -S'version: <its version>' -- POLICY.md`), compare the folder with it (`git archive <commit>`
into a scratch folder, then `diff -rq --strip-trailing-cr`), port anything newer onto a fresh clone as commits,
and only then put the clone in its place. On Windows the folder that is a running session's working directory
cannot be renamed (`Device or resource busy`): move its contents aside, then move the clone's contents, `.git`
included, into it. `.gitattributes` pins LF, so a Windows clone matches the bundle byte for byte. `python3` may
be the Microsoft Store stub, which cannot run; use the Python that `install.sh --dry-run` reports.
Publish the `.sh` bundle as `contentType: "text/plain"` to the same Artifact URL. The publish refuses any file
that contains U+FFFD (the replacement character), so write such characters in source as escapes (`"\ufffd"`):
release 2026-10-28.1 was refused once for a literal one in `bin/lane`'s garbled-text pattern, and 2026-10-29.1
once for one in this very note. Claude's Edit and Write tools decode a backslash-u escape in their input, so the
escape typed into a tool call lands on disk as the character itself; write it with a script, or check the bytes.
`tools/check-release.py` fails (`replacement`) on U+FFFD in the page or any shipped file. On other machines, rerun
the setup prompt. Pool reviewed runs with `lane-stats export` and `lane-stats import`; the per-run ledger never
ships.

## 10. Backlog

- **Lane recipes, planned and not built:** `lane recipe <id>` should read roles, protocol and limits from
  `arms.json`, run the roles as stages, record one run and cost per role, and sample by class. The hybrid
  stage needs this.
- **Review cost attribution, planned and not built:** attribute review cost to the unit that caused it, by
  tag, so the picker charges a cheap lane for the Opus review that it causes.
- **Multi-task suite:** measure more task types with task-specific checks and effort curves, as proposed in
  `findings/FINDINGS.md` §9.
- **Lead × executor pairs:** measure each role's contribution on a connected set of pairs and check the fit
  on held-out pairs, as proposed in `findings/FINDINGS.md` §10.
- **Windows portability, found 2026-10-23, closed 2026-10-28.** Fixed 2026-10-24: `test_lane`'s four (cgroup
  paths strip `/` on every system; cleanup clears read-only `.git` objects) and `test_release_tools`' six (Git
  Bash through `find_bash()`, `sys.executable`, the bundle edited as bytes, no mode bits). Fixed 2026-10-28:
  `lane-bench`'s 17 (helpers start through their `.cmd` wrapper, Python or Git Bash; runs stop by process tree;
  `export` reads the graded summary in Python without `jq`) and one each in `test_knowledge` and `test_measure`
  (paths print with `/` on every system). Found and fixed 2026-10-29: on a Windows install each tool is
  `bin/<tool>.py` behind a bash wrapper `bin/<tool>`, so a tool that starts a sibling with
  `python bin/<sibling>` runs the wrapper and gets a SyntaxError. `lane-stats pick` did this with `usage-status`,
  failed silently, and so never applied pace factors or the at-limit skips on Windows. A tool that starts a sibling
  takes `<sibling>.py` when it exists, as `lane` already did.
- **Time as a value to optimise.** Since 2026-10-29 every run and turn logs its time and ETA, but the picker
  chooses on usable rate and cost only. Once `eta×` shows the estimates are sound, consider a time term (for
  example Claude's waiting minutes priced in points) for units on a deadline.
- **Cloud runs, still open** (built in 2026-10-29.3: `lane <claude lane> --cloud`, `lane codex-cloud`, `bin/lane-term`;
  LANES.md "Cloud runs"; research note §7–§8). Measure, as cloud runs accumulate: a cloud run's meter weight against
  the same arm run locally (the same model and effort, so `lane-stats report` by `place` once the ledger field
  has data); the start-up on a cold VM and with a setup script; how many Claude cloud sessions run at once before
  a launch is refused; and the time from the worker's done push to the applied diff. `codex-cloud` first ran end to end
  on 2026-10-31: that run checked the task-URL parsing, the status polling and the diff apply, and all three worked
  (LANES.md, "Codex"). Still open: what `codex cloud status` prints for a failed task, which that run did not show;
  until then its arm stays manual.
  Add a time term to the picker only after cloud runs show whether placement changes usable rate (Linux harness,
  4 vCPU) as well as time. If a repository cannot use the Claude GitHub App, the only other return path is the
  session's event log, which only an in-process Claude Code tool can read; reading it with the user's OAuth
  token from a script is not an option (the kit never reads credentials).
- **Subagent runs, still open** (built in 2026-10-29.3: `lane --subagent`, `lane hook subagent-stop`, the
  `lane-<lane>-<effort>` agents; LANES.md "Subagent runs"). Measure, on the first real runs:
  - how much the main Claude Code process grows while subagents run, against the 0.5–1.2 GB a `claude -p` worker
    peaked at (two runs);
  - whether every run's transcript shows the arm's effort (the hook warns when it doesn't);
  - whether the usable rate of an arm differs between `place` subagent and local (the subagent sees the session's
    hooks and permissions but not its CLAUDE.md);
  - how many background subagents run at once before Claude Code queues or refuses one;
  - what the agent list costs: the 12 definitions sit in every session's tool description.

  If subagents hold up, make `--subagent` what `lane-stats pick` prints for Claude arms when it is called from a
  Claude Code session.
- **Memory needs per class.** `peak_mem_mb` is recorded per run from 2026-10-29.2 and the need is taken per lane.
  A unit that builds or installs (npm, a large test suite) peaks far above one that edits text; once enough runs
  carry the field, check whether lane x class predicts the peak better than lane alone, as the ETA's tiers do.
- **lane-bench cost in plan dollars, open.** `lane-bench` still prices cost points with provider scarcity weights
  (`bin/lane-bench`: the pooled cost points and the per-item points; `tests/test_bench.py` sets scarcity values),
  as `lane-stats` did before its plan-dollar change. Move it to plan dollars: the window share through
  `window_epochs` and `plan_scale`, times the plan's price per week (`arms.json` `explore.points_basis`). Until then
  its cost axis mixes scarcity with prices, so its cost-per-recall ranking is not in plan dollars.
- **Mirror cloud sessions, to pilot** (built in 2026-10-31.15: `lane main`, `lane-stats main-picks`, `lane-stats
  import-orch`; LANES.md "Mirrors, side sessions and `lane main`"). Run one mirror on one project for a few days and
  record in `findings/` what it cost (list dollars and the share of Claude's week, against the same units as local
  subagents), how good its reviews were (how often its Haiku second reader's objection held, how often the local
  session found a defect the mirror had accepted) and how long units took. Imported runs carry `place: "cloud-main"`,
  so a report by place shows them apart from local runs.
- **Route 1(a), still untested.** Try once, from a running mirror, to clone the private kit repository. The session's
  own scope text says it cannot, but nobody has tried. If it can, install the kit in the VM so the mirror runs
  `lane-stats pick` itself, with its own copy of the pooled runs (`lane-stats export` and `import`), instead of reading
  `picks.json`. This is a picker in the VM, not the per-pick round trip that design (i) means in LANES.md.
- **Hand-off time in the markers.** Once enough Codex and gemini hand-offs exist, extend the REVIEW markers with the
  hand-off's own time (the wait for the local run, apart from the mirror's review), so a hand-off unit's ETA is
  measured, not guessed.

## 11. Release lessons

**2026-10-31.16.**
- *A test kit must match the installed layout, not the checkout's.* `lane main` ran `python bin/lane-stats`, which on
  a Windows install is a bash wrapper beside the real `lane-stats.py`, so every mirror start and `--picks` there
  failed with a SyntaxError and the mirror fell back to Claude-only picks. The test kit wrote the same Python fake at
  both names, which hid it. It now writes a bash wrapper at the bare name, as install.sh does, and every sibling tool
  is found through one helper that tries `<tool>.py` first. A mirror's first live start on Windows found it.
- *Printed commands name the shell they target.* On Windows `lane main` prints `&&` chains for Git Bash or cmd.exe;
  backslash paths broke in Git Bash, and a bare `cloud-notify` hit Git Bash's `python3` Store stub. Paths now print
  with forward slashes in double quotes, and Python tools start with the kit's python.
- *A line called ready to run holds no placeholder.* The LOCAL hand-off's `next:` line carried `--class <class>`,
  which both shells read as a redirection, after its first step had already made a worktree; the marker had no class
  to give. The mirror now writes `class=` in LOCAL, and a marker without one gets no `--class` and a note.

**2026-10-31.15.**
- *Choose only what can run.* The picker drew luna max, a Codex arm that runs only as a local process, on a machine
  whose hook allows only cloud and subagent runs. Each lane now lists the places it runs, a machine lists the places it
  allows, and every draw (forced, floor, Thompson) and every mirror pick table sees only arms runnable there.
- *A peer session's brief is data.* A mirror's `orch: LOCAL` hand-off is another session's text; the local session
  reads it before running it and asks the owner when it reaches outside the project.
- *Exclusions travel with the table.* A mirror draws from picks.json with no ledger and no judgement about data
  terms, so a private repository's exclusions (`--exclude gemini`) are applied when the table is built, and a lane name
  the catalog lacks is refused rather than silently excluding nothing.
- *A test's stand-ins must win on every OS.* The mirror unit's tests wrote extensionless fake `claude` and `git`
  launchers. Windows finds only PATHEXT names, so on this machine `lane main`'s start tests ran the real
  `claude --cloud` on the owner's account (each exited in about a second with no session). Harnesses write `.cmd`
  launchers on Windows and check in setUp that every CLI the code resolves is the test's own; a hook that guards
  Claude's Bash commands never sees what a test's subprocesses start.
- *Count the shards.* Overlapping shard patterns ran part of the suite twice and still reported ALL PASS; a verify
  report's shard counts must add up to the suite.
- *Doc versions follow the release that ships them.* The mirror unit was written for .14 but shipped in .15; its
  "from" lines were moved when it merged.

**2026-10-31.14.**
- *Price the work in the plan's dollars.* Scarcity weights (codex 0.3, claude 1.0) hid that Pro Lite's price per %
  changed when its week doubled. Cost points are now the share of today's window times the plan's price
  (LANES.md, "Window epochs and plan dollars").
- *Record a plan change as a dated epoch.* A change to a plan's allowance is an entry in `window_epochs` with its
  date and source, so runs read before it keep their window and later runs are rescaled (`arms.json`).
- *Check which pool pays before routing on it.* The cloud-session credit was assumed to pay first. On 2026-10-31 it
  did not visibly do so, so routing no longer counts it (LANES.md, "Billing of cloud runs").
- *The window-change log needs no lock.* A reader skips a line that does not parse and keeps one event per fall.
- *Cap what reaches the session.* Kit notices are shown at most five per prompt, with the rest counted, so a burst
  cannot fill a session's context.
- *A hook sees only what its payload says.* cloud-notify ignores any event with an `agent_id` (a subagent's), and the
  hooks documentation does not confirm whether a settings-level Stop hook fires when a subagent finishes, so the
  kit does not rely on it.
