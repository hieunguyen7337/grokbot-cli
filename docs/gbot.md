# gbot command reference

Windows CLI for existing Grok Bot bots (alpha, unofficial). See the
[README](../README.md) for installation, sign-in, safety and exit codes.

## Global invocation

```text
gbot [-h] [--version] [--debug] COMMAND ...
```

`-h` / `--help` prints help; every command also accepts it. `--version` prints
the CLI version. `--debug` re-raises errors for debugging; place global options
before the command. Debug output can include diagnostic details: review before sharing.

Bot selectors accept an exact ID, exact name, then a case-insensitive name.
Ambiguous names fail; use an ID. Commands needing a bot fail if none is selected.
Quote multiword names and prompts. Prompt words are joined with spaces.

REF is a full pending transcript entry ID or an unambiguous prefix of at least
six characters. Obtain it from approvals. Answer commands re-fetch pending items,
show the target and planned answer, and require confirmation; noninteractive use
requires `--yes`. With `--json`, the preview goes to stderr and stdout has
`answered`, `bot_id`, `bot_name`, `entry_id`, `type`, `rpc`, and `effect`.
Payment, publishing, account linking, authentication/checkout forms, card forms,
spend-guard widgets, and meeting-join requests must be handled in the app. Read allowed_actions in pending
JSON to determine which CLI answers are supported.

For commands offering `--json`, that option replaces normal output with JSON.
Errors are one JSON line on stderr with `error.type`, `error.message`, and
`error.exit_code`. Types are `auth`, `still_working`, `timeout`, `network`,
`gateway`, `invalid`, and `error`. Login and following tail have the distinct
multi-record formats described below. Exit codes still apply in JSON mode.

Exit codes: 0 OK; 1 error; 2 needs attention; 3 not signed in or auth failed;
4 still working after ask; 130 interrupted. A broken pipe exits 0 quietly.

## approvals

List pending requests.

```text
usage: gbot approvals [-h] [--bot BOT | --all] [--json]

options:
  -h, --help  show this help message and exit
  --bot BOT
  --all
  --json
```

Example: `gbot approvals --all`.

`--bot BOT` selects one bot; `--all` scans waiting bots across the roster. These are mutually exclusive. Without either, use the selected bot, or waiting bots if no default exists.

`--json`: Array of pending items: bot_id, bot_name, entry_id, session_id, type, summary, created_at, allowed_actions, request_id, tool_text, draft, options and fields. Returns 2 when nonempty.

Email and Slack draft cards can be approved to send the unchanged draft, or denied to discard it.
Meeting-chat drafts are deny-only. The signature shown in the app is not added by gbot.

## approve

Approve a review, meeting consent or local tool request.

```text
usage: gbot approve [-h] [--yes] [--json] [--always] REF

positional arguments:
  REF

options:
  -h, --help  show this help message and exit
  --yes
  --json
  --always
```

Example: `gbot approve REF`.

`--always` sends a persistent approval resolution instead of a one-time approval. `--yes` skips confirmation.

## deny

Deny a review, meeting consent or local tool request.

```text
usage: gbot deny [-h] [--yes] [--json] [--never] REF

positional arguments:
  REF

options:
  -h, --help  show this help message and exit
  --yes
  --json
  --never
```

Example: `gbot deny REF`.

`--never` persistently denies only local tool permissions. `--yes` skips confirmation.

## respond

Answer a widget or ordinary user form.

```text
usage: gbot respond [-h] [--yes] [--json] [--field NAME=VALUE] REF [VALUE]

positional arguments:
  REF
  VALUE

options:
  -h, --help          show this help message and exit
  --yes
  --json
  --field NAME=VALUE
```

Example: `gbot respond REF --field city=Brisbane`.

Supply VALUE for a widget, or repeat `--field NAME=VALUE` for a form; do not mix them. Widget values must match `options` unless custom or multi-select is allowed. Use IDs from `fields` for forms. Field names must be unique. Forms are submitted with vault saving disabled. `--yes` skips confirmation. Avoid sensitive values in shell history.

## dismiss

Dismiss a widget or ordinary user form.

```text
usage: gbot dismiss [-h] [--yes] [--json] REF

positional arguments:
  REF

options:
  -h, --help  show this help message and exit
  --yes
  --json
```

Example: `gbot dismiss REF`.

`--yes` skips confirmation. Form dismissal sends mode dismissed.

## secret

Supply an eligible requested secret through hidden input.

```text
usage: gbot secret [-h] [--yes] [--json] REF

positional arguments:
  REF

options:
  -h, --help  show this help message and exit
  --yes
  --json
```

Example: `gbot secret REF`.

No secret positional argument is accepted. Hidden input must be available; echoed fallback is rejected. `--yes` skips confirmation but still requires hidden input. Account credentials must be handled in the app.

## ask

Send a prompt and wait for the bot reply.

```text
usage: gbot ask [-h] [--bot BOT] [--timeout TIMEOUT] [--idle IDLE] [--stream]
                [--json]
                text [text ...]

positional arguments:
  text

options:
  -h, --help         show this help message and exit
  --bot BOT
  --timeout TIMEOUT
  --idle IDLE
  --stream
  --json
```

