# Cloud computer and runtime settings

`/sandbox` works on any screen. It opens `Cloud computer` with the run state, the
image tag, whether an image update is available, and the upgrade schedule (state,
local time, time zone, recurring, next run and failure reason). A schedule the
server refuses to show appears as one plain sentence above the actions.

- `r` recreate: choose `Keep data` or `Discard data`. Keep asks
  `Recreate the cloud computer? Your data is kept.`; discard needs the word
  `recreate` typed into the form first, then the same confirmation.
- `f` force recreate: needs the word `recreate` typed into the form, then a
  confirmation. It has no keep-data choice.
- `s` schedule, or reschedule when an upgrade is already set: a form with local
  time (24-hour `HH:MM`), time zone (IANA name, UTC by default) and recurring.
  Time and zone are checked before anything is sent.
- `c` cancel the scheduled upgrade, shown only when one exists; confirmed.
- `g` reload.

A recreate reports whether it started, the reason and the operation ID.

`/runtime` works on any screen. It opens `Settings` with the pinned bots, the
auto-review state, whether onboarding has been seen, the main bot and the email
provider.

- `p` pin or unpin: the current bot when a bot session is open, otherwise a bot
  picked from the roster. Confirmed.
- `a` turn auto-review on or off: confirmed.
- `g` reload.

Pin and auto-review writes stay blocked while the settings read is refused, so a
failed read cannot send defaults over stored instructions.

Every change refuses in read-only mode with the notice `Read-only mode`. Each
confirmation has Cancel focused and names the change. Calls run in a thread
worker, and the panel reloads after a change. Errors show as notices with markup
off, and refusals show the server's message.

Host settings (the desktop computer) and update-now stay in the Grok Bot app.
Those actions are not available from gbot.

Fake-service demo replies are discovered automatically from `DEMO_RPCS`; no
account or live backend is needed for tests or demo panels.
