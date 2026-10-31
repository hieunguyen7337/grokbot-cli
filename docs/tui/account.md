# Account panels

Five slash commands show account reads. None of them changes state, so none asks
for confirmation and none is blocked in read-only mode.

- `/analytics` (in a bot session) opens `<bot> analytics`: weekly active users,
  minutes saved (or `Not measured`), the last 14 days with the latest first (day,
  active users, turns and minutes saved), and the top users per window. A bot with
  no analytics yet shows `No analytics yet.` `g` reloads.
- `/egress` opens `Network egress`: Mode (Restricted or Open), the allowed domains
  and the allowed TCP destinations, or that no restriction is set. `g` reloads.
- `/payment` opens `Payment method`: the default payment method label (a card such
  as `Visa ending 4242`, `A saved card` when the vault has no match, a wallet name,
  or `No default payment method.`) and the sentence that the default is changed in
  the Grok Bot app. The vault card id is never shown. `g` reloads.
- `/address` opens `Address lookup`, a query field. Ctrl+S searches. The suggestions
  appear in `Address suggestions`. Enter on one resolves it with the same session
  token and opens `Address` with the formatted address and its parts. An empty or
  failed lookup shows one plain sentence in place of the list.
- `/teach` (in a bot session) shows a notice: teach recording runs in the Grok Bot
  desktop app.

Panels use the shared keys: up and down select, enter opens, esc goes back. Each
panel loads in a worker thread when it opens; nothing polls.

Stays in the Grok Bot app: changing the default payment method, adding a card from
a photo, accepting the terms, and recording a teach session.

Fake-service demo replies are discovered automatically from `DEMO_RPCS`, so
`gbot tui --demo` and the tests show these panels without a live account.
