# Account vault and sign-in methods

These account-level panels work from the home screen or a bot session. They do not select a bot.

`/vault` groups Logins, Cards and Contacts, followed by saved Payment methods. Login rows show the username and first site; card rows show only the brand, last four digits and expiry. Payment authentication and availability states appear as dim text.

- `a`: add a login with Title, Username, Password, comma-separated Sites and Notes.
- `e`: edit the selected login. Enter the password again to update this login. Card editing points to the Grok Bot app.
- `d`: delete the selected vault item after confirmation.

The password input is hidden and clears when submitted. Cancelling confirmation sends nothing; enter the password again before resubmitting. Passwords have no command-line option and are excluded from service models and output. Submission failures use a generic message so a server error cannot echo the submitted password.

`/passkeys` shows each passkey's device type, backup status and last use. `x` confirms revocation. Add passkeys in the Grok Bot app, where the browser ceremony takes place.

The 1Password panel shows a detail screen for each connected vault: account email, vault name, item count, last sync, last error, lifecycle and expiry. Escape reveals the preceding connection. `s` confirms a manual sync; `x` confirms disconnection of that vault. An empty account points to the Grok Bot app to connect 1Password. No provider tokens are retained in these models.

The intended `/1password` entry point is pending a change to the shared slash registry: its current name validator rejects names beginning with a digit. The handler is implemented and tested directly, but is not registered, so the command menu remains usable. The CLI `--onepassword` options are available.

Every mutation refuses read-only mode, defaults confirmation to Cancel and runs the request in a thread worker. Errors are terminal-safe notices with markup disabled.

The CLI equivalent is `gbot vault`, with `--json` available for all lists:

```text
gbot vault
gbot vault --add-login --title Example --username user --site example.com --yes
gbot vault --update-login ID --title Example --username user --yes
gbot vault --delete ID --yes
gbot vault --payment-methods
gbot vault --passkeys
gbot vault --revoke-passkey ID --yes
gbot vault --onepassword
gbot vault --onepassword-sync --yes
gbot vault --onepassword-disconnect ID --yes
```

Login writes accept repeated `--site` options and `--notes`. The CLI reads `Password (hidden): ` on a terminal, or one stdin line when redirected. Every mutation requires `--yes` before any request is sent. Add or edit payment credentials and connect 1Password in the Grok Bot app.
