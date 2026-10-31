# Microsoft Teams

`gbot teams BOT [--json]` reads the bot's Teams setup, tenant, installed teams,
and status sentences. A missing installation is shown as not connected.

All mutations require `--yes`, including in an interactive terminal:

- `--connect [--admin]`: Microsoft consent, followed by an install suggestion.
- `--install [--team ID …] [--no-personal]`: install personally and/or into teams.
- `--reinstall`: update the app without a tenant argument.
- `--uninstall`: remove the app.
- `--add-to-team ID`: install into one additional team.
- `--disconnect TENANT`: revoke the tenant connection and show bots still installed.
- `--account`: list the user's linked Teams identities.
- `--link-account`: link the user's account through Microsoft consent.
- `--unlink-account TENANT`: unlink the user's identity in that tenant.

`--no-browser` prints the handoff URL on stderr for manual opening. Consent and
account linking still wait for status completion. Cancellation exits 130; timeout
exits 1. JSON results stay on stdout.

In a bot session, `/teams` opens `<bot> on Microsoft Teams`. Applicable actions
are `c` connect (normal/admin choice), `i` install (personal toggle and joined-team
toggles), `a` add to a team, `r` reinstall, `x` uninstall, `d` disconnect the
displayed tenant, and `g` reload. Successful consent offers installation.

`/teams-account` works anywhere and lists tenant IDs with linked dates in UTC.
Use `l` to link (also available on an empty list) and `x` to unlink the selected
tenant. Every mutation refuses read-only mode, requires a Cancel-focused
confirmation, and runs transport calls in a thread worker.

Both flows use the [shared browser handoff](handoff.md). Bot consent rereads
installation status with the consent nonce until a consent result, connected
account, or terminal response appears. Account linking waits up to two minutes
for a new `(tenantId, aadObjectId, linkedAtMs)` tuple. Opening a browser alone
does not complete either operation. URLs appear only in the handoff screen.

Fake-service demo replies are discovered automatically from `DEMO_RPCS`; no
Teams account or live backend is needed for tests or demo panels.
