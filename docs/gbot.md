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
usage: gbot approve [-h] [--yes] [--json] [--bot BOT] [--always] [--all-bots] REF

positional arguments:
  REF

options:
  -h, --help  show this help message and exit
  --yes
  --json
  --bot BOT   Bot that owns REF, when REF is ambiguous
  --always
  --all-bots  connector grant: always allow for all team bots
```

Example: `gbot approve REF`.

`--always` sends a persistent approval resolution instead of a one-time approval. `--yes` skips confirmation.
For connector grants, `--always` remembers permission for this bot; add `--all-bots`
to remember permission for all team bots. `--all-bots` requires `--always` and a
connector grant. Use `gbot deny REF` to skip a connector grant.

## deny

Deny a review or local tool request. Meeting-consent cards are answered in the app.

```text
usage: gbot deny [-h] [--yes] [--json] [--bot BOT] [--never] REF

positional arguments:
  REF

options:
  -h, --help  show this help message and exit
  --yes
  --json
  --bot BOT   Bot that owns REF, when REF is ambiguous
  --never
```

Example: `gbot deny REF`.

`--never` persistently denies only local tool permissions. `--yes` skips confirmation.
On a meeting-consent card, `deny` exits 1 with `meeting-join-consent: answer in the Grok Bot app.` Answer that card in the app.

## respond

Answer a widget or ordinary user form.

```text
usage: gbot respond [-h] [--yes] [--json] [--bot BOT] [--field NAME=VALUE] REF [VALUE]

positional arguments:
  REF
  VALUE

options:
  -h, --help          show this help message and exit
  --yes
  --json
  --bot BOT   Bot that owns REF, when REF is ambiguous
  --field NAME=VALUE
```

Example: `gbot respond REF --field city=Brisbane`.

Supply VALUE for a widget, or repeat `--field NAME=VALUE` for a form; do not mix them. Widget values must match `options` unless custom or multi-select is allowed. Use IDs from `fields` for forms. Field names must be unique. Forms are submitted with vault saving disabled. `--yes` skips confirmation. Avoid sensitive values in shell history.

## dismiss

Dismiss a widget or ordinary user form.

```text
usage: gbot dismiss [-h] [--yes] [--json] [--bot BOT] REF

positional arguments:
  REF

options:
  -h, --help  show this help message and exit
  --yes
  --json
  --bot BOT   Bot that owns REF, when REF is ambiguous
```

Example: `gbot dismiss REF`.

`--yes` skips confirmation. Form dismissal sends mode dismissed.

## secret

Supply an eligible requested secret through hidden input.

```text
usage: gbot secret [-h] [--yes] [--json] [--bot BOT] REF

positional arguments:
  REF

options:
  -h, --help  show this help message and exit
  --yes
  --json
  --bot BOT   Bot that owns REF, when REF is ambiguous
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

## automations

```sh
gbot automations [BOT] [--json]
gbot automations BOT --show ID [--json]
gbot automations BOT --new --name N --prompt P --schedule S [--off] [--yes] [--json]
gbot automations BOT --edit ID [--name N] [--prompt P] [--schedule S] [--yes] [--json]
gbot automations BOT --on ID [--yes] [--json]
gbot automations BOT --off ID [--yes] [--json]
gbot automations BOT --delete ID [--yes] [--json]
gbot automations BOT --run ID [--no-wait] [--yes] [--json]
```

Omit BOT to list the account. `--show` includes prompt and recent runs.
ID is a record ID, a unique prefix of at least six characters, or an exact
name. `--new` requires `--name`, `--prompt` and `--schedule`; bare `--off`
creates it disabled. `--edit` preserves unspecified fields. `--prompt -`
reads stdin. `--on ID` and `--off ID` enable or disable; `--delete` removes.
`--run` waits up to 120 seconds for a new run and prints its status;
`--no-wait` returns after the request. Every mutation requires terminal
confirmation or `--yes`. `--help` shows command help.

