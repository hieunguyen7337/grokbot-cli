# Skills and the skill catalog

Open `/skills` in a bot session. The list groups unscheduled editable skills under
Yours, scheduled skills under Scheduled, and other skills under Managed. Enter
shows source, schedule, last and next run timestamps (milliseconds), description
and the instruction body as plain text.

- `n`: new skill; `e`: edit the selected editable skill.
- `x`: delete the selected editable skill.
- `R`: run the selected scheduled skill now, including a paused schedule.
- `i`: import from an HTTP/HTTPS URL or a local UTF-8 Markdown file path.
- `c`: open `/skill-catalog`.
- Up/down select; Enter opens; Escape returns.

New and edit forms contain Name, Description, multiline Body and Schedule.
The first three fields are required. Leave Schedule blank to remove a schedule;
otherwise its trimmed text goes to the server for validation. Ctrl+S opens a
confirmation with Cancel focused. Managed, template and plugin skills cannot be
edited or deleted; copy their text into a new skill to make your own.

`/skill-catalog` works on the home screen or in a session. Type in its filter to
search names, publishers and descriptions. It shows at most 200 matches and a dim
count of remaining matches. Arrow keys leave the filter to select entries; `/`
returns to the filter. Enter opens the description and publisher. With a bot
selected, `a` adds the entry after confirmation (also available in its detail).
URL installs and content installs use the corresponding workflow import command.
Unknown install kinds direct you to the Grok Bot app.

Every mutation requires confirmation and is refused in read-only mode. Network
work runs in thread workers. Skills refetch on matching `workflows` and
`bot-skills` events. Import notices show the workflow counts before and after;
they make no claims about unknown import result fields.
