# Secrets

`gbot secrets BOT [--json]` lists secret names, descriptions and update timestamps.
`gbot secrets --computer [--json]` lists computer secret names and application status.

Mutations require `--yes`:

- `gbot secrets BOT --set NAME [--description TEXT] --yes` adds or replaces a secret.
  The value is read with a guarded hidden prompt, or one line from non-terminal stdin.
- `gbot secrets BOT --delete NAME --yes` removes a secret.
- `gbot secrets BOT --copy-from-computer NAME [NAME ...] --yes` prints each copy outcome.

There is no command-line value option. Names are trimmed and uppercased; reserved
environment names and prefixes are refused. Values are trimmed, nonempty and limited
to 4,096 UTF-8 bytes. Values are sent only in the put request and are never displayed.

In a bot session, `/secrets` lists metadata with a computer status footer. Press `a`
to add or replace, `d` to delete the selected name, or `c` to select computer names
with toggles. Use Tab between fields, Ctrl+S to validate and review, and Escape to
go back. Confirmations focus Cancel. The password input clears on submission or
cancellation. Read-only mode refuses all mutations.

Bot operations resolve the gateway bot ID to its backend identity. Missing identities
require the desktop app; writes require ownership. Computer copying reports gateway
outcomes. Replacing the computer's entire secret map (`setBoxSecrets`) stays planned.