Schedules support numeric five-field cron, lists/ranges/steps, macros
`@hourly`, `@daily`, `@midnight`, `@weekly`, `@monthly`, `@yearly`, `@annually`,
and `@every` durations (ms/s/m/h/d, including combined/decimal durations and
an optional `/phase` shorter than the interval). Prefix `TZ=Zone` or
`CRON_TZ=Zone` for a validated timezone. Non-cron triggers retain their fields
on edit; change their trigger in the Grok Bot app.

`--json`: listing returns record objects including bot_id, server_id and
allowed actions. Show returns one record; create/edit/toggle/delete return
an automations object; run returns id, status and the new run (or null).
Exit 0 on success, 1 on error, cancellation or run-start timeout.

## plugins

```text
gbot plugins BOT [--json]
gbot plugins BOT --add ENTRY [--yes] [--json]
gbot plugins BOT --remove PLUGIN [--yes] [--json]
gbot plugins BOT --set-var PLUGIN NAME [--yes] [--json]
```

List visible plugins with skills, servers and `needs setup` for unconfigured
settings. `--add` selects a catalog entry by ID, name or unique display name;
`--remove` selects a plugin by ID or unique display name. Existing hidden
bot-skills plugins are preserved. Add plugins with nonnumeric IDs in the app.

`--set-var` reads one setting from `Value for NAME (hidden): ` in a terminal,
or one line from stdin otherwise. No option takes a setting value. Stored values
are never shown; empty inputs are refused and filled inputs merge with stored
settings. Mutations require terminal confirmation or `--yes`. After adding a
plugin needing setup, the command prints a settings command to run next.

`--json`: Lists safe plugin metadata; a settings save returns plugin_id and saved.

## catalog

```text
gbot catalog [--category KEY] [--search TEXT] [--json]
gbot catalog show ENTRY [--json]
```

Browse connector plugins by popularity rank, then display name (missing ranks
last). Lists show display name, category, publisher and connector count.
`--category` matches a category or category key; `--search` filters name and
description. `show` selects by ID, name or unique display name and includes setup
field labels, required status and secret status.

`--json`: An array of catalog metadata, or one entry object for `show`.

## voice

```text
gbot voice BOT [--voice ID] [--speed N] [--language L] [--yes] [--json]
gbot voice --list [--json]
```

With no options, show the current voice. `--list` lists available voice IDs,
speeds and languages in JSON (voice IDs and labels in text). Speeds snap to
0.5, 0.75, 1, 1.25, 1.5 or 2. A speed that is not a number is refused with
`Speed must be a number, such as 1.25.` Unknown languages become
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

## connector

```text
gbot connector SERVER [--json]
gbot connector SERVER [--disable-tool T] [--enable-tool T] [--permission T=LEVEL]
  [--reads LEVEL] [--writes LEVEL] [--instructions TEXT] [--rename-account OLD NEW]
  [--remove-account KEY] [--remove] [--shared-spaces on|off] [--yes] [--json]
gbot connector SERVER --sign-in [--account KEY] [--reauth] [--no-browser] [--yes] [--json]
gbot connector --clear-always-allow [--yes] [--json]
```

Show one connector's status, account, transport, tools, permission defaults,
group-chat access and custom instructions. SERVER matches a unique ID, server
identifier, name or plugin display name, ignoring case. `--json` returns these
fields as an object; credentials and browser sign-in links are excluded.

`--disable-tool` and `--enable-tool` change a tool's enabled state.
`--permission T=LEVEL` changes one tool; `--reads` and `--writes` change defaults.
LEVEL is auto, allow, ask or block (also auto_review, always_allow,
needs_approval or blocked). Auto removes an explicit tool override.
`--instructions TEXT` trims and saves text; empty text clears, and `-` reads stdin.
`--rename-account OLD NEW` renames an account, `--remove-account KEY` removes
one, and `--remove` removes the connector. Team connectors are managed by admins.
`--shared-spaces on|off` controls availability in group chats.
`--clear-always-allow` forgets all saved always-allow answers for connector tools.

