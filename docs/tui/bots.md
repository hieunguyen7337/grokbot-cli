# Bot management service (M3)

`gbot.service.bots` provides account capabilities and creation routing, bot
creation and profile edits, deletion, sidebar visibility, update notifications,
drafting, main-bot settings, roster count/open, conversation naming and collaborator
automation policy. `gbot bot` exposes these operations in the CLI. The existing TUI
identity editor shares the service update path; this change adds no new slash panel.

Temporal creation uses the backend and preserves the caller's nonce as the bot
identity. Box creation uses `createAgent` followed by `kickstartAgent`. Rooms use
the same route decision. Server metadata keeps backend `id` separate from logical
`agentId`, and carries ownership, group, drafting and voice fields.

Deletion and runtime toggles reject nonowners. Managed nonowner identity rows use
`UpdateGrokBotAgent`; owner edits continue through gateway `updateAgent`. Deletion
protects the main bot, and drafting rejects groups. Main-bot pointers use user
settings RPCs. Conversation open returns parsed entries; unknown naming and policy
reply fields stay available as raw mappings.

## CLI options and results

Manage bot identity, instructions and settings. BOT accepts a name or ID. Every
action accepts `--json`; mutations ask for confirmation in a terminal and require
`--yes` when run noninteractively.

```text
gbot bot new NAME [--description TEXT] [--shape S] [--color C] [--avatar FILE.png]
gbot bot count
gbot bot open BOT
gbot bot seed-name BOT PROMPT [PROMPT...]
gbot bot collaborator-automation BOT on|off
gbot bot edit BOT [--name NAME] [--title TITLE] [--description TEXT | --description-file FILE] [--avatar FILE.png | --clear-avatar]
gbot bot delete BOT [BOT...]
gbot bot hide BOT
gbot bot show BOT
gbot bot notify BOT on|off
gbot bot drafting BOT on|off
gbot bot main [BOT]
gbot bot info BOT
```

`new` trims the name (1–255 characters), defaults to a blue blob, and accepts a
PNG avatar. Creation selects the account's temporal or box route automatically.
Temporal creation requires both durable identity flags. Description is the bot's
instructions; `edit --description-file` reads UTF-8 text. Unspecified profile
fields are preserved. An edit that changes nothing is refused.

`delete` previews every selected bot and warns that its conversation history is
removed. The current main bot cannot be deleted; select another main bot first.
Partial deletion failures return exit code 1 and list refused and failed IDs.
Deletion and runtime toggles require ownership. Managed nonowner identity edits
use the backend partial update; avatar upload and clear use its avatar oneof.
Drafting is available only for non-group bots; `off` disables
drafting. `notify` controls update notifications separately from general notifications.

`main` without BOT reads the server's main-bot pointer (which can be unset);
with BOT it sets that pointer. This is separate from `gbot use`'s local selection.
`info` shows name, title, instructions, harness, ownership, hidden state, update
notifications, drafting, voice and whether this is the main bot.
`count` returns a number. `open` returns entry records and applies the gateway's
read acknowledgement. `seed-name` returns the kept/seeded outcome and raw agent
mapping. `collaborator-automation` returns the routine policy mapping; both writes
need `--yes`.

JSON mutations return `action` and `bot_id` (or `bot_ids` for deletion), plus the
resulting setting. Creation also returns `name`; edits return the gateway's `bot`
row or null; deletion returns `refused_ids` and `failed_ids`. Main reads return
`main_agent_id`; info returns the displayed fields, including `voice` with
`id`, `speed`, `language`. Confirmation previews go to stderr in JSON mode.


## In the TUI

Use `/new [name]` to create a bot, `/edit` to edit the current bot, and
`/delete` to remove it. `/bot` opens sidebar, notification, drafting and main-bot
settings. `/main [bot]` shows or sets the main bot; its home row has a dim star.
`/hidden` lists hidden bots: Enter opens one and `u` shows it in the sidebar.
Forms use Tab to move, Ctrl+S to save, and Escape to go back. Every change asks
for confirmation with Cancel focused. Read-only mode permits viewing panels.
