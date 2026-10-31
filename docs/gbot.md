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

## bot

Create, edit, delete and configure bots. BOT accepts a name or ID.

```text
gbot bot new NAME
gbot bot edit BOT
gbot bot delete BOT [BOT...]
gbot bot hide BOT
gbot bot show BOT
gbot bot notify BOT on|off
gbot bot drafting BOT on|off
gbot bot main [BOT]
gbot bot info BOT
```

See [bot management](tui/bots.md#cli-options-and-results) for action options,
confirmation, JSON results, avatar input and instruction files. Mutations need
confirmation; deletion removes conversation history and protects the current main
bot. Drafting off disables drafting. Main without BOT reads the server pointer;
info displays identity, ownership, sidebar settings, drafting, voice and main state.

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

Approve a review, local tool request, connector grant or message draft.

```text
usage: gbot approve [-h] [--yes] [--json] [--always] [--all-bots] REF

positional arguments:
  REF

options:
  -h, --help  show this help message and exit
  --yes
  --json
  --always
  --all-bots  connector grant: always allow for all team bots
```

Example: `gbot approve REF`.

`--always` sends a persistent approval resolution instead of a one-time approval. `--yes` skips confirmation.
For connector grants, `--always` remembers permission for this bot; add `--all-bots`
to remember permission for all team bots. `--all-bots` requires `--always` and a
connector grant. Use `gbot deny REF` to skip a connector grant.

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
                [--json] [--attach PATH]
                [text ...]

positional arguments:
  text

options:
  -h, --help         show this help message and exit
  --bot BOT
  --timeout TIMEOUT
  --idle IDLE
  --stream
  --json
  --attach PATH
```

Example: `gbot ask --bot "Research" "Summarize tomorrow"`.

`--bot BOT` overrides the default. `--timeout TIMEOUT` is the overall timeout in seconds (600 default); `--idle IDLE` is the idle timeout in seconds (45 default). `--stream` prints reply chunks as they arrive.

Use `gbot ask -` to read the prompt from stdin.

`--json`: Object with bot (id, name) and reply; when input is needed, also pending and exit 2. Streaming JSON produces a final object rather than chunks.

Repeat `--attach PATH` to upload local files before asking; text may be omitted when
files are attached. JSON adds `attachments` with each file's `name` and committed `path`.
Upload errors exit 1 without sending a prompt. Upload progress appears only on terminal stderr.

## bots

List existing bots without creating one.

```text
usage: gbot bots [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json
```

Example: `gbot bots --json`.

`--json`: Array of id, name, state and default; state is awaiting, composing, running or idle (in that priority order).
`awaiting` means the bot needs a user response.

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

## interrupt

`gbot interrupt [--bot NAME] [--session ID] [--yes] [--json]` stops an active run. Confirmation is required; use `--yes` for non-interactive use. The result indicates whether a run was active.

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

## save

```text
gbot save --bot NAME [--session ID] [--out DIR] [--json] REF
```

Save every file on an entry by its id or a unique prefix of at least six characters.
The output folder defaults to ~/Downloads and is created as needed. Existing names
get a numbered suffix. Remote HTTP(S) files print as `link: <url>` and are never fetched.
An entry without files exits 1. JSON returns `saved` paths and `links` URLs.

## send

Submit a prompt without waiting for a reply.

```text
usage: gbot send [-h] [--bot BOT] [--session ID] [--json] [--attach PATH] [text ...]

positional arguments:
  text

options:
  -h, --help  show this help message and exit
  --bot BOT
  --session ID
  --json
  --attach PATH
```

Example: `gbot send --bot "Research" "Prepare a summary"`.

`--bot BOT` overrides the selected bot. `--session ID` routes the prompt to that session. Use tail or ask to inspect subsequent activity.

`--json`: Object with `accepted`, `bot` (id, name), and `last_seq`, the highest sequence before sending, or null if none. It is not the eventual reply.

Repeat `--attach PATH` to upload local files before sending; text may be omitted when
files are attached. JSON adds `attachments` with each file's `name` and committed `path`.
Upload errors exit 1 without sending a prompt. Upload progress appears only on terminal stderr.
Files must be nonempty and at most 25 MiB (200 MiB for mp4, mov, m4v, webm, mkv and avi).

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

`--bot BOT` selects a bot. `-n N` limits initial entries (20 default; 0 prints none). `--since SINCE` starts after an entry ID in the fetched tail, not a date; missing IDs error. `--after SEQ` keeps entries with sequence greater than SEQ, including with `-n` and `--follow`. `--full` avoids the 160-character text truncation. `--follow` subscribes to SSE, backfills missed entries and reconnects after transient failures; duplicate entries are suppressed. Ctrl+C exits 0.

`--json`: Array of raw entries normally; with follow, one compact entry per line (JSON Lines), including the initial selected entries. Entries include `seq`, `id`, `kind`, `timestampMs`, and `message`; `message` kind is user and `send-message` is bot. Full affects text rendering only.

## tui

Open the terminal UI against your signed-in account and its live event stream.
Run `gbot login` first if signed out; `--demo` uses synthetic bots offline.

```text
usage: gbot tui [-h] [--bot BOT] [--demo] [--screenshot PATH] [--size WxH] [--ascii]

options:
  -h, --help         show this help message and exit
  --bot BOT
  --demo
  --screenshot PATH
  --size WxH
  --ascii
```

Example: `gbot tui --demo`.

Install the repository's `tui` extra using the editable uv tool installation
described in the [README](../README.md). Help works without this extra.
`--bot BOT` opens a session by ID or name. `--ascii` uses plain ASCII symbols.
`--screenshot PATH` writes a read-only headless SVG after the first load and exits;
it never marks a chat read, sends a message or answers a card. If loading takes
more than 20 seconds it still writes the SVG, reports the timeout and exits 1.
`--size WxH` sets screenshot dimensions (120x40 default).
Example: `gbot tui --demo --screenshot home.svg --size 100x30`.

On home, Up/Down select, Enter/Right open a bot, Space toggles Peek,
Ctrl+F filters, Ctrl+T pins, Ctrl+S changes grouping, and Shift+Up/Down
reorders. In Peek, Tab focuses reply and 1-9 choose an answer.
In a session, Enter sends, Tab focuses the prompt, PageUp/PageDown browse
history, Home/End jump to top/latest, and Escape returns home.
`?` shows home help and Ctrl+P opens the command palette.
Press Ctrl+C twice within two seconds to exit. Printable shortcuts only act
when no text input has focus.

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

## watch

Watch bot states and summaries as they change.

```text
usage: gbot watch [-h] [--bot BOT] [--once] [--json]
```

Example: `gbot watch --bot Research --json`.

`--once` prints a roster snapshot and exits 2 if a bot is awaiting a response, otherwise 0. States are awaiting, working, new and idle, in that priority order. `--bot` limits the view to one bot and includes its transcript entries while streaming. Ctrl+C exits 0.

`--json` produces an array for `--once`; streaming emits JSON Lines with state, connection and selected bot entry records.


Answers to pending cards go to the Cursor backend's `aiserver.v1.GrokBotService`, using the same path as the desktop app.

## avatar

```text
gbot avatar BOT [--file FILE.png | --generate TEXT | --clear] [--save-to FILE] [--yes] [--json]
```

BOT is a name or ID. With no mutation option, show shape, color and whether an
image is set. `--save-to` exports the current or generated image and refuses to
overwrite a file. `--file` accepts PNG up to 2 MiB and 1024 pixels on either side;
resize larger images before importing. Generation is separate from saving to the
bot: the command reports the generated image's MIME type and byte count, then
asks for confirmation before applying it. Generated images must be valid PNG to
apply. `--clear` removes the image. Mutations require confirmation on a terminal
or `--yes` when running without one.

`--json`: Object with id, shape, color, has_image, mime_type and saved_to.

## voice

```text
gbot voice BOT [--voice ID] [--speed N] [--language L] [--yes] [--json]
gbot voice --list [--json]
```

With no options, show the current voice. `--list` lists available voice IDs,
speeds and languages in JSON (voice IDs and labels in text). Speeds snap to
0.5, 0.75, 1, 1.25, 1.5 or 2; invalid speeds become 1. Unknown languages become
auto. Changes require terminal confirmation or `--yes`. Audio preview uses the
Grok Bot app.

`--json`: Object with id, voice_id, speed and language; `--list` returns voices,
speeds and languages.

## skills

```text
gbot skills BOT [--all] [--json]
gbot skills BOT --show SKILL [--json]
gbot skills BOT --new --name N --description D --body FILE|- [--schedule S] [--yes] [--json]
gbot skills BOT --edit SKILL [--name N] [--description D] [--body FILE|-] [--schedule S] [--unschedule|--pause|--resume] [--yes] [--json]
gbot skills BOT --delete SKILL [--yes] [--json]
gbot skills BOT --run SKILL [--yes] [--json]
gbot skills BOT --import-file PATH [--name N] [--yes] [--json]
gbot skills BOT --import-url URL [--name N] [--yes] [--json]
gbot skills BOT --install CATALOG_ID [--yes] [--json]
gbot skills --catalog [--search TEXT] [--json]
```

List editable and scheduled skills; `--all` includes managed skills. `--show`
prints the description and body. SKILL accepts an ID, a unique ID prefix of at
least six characters, or an exact case-insensitive name. `--new` requires a
nonblank name, description and body. `--body -` reads standard input; other body
and import files are UTF-8. `--edit` resends unchanged fields; `--schedule` sets a
trimmed schedule for server validation, `--unschedule` removes it, and `--pause`
or `--resume` changes its enabled state. Managed, template and plugin skills
cannot be edited or deleted. `--run` requires a scheduled skill.

All mutations require terminal confirmation or `--yes`. Imports accept local
Markdown or HTTP/HTTPS URLs. `--catalog` browses names, publishers and short
descriptions; `--search` filters them. `--install` imports the catalog entry by
its URL or content. Unsupported install kinds use the Grok Bot app.

`--json`: Lists and create/edit/delete return skill arrays; show returns one
skill; run returns id and started (request acknowledged, not run completion).
Imports/install return added_count and workflow_count, based only on before/after
workflow counts. Catalog returns id, name, description, publisher and install_kind.
`--help` (or `-h`) shows command usage.

## templates

```text
gbot templates [--category C] [--json]
gbot templates show SHARE_ID [--json]
gbot templates use SHARE_ID [--yes] [--json]
```

Browse featured and public listings, inspect a template's summary and active
version, or create a bot from that version. Import requires terminal confirmation
or `--yes`. When the server has not handled setup, finish the recipe in the Grok
Bot app. Browsing stops after 20 pages of 100 listings. No recipe blob is fetched.

`--json`: Browsing returns featured_listings, listings and category_order; show
returns template, expected_active_version and creator_display_name; use returns
bot, setup_handled_by_server and note. Template version inspection and publishing
remain planned for a later milestone.

## secrets

```text
gbot secrets BOT [--json]
gbot secrets --computer [--json]
gbot secrets BOT --set NAME [--description TEXT] --yes [--json]
gbot secrets BOT --delete NAME --yes [--json]
gbot secrets BOT --copy-from-computer NAME [NAME ...] --yes [--json]
```

List a bot's secret names, descriptions and update times, or the secret names on
the bot's desktop computer and whether they are applied. Values are never shown.
`--set` reads the value from a hidden prompt, or one line of stdin when stdin is
not a terminal; no option takes a value. Names are uppercased and must start with
a letter; reserved names such as PATH and prefixes such as CURSOR_ are refused.
Values are at most 4,096 bytes. Changes need `--yes`, and only the bot's owner can
change its secrets.

`--json`: List rows have name, description and updated_at_ms; `--computer` returns
keys, card_keys, is_applied and last_applied_at_ms; `--set` and `--delete` return
the name; `--copy-from-computer` returns name and outcome per secret.

## inboxes

```text
gbot inboxes [--json]
gbot inboxes --create USERNAME [--yes] [--json]
```

List the account's email inboxes and whether each is assigned to a bot, or create
one. Usernames are lowercased and cannot contain `@` or spaces. Creating requires
terminal confirmation or `--yes`. Email threads stay in the Grok Bot app.

`--json`: Rows have email, domain, created_at_ms and assigned; `--create` returns
the new inbox.

## computer

```text
gbot computer BOT [--json]
gbot computer BOT --wake|--update|--hand-back [--yes] [--json]
gbot computer BOT --open
```

Show a bot's desktop computer: state, phase, host version, available updates,
disk pressure and a pending hand-off's instruction. `--wake` starts it, `--update`
updates it (it restarts), and `--hand-back` returns a pending hand-off to the bot.
These require terminal confirmation or `--yes`. `--open` opens the live view in a
browser. The live-view link carries an access token, so gbot never prints it.

`--json`: Object with state, phase, handoff_request_id, handoff_instruction,
pull_percent, host_version, host_update_available, image_update_available and
disk_pressure.
