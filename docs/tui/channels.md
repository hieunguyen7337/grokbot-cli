# Slack, texting and listeners

`gbot channels slack BOT [--json]` reads the bot's Slack installation. Mutations
are `--connect`, `--install [--workspace ID]`, `--reinstall` and `--uninstall`.
Every mutation requires `--yes`, including in an interactive terminal.

`gbot channels sms [--json]` shows texting availability, the line number and
linked phones. `--link --yes` issues a code; send the displayed link message from
your phone, using the SMS URI if helpful. `--unlink HANDLE --yes` removes a phone.
Texting availability is controlled by the server; its unavailability message is
shown without treating it as a transport failure.

`gbot channels listeners [--json]` lists the six event-source platforms, connection
state and automation usage. `--connect PLATFORM --yes` connects a platform.
With `--json`, the object holds `integrations`, one row per platform with `platform`,
`is_connected`, `needed_by_count`, `state`, `detail`, `granted_repos` and `scope_issues`,
plus `message`.

Slack and listener browser steps use the shared handoff helper. `--no-browser`
prints the URL on stderr and waits for you to open it manually. JSON stays on
stdout. Cancellation exits with 130. Slack completes when status, workspaces
(including manager authorization timestamps), or pending reinstall approval
changes. Listeners complete when that platform becomes connected. Listener timeout
explains that a browser callback may need to finish in the Grok Bot app; gbot does
not implement its desktop callback. URLs appear in the handoff only and are not
included in Slack status output or logs.

In the TUI, `/slack` opens **<bot> on Slack** within a bot session. It shows status,
workspace, workspace count and installation flags as sentences. Available actions
depend on state: `c` connect, `i` install (choose a workspace if several exist),
`r` reinstall, `x` uninstall, and `g` reload. Unsupported or unknown states offer
reload. Connect, install and reinstall confirm that the browser will open;
uninstall confirms the bot and workspace being removed.

`/sms` opens **Text your bots** from any screen. Available texting shows the line,
phones, link code, expiry, message and SMS URI as text. `l` issues a code, `x`
chooses a linked phone to unlink, and `g` reloads status and phones. Unavailable
texting shows the server's sentence without actions. There is no QR or browser
wait; send from the phone and reload with `g`.

`/listeners` opens **Listeners** from any screen. Each platform shows state,
connection, automation count, detail and scope issues. Use arrows to select,
`c` to connect and `g` to reload. Browser handoffs support `o` reopen, `c` copy,
and Escape cancel; see [handoff.md](handoff.md).

Every TUI mutation confirms with Cancel focused, refuses read-only mode, runs
transport work in a thread, and reports sanitized errors without Rich markup.
Cancelling a Slack handoff preserves the displayed state; `g` can read it again.
Microsoft Teams is not managed here. Use `/teams` in a bot session or `gbot teams BOT`;
see [teams.md](teams.md). Native Messages grants and desktop GitHub callback operations
are not implemented here.