Example: `gbot ask --bot "Research" "Summarize tomorrow"`.

`--bot BOT` overrides the default. `--timeout TIMEOUT` is the overall timeout in seconds (600 default); `--idle IDLE` is the idle timeout in seconds (45 default). `--stream` prints reply chunks as they arrive.

Use `gbot ask -` to read the prompt from stdin.

`--json`: Object with bot (id, name) and reply; when input is needed, also pending and exit 2. Streaming JSON produces a final object rather than chunks.

## bots

List existing bots without creating one.

```text
usage: gbot bots [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json
```

Example: `gbot bots --json`.

`--json`: Array of id, name, state and default; state is composing, running or idle.

## connectors

Inspect existing computer connectors without modifying them.

```text
usage: gbot connectors [-h] [--tools] [--json]

options:
  -h, --help  show this help message and exit
  --tools
  --json
```

Example: `gbot connectors --tools`.

`--tools` also fetches tool names per server. A tool-list error is reported per server; listing does not perform sign-in.

`--json`: Object with `connectors`, `plugins_without_connector`, and `warnings`. Connector rows include `name`, `server_identifier`, `account`, `status`, `auth`, `tool_count`, `plugin`, `served_by`, `sources`, `kind`, and `usable`. Kind is plugin, cursor, team, or custom. Requested tools and per-server errors may also appear.

## doctor

Check local configuration, gateway access and protocol compatibility.

```text
usage: gbot doctor [-h] [--offline] [--json]

options:
  -h, --help  show this help message and exit
  --offline
  --json
```

Example: `gbot doctor --offline`.

`--offline` skips gateway, default-bot and host checks, but still reads local sign-in state and inspects the app. GBOT_APP_DIR selects the app directory. Drift checks only names and argument kinds, not fields or replies.

`--json`: Array of check, status and detail. Authentication failure returns 3; other failed checks 1; warnings 2; otherwise 0.

## login

Sign in and save the session locally.

```text
usage: gbot login [-h] [--no-browser] [--timeout TIMEOUT] [--json]

options:
  -h, --help         show this help message and exit
  --no-browser
  --timeout TIMEOUT
  --json
```

Example: `gbot login --no-browser`.

`--no-browser` prints the sign-in URL without opening it; open it yourself. `--timeout TIMEOUT` sets seconds to wait (300 default).

`--json`: Two separate JSON objects: login_url first, then signed_in on success. This is not one JSON document. Tokens are never output.

## logout

Remove the locally saved session.

```text
usage: gbot logout [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json
```

Example: `gbot logout`.

`--json`: Object with removed (boolean). This does not promise remote token revocation.

## send

Submit a prompt without waiting for a reply.

```text
usage: gbot send [-h] [--bot BOT] [--json] text [text ...]

positional arguments:
  text

options:
  -h, --help  show this help message and exit
  --bot BOT
  --json
```

Example: `gbot send --bot "Research" "Prepare a summary"`.

`--bot BOT` overrides the selected bot. Use tail or ask to inspect subsequent activity.

`--json`: Object with `accepted`, `bot` (id, name), and `last_seq`, the highest sequence before sending, or null if none. It is not the eventual reply.

## status

Show sign-in, selected bot and desktop computer status.

```text
usage: gbot status [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json
```

Example: `gbot status --json`.

`--json`: Object with signed_in, client_version and default_bot. When signed in with a selected bot, also bot, host, secrets (application status only) and mcp server summaries. Returns 3 if not signed in.

## tail

Read recent transcript entries, optionally following new events.

```text
usage: gbot tail [-h] [--bot BOT] [-n N] [--since SINCE] [--after AFTER] [--full] [--json]
                 [--follow]

options:
  -h, --help     show this help message and exit
  --bot BOT
  -n N
  --since SINCE
  --after AFTER
  --full
  --json
  --follow
```

Example: `gbot tail -n 10 --follow`.

`--bot BOT` selects a bot. `-n N` limits initial entries (20 default; 0 prints none). `--since SINCE` starts after an entry ID in the fetched tail, not a date; missing IDs error. `--after SEQ` keeps entries with sequence greater than SEQ, including with `-n` and `--follow`. `--full` avoids the 160-character text truncation. `--follow` uses SSE and reconnects after transient failures; Ctrl+C exits 0.

`--json`: Array of raw entries normally; with follow, one compact entry per line (JSON Lines), including the initial selected entries. Entries include `seq`, `id`, `kind`, `timestampMs`, and `message`; `message` kind is user and `send-message` is bot. Full affects text rendering only.

## use

Save the default bot selection locally.

```text
usage: gbot use [-h] [--clear] [--json] [bot]

positional arguments:
  bot

options:
  -h, --help  show this help message and exit
  --clear
  --json
```

Example: `gbot use "Research"`.

BOT may be an ID or name. With no argument, validate and retain the current default. `--clear` removes the selection and cannot be combined with a bot.

`--json`: Object with default_bot (id and name), or null when cleared.


Answers to pending cards go to the Cursor backend's `aiserver.v1.GrokBotService`, using the same path as the desktop app.
