# Skill publishing and plugin listings

`gbot listings` is the command-line twin of these two panels. Both work in a bot
session. They send gateway commands whose replies are not fully known, so a reply
that is empty or shaped differently than expected counts as success, and a bot
that the backend hosts may refuse; the refusal is shown as a plain notice with the
server's own sentence, never as a crash.

## `/skill-publish`

Lists the bot's own skills (name and workflow id). Skills managed by Grok Bot are
not listed. A header line above the list names the places a skill can be published
to, or shows the reason publishing is unavailable (a personal account with no team
has no targets). If the targets read is refused, the sentence is the header and the
skills still show.

Keys, shown in the footer only when they apply:

- `p` publish the selected skill. Hidden when there is no target. With one target
  the confirm reads `Publish <skill> to <target>?`; with several you choose a
  target first (enter selects, esc goes back).
- `r` resync the selected skill after confirming `Resync <skill>?`.
- `u` unpublish the selected skill after confirming `Unpublish <skill>?`.
- `g` reload the skills and targets.

With no skills of your own the panel says so in one sentence.

## `/plugin-listing`

Lists the bot's plugins (name and plugin id). The bot's own skills plugin is not listed; publish skills with `/skill-publish`.

- `u` takes the selected plugin's listing down. The panel first asks whether a
  private copy exists, then confirms `Remove the <plugin> listing? A private copy
  stays.` or `Remove the <plugin> listing? No private copy remains.`
- `g` reload.

## Shared behaviour

Every change refuses in read-only mode with the notice `Read-only mode`, asks
through a confirmation naming the bot and the change with Cancel focused, runs in
a thread worker, shows errors as plain text, and reloads the panel afterwards. A
reply that carries an error is shown as a warning; otherwise the reply's status
and message (or `Done`) appear as a notice.

What stays in the Grok Bot app: reviewing a listing, choosing a visibility other
than a team, and publishing a whole bot or a template.

Fake-service demo replies are discovered automatically from `DEMO_COMMANDS`; no
account or live backend is needed for tests or demo panels.