Every mutation requires terminal confirmation or `--yes`. `--sign-in` starts
browser authentication, optionally for `--account KEY`; `--reauth` forces a new
sign-in. The handoff link prints only on stderr. `--no-browser` displays the
link without opening it. Completion requires a status change; opening a link
alone is insufficient. Ctrl+C cancels waiting (exit 130). If the browser asks
to open the Grok Bot app, finish there: gbot cannot receive that callback.
`--help` (or `-h`) displays command usage.

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
bot, setup_handled_by_server and note. Publishing a template and listing a bot in
the marketplace are under `gbot publish`.

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

## vault

```text
gbot vault [--json]
gbot vault --add-login --title T --username U [--site S ...] [--notes N] --yes [--json]
gbot vault --update-login ID [--title T] [--username U] [--site S ...] [--notes N] --yes [--json]
gbot vault --delete ID --yes [--json]
gbot vault --payment-methods [--json]
gbot vault --passkeys [--json]
gbot vault --revoke-passkey ID --yes [--json]
gbot vault --onepassword [--json]
gbot vault --onepassword-sync --yes [--json]
gbot vault --onepassword-disconnect ID --yes [--json]
```

List the account's vault logins, cards and contacts (cards as brand and last four
digits only), add or update a login, or delete an item. The password comes from a
hidden prompt, or one line of stdin when stdin is not a terminal; no option takes a
password, and updating a login asks for it again. Options left out of an update keep
the login's current values. Sites must be hosts or HTTP URLs. Also lists saved
payment methods, lists and revokes passkeys, and shows, syncs or disconnects
1Password connections. Changes need `--yes`. Cards, payment methods, passkey
enrollment and connecting 1Password stay in the Grok Bot app.

`--json`: Items have id, kind, title, username, notes, sites, created_at_ms,
updated_at_ms, card, contact and managed_by; the other options return their
objects. No output contains a password.

## account

```text
gbot account egress [--json]
gbot account analytics BOT [--json]
gbot account payment [--json]
gbot account address QUERY [--pick N] [--json]
```

Read-only views of your account; nothing here changes state, so none asks for a
confirmation. `egress` shows whether the cloud computer's outbound network is open
or restricted, with the allowed domains and TCP destinations. `analytics` shows a
bot's weekly active users, its minutes saved (or `Not measured`), the last 14 days
with the latest first, and the top users per window; a bot with no analytics yet
says so. `payment` shows the default payment method: a card's brand and last four
digits from your vault, or a wallet's name. It says that the default is changed in
the Grok Bot app. `address` lists suggestions for QUERY. `--pick N` resolves
suggestion N from that same lookup and prints the formatted address and its parts.
A refusal from the server is printed as its message, and the command exits 1.

`--json`: `egress` has restricted, allowed_domains and allowed_tcp (cidr and
port). `analytics` has the analytics object (weekly_active_users, days,
top_users and top_users_by_window), or null when the bot has none. `payment` has
kind, wallet and label. `address` has outcome and suggestions (index, title and
subtitle); with `--pick` it has the address parts (street, city, state,
postal_code, country, country_code and formatted). The vault card id and the
lookup token are never printed.

## teams

```text
gbot teams BOT [--json]
gbot teams BOT --connect [--admin] [--no-browser] --yes [--json]
gbot teams BOT --install [--team ID ...] [--no-personal] --yes [--json]
gbot teams BOT --reinstall|--uninstall --yes [--json]
gbot teams BOT --add-to-team ID --yes [--json]
gbot teams BOT --disconnect TENANT --yes [--json]
gbot teams --account [--json]
gbot teams --link-account [--no-browser] --yes [--json]
gbot teams --unlink-account TENANT --yes [--json]
```

Show whether a bot's Microsoft Teams app is set up and where it is installed,
connect it (Microsoft consent in the browser; `--admin` asks for admin consent),
install it personally or into teams, reinstall, uninstall, add it to another team,
or disconnect a tenant. `--account` lists your own Teams account links, and
`--link-account` and `--unlink-account` change them. Browser steps wait until the
status changes; `--no-browser` prints the link without opening it. Changes need
`--yes`.

`--json`: The state object (state, tenant, installed teams, flags and messages);
account links have tenant_id, aad_object_id and linked_at_ms.

