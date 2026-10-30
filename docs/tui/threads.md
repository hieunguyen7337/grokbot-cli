# Threads and activity

All commands require a selected bot and work on home or in a session.

| Command | Shows | Keys | Desktop name |
|---|---|---|---|
| `/threads` | Pinned, open, then done task threads; newest first per group, with unread previews | Enter opens; p pins/unpins; d confirms Done | Sidebar threads |
| `/background` | Async work, kind, elapsed age and detail | Read only | Background tasks |
| `/subagents` | Type, title and running/done/error/aborted status | Read only | Outline subagent tabs |
| `/outline` | User, thinking duration, tool calls, assistant text and sent messages | / filters | Conversation outline |
| `/suggestions` | Roster suggestion titles and detail | Enter fills composer and dismisses as acted; h hides | Suggestions |
| `/read` | Marks bot and followed threads read | No confirmation | Mark read |
| `/unread` | Marks bot unread | No confirmation | Mark unread |

Lists use Up/Down to select and Escape to go back. Failed loads show the error;
`r` retries. Empty suggestions show `No suggestions`. Done asks for confirmation;
Cancel sends nothing. Pinning reloads the list. Opening an unread thread acknowledges
its unread entry after opening. Read-only mode permits browsing and thread opening,
but refuses mutations with `Read-only mode`.

Task transcripts use `task:<id>` in main chat and `task:<id>:<parent>` in another
session. Suggestions populate a draft without sending it; from home they first
open the bot session. Remote names and text are displayed as plain terminal-safe text.
