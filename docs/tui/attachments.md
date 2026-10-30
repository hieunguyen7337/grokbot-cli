# Attachments

In a session, use `/attach <path>` or paste/drop a file path into the composer.
Quotes, `~`, and `file://` paths are accepted. `/attach` alone opens a Path form;
Enter or Ctrl+S saves the form. Upload progress and staged names appear above
the composer. `/detach <name>` removes matching staged files; `/detach` removes all.

Enter sends text and staged files together, including files with no text.
Wait for uploads to finish before sending. Failed sends keep files for retry;
the retry nonce changes when text or attachment paths change.

`/files` lists files from loaded messages, newest first. PgUp in the session loads
earlier messages. Up/Down selects a file; Enter previews text or binary details.
Truncated text is marked `(truncated)`. Press S to confirm saving under Downloads;
downloads use safe filenames and avoid overwriting existing files. Press O in the
list to confirm opening an HTTPS link. Other URL schemes refuse.
Escape returns from panels. Read-only mode permits browsing and previews, while
uploads, sends and saves refuse; pasted paths remain ordinary composer text.
