# Team bots

These screens need a team account. On a personal account the server refuses
each call with a readable message: the TUI shows it as a plain notice, or in
place of an empty list, and nothing else changes. A combined view such as
`/team` shows a refused part as its sentence and keeps the rest.

`/team` (in a bot session) opens `<bot> in your team`. The first row is the
shared summary: its prose, the memory count, and `stale` when the summary is
out of date. Learned memories follow, each with the date learned. Pending
review items come last, labelled by kind and action (for example `memory write`
or `skill add`) with the change's summary.

Keys appear only when they apply:

- `a` approve and `r` reject: only when a pending item is selected. They ask
  `Approve this change to <bot>?` or `Reject this change to <bot>?`, with Cancel
  focused.
- `h` switches between pending items and the approved history (the last 20).
- `m` opens the memories you can share with the team.
- `g` reloads.

In the memories panel, `space` marks or unmarks a memory. `p` appears once one
is marked and asks `Share <n> memories of <bot> with the team?`. The result
sentence reports how many were created, how many were already in the team, and
how many were kept private. Marks clear and both panels reload.

`/team-bots` (anywhere) lists the team's bots with user turns, teammate turns
and the date of the last turn. An empty list shows `No team bots.`

`/team-link-preview [TEAM_ID]` (anywhere) shows whether link previews are on for
a team. With no argument it asks for the team ID first. This is a team-wide
switch, not a bot's public card. `t` turns it on or off after
`Turn link previews <on|off> for team <id>?`. `g` reloads.

Every change refuses in read-only mode with `Read-only mode`, asks through a
confirmation with Cancel focused, and runs its call in a thread worker. Panels
reload after a change; errors appear as notices.

Creating or sharing a team bot, managing its access and visibility, and adding
review items stay in the Grok Bot app.
