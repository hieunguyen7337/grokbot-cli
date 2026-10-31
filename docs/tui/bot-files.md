# Bot files and library

`/bot-files` opens `<bot> files` for the bot in the current session. It lists the
bot's files (name, size, updated, every page of the list), then the user-store
files marked `user store`, then the total size. A part the server refuses is
shown as one plain sentence; an empty bot says it has no files.

Keys, shown in the footer only when they apply:

- `u` upload: asks for a file path, then confirms `Upload <file> (<size>) to <bot>?`.
  Hidden when your account cannot edit the bot's files.
- `x` delete the selected file: confirms `Delete <file> from <bot>?`. User-store rows
  are deleted by path through the user-store call.
- `g` reload.

`/library` opens the bot's library: documents (title or external id, provider,
kind, last touched, a `pinned` mark), then pins that are not documents.

- `p` pin or unpin the selected document, after a confirmation.
- `o` open the document's link in the browser (https links only).
- `g` reload.

Every change refuses in read-only mode with `Read-only mode`, asks through a
confirmation with Cancel focused that names the bot and the change, runs its calls
in a thread worker, and reloads the panel afterwards. Errors are shown as plain
text; storage addresses, upload tokens and upload headers never appear.

Merging pin lists between bots, editing documents and creating pins for pages or
media stay in the Grok Bot app (the CLI offers `gbot library --merge-pins`).
