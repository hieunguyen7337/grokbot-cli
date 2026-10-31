# Automations

`/automations` opens the selected bot's scheduled and triggered prompts. From
home it opens the account list. Press `b` to toggle between the selected bot
and all bots, `r` to reload, `n` to create, and Enter to open a record.
On an account list, creation uses the selected row's bot; select a bot first
when the account list is empty.

Rows show state, trigger, relative next run, and the bot name in account view.
Details show Trigger, State, Next run, Last run, Created, Provenance, prompt,
and the last five runs. Server permissions determine which actions appear:
`e` edits, `t` toggles, `x` deletes, `R` runs now, and `r` reloads.

The create/edit form has Name, multiline Prompt and Schedule (cron only).
Save with Ctrl+S. Every write opens a confirmation with Cancel focused;
Escape cancels. Read-only mode refuses every write. A manual run displays
its status once a new run ID appears, or reports a timeout after 120 seconds.
Leaving the detail panel cancels the wait. Automation replacement and
invalidation events refetch the affected bot's records.

Schedules accept five numeric cron fields, lists, ranges, wildcard and positive
steps, the standard hourly/daily/weekly/monthly/yearly macros, and `@every`
with positive ms/s/m/h/d durations. Optional `TZ=Zone` or `CRON_TZ=Zone`
uses a zoneinfo timezone. Other trigger types can be viewed and their name
and prompt edited; change their trigger in the Grok Bot app.

Timezone prefixes require an IANA timezone database available to Python's
`zoneinfo`. Windows installations need the `tzdata` package; this unit adds
no dependencies. Schedules without a timezone prefix work without that data.