## publish

```text
gbot publish BOT [--json]
gbot publish BOT --listing on|off --yes [--json]
gbot publish BOT --template-version N [--share-id ID] --yes [--json]
gbot publish BOT --template-visibility public|team [--share-id ID] --yes [--json]
gbot publish BOT --delete-template [--share-id ID] [--yes] [--json]
```

Show whether a bot is listed in the Grok Bot marketplace, its template (name,
share ID, published, active version, visibility) and what the account may do with
templates. `--listing on` lists the bot in the marketplace and `--listing off`
takes it off; the answer is one sentence (for example, a bot must be shared before
it can be listed). `--template-version N` publishes version N of the template,
`--template-visibility` makes it visible to everyone (`public`) or to your team
(`team`), and `--delete-template` deletes it. `--share-id ID` acts on that
template instead of the bot's own. When the account's policy is off, template
changes are refused with a sentence saying so, and `public` is refused when the
policy allows teams only. A refusal from the server exits 1 with its message.

Every change needs `--yes`; without it and without a terminal nothing is sent. In
a terminal, `--delete-template` without `--yes` asks you to type the template name.

`--json`: The marketplace state, the template, the export policy and its sentence;
for a change, the result of each change.

## files

```text
gbot files BOT [--json]
gbot files BOT --upload PATH --yes [--json]
gbot files BOT --delete NAME --yes [--json]
gbot files BOT --delete-user-file PATH --yes [--json]
```

List a bot's files (every page, with the total size and whether you can edit),
then the files in its user store. A part the server refuses is shown as its
message and the other part is still listed. `--upload` sends one local file to the
bot, `--delete` removes a bot file by name, and `--delete-user-file` removes a
user-store file by path. Each change needs `--yes`; without it, and without a
terminal, nothing is sent. Upload addresses are never printed.

`--json`: `bot`, `files`, `total_bytes`, `can_edit`, `user_store_files` and
`notices`; a change prints `uploaded`, `deleted` or `deleted_user_file`.

## library

```text
gbot library BOT [--json]
gbot library BOT --pin KEY --yes [--json]
gbot library BOT --unpin KEY --yes [--json]
gbot library BOT --merge-pins FILE --yes [--json]
```

List the documents the bot has touched, marked when pinned, then its pins.
`--pin` and `--unpin` take an external document key (the `key` shown for each
document). `--merge-pins` reads a JSON list of pins in the shape of
`gbot library BOT --json` (`pins`) and merges it into the bot's pins, which copies
pins between bots. Each change needs `--yes`.

`--json`: `bot`, `docs` (each with `pinned`), `pins` and `notices`; a change prints
the pin list after it.

## sandbox

```text
gbot sandbox [--json]
gbot sandbox --recreate [--discard-data] [--acknowledge-schedule] --yes [--json]
gbot sandbox --force-recreate --yes [--json]
gbot sandbox --schedule-upgrade HH:MM [--timezone TZ] [--recurring] --yes [--json]
gbot sandbox --reschedule-upgrade HH:MM [--timezone TZ] [--recurring] --yes [--json]
gbot sandbox --cancel-upgrade [--dismiss-outcome] --yes [--json]
```

Show the cloud computer's run state (absent, hibernated, running, starting or
unknown), its image tag, whether an image update is available, and its upgrade
schedule. Recreate the cloud computer: data is kept unless `--discard-data` is
given. `--acknowledge-schedule` is meant to let a recreate proceed past a terminal
upgrade schedule; the protocol notes infer this, so it is unconfirmed.
`--force-recreate` has no keep-data choice. Schedules take a 24-hour `HH:MM` time
and an IANA time zone (`--timezone`, UTC by default); `--recurring` asks for the
upgrade to repeat, but the protocol notes do not confirm how often. `--cancel-upgrade`
cancels the scheduled upgrade, and `--dismiss-outcome` also dismisses the outcome of
a finished one. Host settings and update-now stay in the Grok Bot app.

