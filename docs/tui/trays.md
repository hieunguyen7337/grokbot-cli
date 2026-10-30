# Alerts

`/trays` opens Alerts from home or a session, with no selected bot required.
Home lists every gateway tray with its bot name; a session lists only its bot's
trays. Rows show the title, first detail line, age and repeated occurrence count.
Newest alerts appear first. Empty lists show `No alerts`.

| Key | Action |
|---|---|
| `f` | Confirm a fresh conversation using the advertised session, then dismiss |
| `b` | Confirm rolling back the advertised session, then dismiss |
| `o` | Confirm opening an HTTPS link in the browser |
| `$` | Show the app handoff for buying credits |
| `a` | Show the app handoff for a dashboard action |
| `m` | Show the app handoff for switching models |
| `d` | Dismiss the selected alert immediately |
| `c` | Confirm clearing all alerts, including alerts belonging to other bots |
| Escape | Return to the previous screen |

Actions require a matching advertised tray action, except dismiss and clear.
Rollback restores the last user message into the composer when the session
underneath Alerts matches both bot and session. Otherwise the notice asks the
user to open the bot to edit the message. The optional `fromSeq` is retained as
metadata and is never sent to the rollback command.

Read-only mode blocks fresh, rollback, dismiss and clear, including when enabled
while a confirmation is open. Browser links and app handoff notices remain
available. Only HTTPS links open; their URLs appear as plain text in the
confirmation. Remote titles, details, names and notices use terminal-safe text.

The home summary shows the total alert count in the warning colour. Each session
shows its newest alert above the composer, with a count of additional alerts and
a `/trays` hint. Loading happens after the first roster and whenever a `tray`
event arrives. Failed reads preserve the old list quietly for compatibility with
gateways that do not support trays. Successful mutations refresh both the list
and the indicators. Demo mode starts with no trays.

The gateway commands are `getTrays` and `clearTrays` without arguments, and
`dismissTray` with `{id}`. Tests use fake services and a patched browser only.
