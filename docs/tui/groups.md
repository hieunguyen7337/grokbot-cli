# Groups and people

Use `/newgroup` on home to enter a name, an optional description and select at
least two bots. Ctrl+S opens a confirmation; Escape cancels without creating a group.
After creation the roster refreshes and the new group opens when available.

Use `/members` with a group selected, on home or in its conversation. Bot members
show `bot`; people show `person`, or `you` for the viewer. Unknown bot ids remain
visible. Up and Down select a row, `a` opens bot selection, and `x` removes the
selected member. Every change requires confirmation. Adding preserves existing
bot order; removing the last bot, yourself, or a person without a user id is refused.
The roster and member panel refresh after each change. Escape returns to the prior screen.

Read-only mode permits viewing members and refuses mutations. Temporal groups
update bot membership through the room RPC; other groups use the gateway.
People are removed through the room RPC. Adding people is available in the app:
its people picker uses team data that the TUI does not have. Canvas bundles also
require the app.
