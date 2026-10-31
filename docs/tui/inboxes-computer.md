# Email inboxes and desktop computers

`gbot inboxes [--json]` lists account addresses and their assignment status.
`gbot inboxes --create USERNAME --yes [--json]` creates an address. Usernames
are trimmed and lowercased; empty names, whitespace and `@` are refused.

`gbot computer BOT [--json]` reports state, phase, host version, update flags,
disk pressure and any pending hand-off instruction. Choose one action:
`--wake --yes`, `--update --yes`, `--hand-back --yes`, or `--open`.
Hand-back requires a pending request. Open requires a live view and opens it
in the browser, reporting only `Opened the live view.` Access URLs and window
URLs are excluded from text, JSON and status representations.

`/inboxes` works on any screen. The Email inboxes panel lists assigned and
unassigned addresses, or No inboxes. Press `n` for a Username form; its hint
previews the address using the first inbox's domain, falling back to
mail.grokbot.com. Submit with `ctrl+s`, then confirm creation. `r` reloads.

`/computer` works in a bot session. The panel shows State, Phase, Host version,
Updates, Disk pressure and a pending hand-off instruction. Keys:

- `w`: wake, after confirmation.
- `u`: update, available when host or image updates exist; confirmation warns
  that the computer restarts.
- `h`: hand back, available with a pending request, after confirmation.
- `o`: open the live view, available with a VNC URL; no confirmation.
- `r`: reload. A BoxChanged event for this bot also reloads.
- `esc`: return to the previous screen.

Every mutation uses a thread worker, refuses read-only mode and opens a
confirmation with Cancel focused. Browser viewing remains available in
read-only mode. Errors are terminal-sanitized plain-text notices.

Computer phases are pulling when pull is present, running for the running
state, sleeping for hibernated and off otherwise. A null reply means absent.
Wake and update use ensureForeverBox and updateForeverBox. Hand-back uses
EndGrokBotBoxHandoff for temporal bots, with BUTTON=1, VIEWER_CLOSED=2 and
DISMISSED=3; box bots use handBackForeverBox with string triggers.
This unit does not implement email thread browsing or RecreateSandBox.

Demo replies are discovered by load_fake alongside other service modules.
All coverage uses recording fakes and patched browser opening.