Every change needs `--yes`. In a terminal, `--discard-data` and `--force-recreate`
ask you to type `recreate` instead of confirming with `y`; the times and time zone
are checked before anything is sent. A recreate prints whether it started, the
reason and the operation ID. If the server does not start it, the report is still
printed and the exit code is 1. A refusal exits 1 with the server's message.

`--json`: For a read, the state, image tag, update flag, egress tunnel ownership,
the upgrade schedule (or null) and a notice for any part the server refused. For a
recreate, `started`, `reason` and `operation_id`. For a schedule change, the
schedule.

## settings

```text
gbot settings [--json]
gbot settings --pin BOT --yes [--json]
gbot settings --unpin BOT --yes [--json]
gbot settings --auto-review on|off --yes [--json]
```

Show your runtime settings: the pinned bots by name, whether auto-review is on,
whether onboarding has been seen, the main bot and the email provider. `--pin` and
`--unpin` take a bot by name or ID; `--unpin` also accepts the ID of a pinned bot
that is no longer in your roster. `--auto-review` turns auto-review on or off and keeps
its allow and block lists. Each change needs `--yes`; a change
that is already in place sends nothing and prints the current settings.

`--json`: `pinned_bots` (id and name for each), `auto_review_enabled`,
`has_seen_onboarding`, `main_bot` (id and name, or null), `email_provider` and
`updated_at_ms`.

## team

```text
gbot team [--role ROLE] [--json]
gbot team BOT --summary [--json]
gbot team BOT --review [--status pending|approved|rejected ...] [--limit N] [--json]
gbot team BOT --memories [--json]
gbot team BOT --approve ITEM --yes [--json]
gbot team BOT --reject ITEM --yes [--json]
gbot team BOT --promote FACT_ID ... --yes [--json]
gbot team --link-preview TEAM_ID [--json]
gbot team --link-preview TEAM_ID --set on|off --yes [--json]
```

List your team's bots with their turn counts, read a bot's shared summary, its
review queue and the memories you can share with the team, approve or reject a
review item, share memories with the team, and read or change a team's link
previews. This needs a team account: on a personal account the server's refusal
is the error message, with exit code 1. The TUI shows the same screens; see
[tui/team.md](tui/team.md).

`--role` lists only the team bots with that role; without it, every team bot is
listed. `--status` may repeat; it defaults to pending. `--limit` defaults to 100. Use
the IDs from `--review` and `--memories` with `--approve`, `--reject` and
`--promote`. `--promote` takes one or more memory IDs. `--set` turns a team's
link previews on or off; it is a team-wide switch, not a bot's public card.

Every change needs `--yes`. Without it, a terminal asks for confirmation; without
a terminal, nothing is sent. A change that the server refuses exits 1 with the
server's message.

`--json`: With no BOT, a list of team bots (agent_id, name, user_turns,
teammate_turns, last_turn_at_ms). `--summary` gives prose, generated_at_ms,
memory_version, summary_model, stale, skills, learned (fact_id, text,
learned_at_ms) and memory_count. `--review` gives a list of items (item_id,
status, proposed and reviewed user IDs, created and reviewed times, and change).
`--memories` gives a list of facts. `--approve` and `--reject` give the item.
`--promote` gives created, already_in_team and kept_private_count. The link
preview gives team_id and enabled.

## channels

```text
gbot channels slack BOT [--json]
gbot channels slack BOT --connect|--reinstall|--uninstall [--no-browser] --yes [--json]
gbot channels slack BOT --install [--workspace ID] [--no-browser] --yes [--json]
gbot channels sms [--json]
gbot channels sms --link --yes [--json]
gbot channels sms --unlink HANDLE --yes [--json]
gbot channels listeners [--json]
gbot channels listeners --connect PLATFORM [--no-browser] --yes [--json]
```

`slack` shows whether a bot is connected to Slack and in which workspace, and
connects, installs, reinstalls or uninstalls its Slack app. `sms` shows whether
texting your bots is available, the line number and the linked phones; `--link`
issues a code with the message to text from your phone, and `--unlink` removes a
phone. `listeners` lists the event sources automations can listen to (GitHub and
others) and connects one. Browser steps wait until the status changes;
`--no-browser` prints the link without opening it. Changes need `--yes`.

