# Reactions, feedback, threads and search

In a session, `/react` picks a displayed entry and a reaction; `/react <emoji>`
toggles a reaction on the newest bot message. `/feedback [up|down]` gives
feedback, with a form available when no vote is supplied. `/thread [entry-id]`
starts a thread after confirmation; without an ID it offers displayed entries.
These actions are unavailable in read-only mode.

`/search <query>` searches messages across bots; `/media [query]` searches
media. Select a result to open its bot. `/find <query>` searches the current
conversation and scrolls to a loaded result. Older results require loading
history with Page Up.

`/find` has no twin in the app: the gateway declares `searchConversation`, but the app's search overlay only
searches messages and media across bots.

The notice after `/react` says "Removed reaction" when the entry already carries your reaction with that emoji.
gbot takes a reaction whose `by` is `user` to be yours; the protocol notes do not settle this, so the notice can be
wrong while the toggle itself still works.
