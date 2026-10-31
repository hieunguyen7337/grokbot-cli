# Connectors

`/connectors` works on the home screen and in sessions. Enter opens a connector.
Rows show its account, status sentence and tool count. `r` reloads.
`A` asks: `Forget every "always allow" answer for connector tools?`

The detail panel shows Status, Account, Transport, Tools, Group chats and
Instructions. Keys:

- `t`: tools; space enables or disables the selected tool, `p` chooses Auto
  review, Always allow, Needs approval or Blocked, `d` edits read and write defaults.
- `i`: multiline instructions; Ctrl+S asks `Save instructions for <name>?`
- `s`: asks `Sign in to <name>? Your browser opens.`, then opens the shared
  [browser handoff](handoff.md). Connected accounts are reauthenticated.
- `n`: rename the current account; `x`: remove it. Both require confirmation.
- `X`: remove the connector for every bot; hidden for team connectors.
- `g`: allow or stop allowing the connector in group chats.
- `r`: reload; Escape: back or cancel.

Account actions are hidden without an account. Every mutation refuses in
read-only mode. Confirmations focus Cancel; forms use Ctrl+S to review before
saving. Service calls run in thread workers; error notices display plain text.

The handoff completes on a matching `mcp-auth` event or a change from the
pre-sign-in status to a state without a pending or required sign-in. Events for
another server do not complete it. Provider cancellation displays its failure
detail. Escape cancels waiting without changing connector settings. A timeout
explains: `If the browser asked to open the Grok Bot app, finish there; gbot cannot receive that callback.`