`--json`: The Slack state, the messaging link with its phones, or the listener
integrations (platform, connected, state and the number of automations that need
it).

## listings

```text
gbot listings targets [--json]
gbot listings publish-skill BOT SKILL [--team ID] --yes [--json]
gbot listings resync-skill BOT SKILL --yes [--json]
gbot listings unpublish-skill BOT SKILL --yes [--json]
gbot listings plugin BOT PLUGIN [--json]
gbot listings unpublish-plugin BOT PLUGIN [--team ID] --yes [--json]
```

`targets` shows where skills can be published: the teams you can publish to, or
the reason publishing is unavailable (a personal account with no team has none).
`publish-skill` publishes a skill, `resync-skill` refreshes a published skill from
its current text, and `unpublish-skill` removes its listing. SKILL is a skill's
workflow id or its name (see `gbot skills BOT`). `--team ID` publishes to or
removes the listing from that team and is sent only when given.

`plugin` tells whether a plugin's listing has a private copy that stays when the
listing is removed. `unpublish-plugin` takes the listing down; PLUGIN is a plugin id
or name (see `gbot plugins BOT`). Run `plugin` first to know whether a copy stays.

Changes need `--yes` (in a terminal, without it you are asked to confirm; without
a terminal nothing is sent). A bot that is hosted by the backend may refuse these
commands: the server's message is the error message and the exit code is 1.

`--json`: `targets` has teams (team_id, name), unavailable_reason and
unavailable_kind; `plugin` has plugin_id, name and restorable_copy; a change has
ok, state and message plus the workflow_id or plugin_id it applied to.

## apps

```text
gbot apps [--json]
gbot apps --update BC_ID --slug S --apex A --visibility private|team|public [--mute-redeploy-prompts] [--require-confirmation] --yes [--json]
gbot apps --unpublish BC_ID --slug S --apex A --yes [--json]
```

List your published cloud-agent apps (slug, apex, visibility and the cloud agent
that built each), change one's slug, apex, visibility and update prompts, or
unpublish it. When cloud-agent apps are off for the account, the list says so in
one sentence. `--mute-redeploy-prompts` stops redeploy prompts and
`--require-confirmation` asks before each update; both go with `--update`.
Changes need `--yes`. A refusal from the server is shown as its own sentence; a
refused change exits 1. The app gate (the page that admits viewers with a
short-lived ticket) opens only in the Grok Bot app, and app links are never
printed.

`--json`: The list is an object with kind (on, off or unknown) and apps (bc_id,
slug, apex and visibility); `--update` and `--unpublish` return ok, state and
message.

## cloud-agent

```text
gbot cloud-agent BC_ID [--files] [--artifacts] [--json]
gbot cloud-agent BC_ID --conversation [--json]
gbot cloud-agent BC_ID --stop --yes [--json]
gbot cloud-agent BC_ID --proposals [--json]
gbot cloud-agent BC_ID --confirm-proposal ID --bot BOT --slug S --visibility private|team|public [--require-confirmation] --yes [--json]
gbot cloud-agent BC_ID --dismiss-proposal ID [--bot BOT] --yes [--json]
gbot cloud-agent BC_ID --secrets DIR [--json]
gbot cloud-agent BC_ID --set-secret NAME [--set-secret NAME ...] --project-dir DIR --yes [--json]
```

Show a cloud agent's status, title, branch, repository, creation time and file
and artifact counts (`--files` and `--artifacts` ask the server to include them),
or say that no cloud agent has that id. `--conversation` prints its messages and
`--stop` stops it. `--proposals` lists its publish proposals; `--confirm-proposal`
publishes one as the given slug and visibility for the bot named by `--bot`, and
`--dismiss-proposal` dismisses one (`--bot` is optional there).

`--secrets DIR` lists the names of the app's secrets in that project directory;
values are never shown. `--set-secret` saves values for one or more names in the
directory given by `--project-dir`: each value comes from a hidden prompt, or one
line of stdin per name when stdin is not a terminal, and no option takes a value.
gbot then tells the bot which names were saved and which were refused, as the
app does. Refused names are listed with the reason and the command exits 1.
Changes need `--yes`. A refusal from the server is shown as its own sentence; a
refused change exits 1. Reply links are never printed.

`--json`: The info object (bc_id, status, title, branch, repo, created_at,
file_count, artifact_count and extra, the names of other reply fields), or null
when there is none; messages have role and text; proposals have proposal_id,
slug, visibility and summary; `--secrets` returns the names; `--set-secret`
returns saved, refused (name, kind, message, permanent) and apply_needed; the
other changes return ok, state and message, or `--stop` returns bc_id and
stopped.

## share

```text
gbot share BOT [--json]
gbot share BOT --share-status [--json]
gbot share BOT [--grant KIND[:ID]=ROLE ...] [--revoke KIND[:ID] ...] --yes [--json]
gbot share BOT --team-row on|off [--role user|manager] --yes [--json]
gbot share BOT --team-visible [--carry-secret NAME ...] --yes [--json]
gbot share BOT --share-in-place --yes [--json]
gbot share BOT --clone-to-team [--carry-secret NAME ...] --yes [--json]
gbot share BOT --invite EMAIL [--language TAG] --yes [--json]
gbot share BOT --revoke-invite EMAIL --yes [--json]
gbot share BOT --add-manager USER_ID --yes [--json]
gbot share BOT --remove-manager USER_ID --yes [--json]
gbot share --preview-invite [--json]
gbot share --accept-invite --yes [--json]
```

Show who has a bot and with what role: the owner, each access row, the team row,
link access, managers and the invites you sent. A part the server refuses (for
example invites on an account without a team) shows the server's sentence and the
rest still prints. Every change needs `--yes`; without it, and without a terminal
to confirm in, nothing is sent. A change the server refuses exits 1 with its
message. Only one kind of change runs per call, except that `--grant`, `--revoke`
and `--team-row` together make one update.

- `--grant KIND[:ID]=ROLE` and `--revoke KIND[:ID]` (repeatable): change access
  rows. KIND is `user`, `group`, `other_team` or `organization` (the team row has
  its own option); `user`, `group` and `other_team` need an id, as in
  `user:12=manager`. ROLE is `user` or `manager`. The whole list is sent back with
  the token read a moment before, so a change someone else made in between is
  refused rather than overwritten. The owner is never part of the list.
- `--team-row on|off` with `--role user|manager`: turn the row for everyone in the
  team on or off. Without `--role`, a row that is already there keeps its role; a
  new row is `user`. Turning it off is refused when no other row would remain and the
  server does not allow it.
- `--team-visible`: make the bot visible to the team. `--clone-to-team`: copy it
  into the team. `--carry-secret NAME ...` (repeatable) names personal secrets to
  carry over; values are never sent.
- `--share-in-place`: start sharing the same bot with the team. The server keeps
  working after the command returns; `--share-status` reads the state and step
  once (not started, running, done or failed).
- `--invite EMAIL`: the server emails the invite; the link is never shown.
  `--language TAG` sets the email language (`en`, `pt-BR`). The result says whether
  the invite was created, whether the email went out, when it expires and how many
  invites the bot has used. `--revoke-invite EMAIL` cancels one.
- `--add-manager USER_ID` and `--remove-manager USER_ID`: change the managers.
- `--preview-invite` and `--accept-invite`: for an invite someone sent you. The code
  or link is read from a hidden prompt, or from one line on stdin when there is no
  terminal, and never from the command line. The preview shows the bot, the sender,
  your role, the state and whether you can accept; accepting grants the access.
- `--yes`: confirm a change. `--json`: print JSON.

`--json`: the read has `bot`, `access` (owner, team row and rows with kind, id,
name and role), `link_access`, `managers` and `invites` (with `cap_usage`); a
refused part is `{"refused": "<message>"}`. Changes print their result (outcome and
message, created and email_sent for invites). No output contains an invite link or
code.
