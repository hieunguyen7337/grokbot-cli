# Plugins and connector catalog

`/catalog` opens the Connector catalog from any screen. Entries are grouped by
category and show publisher and connector count. Use up/down to select, `/` to
focus the filter, Enter to read the description, publisher, connectors and setup
fields, and Escape to go back. Fields identify required and secret inputs.

With a bot selected, `a` on a catalog entry or its detail asks
`Add <plugin> to <bot>?`. Cancel is focused. Confirming adds the catalog plugin
while preserving every existing plugin, including hidden bot-skills entries.
Plugins without a positive numeric catalog ID must be added in the Grok Bot app.
An added plugin that needs setup opens its settings form.

`/plugins` works in a bot session. The list shows plugin names, skills, servers
and `needs setup` when settings are unconfigured. Enter shows description,
skills, servers, install mode and credential source. `a` opens the catalog,
`x` asks `Remove <plugin> from <bot>?`, and `v` opens settings.

Settings use the plugin's JSON schema, catalog fields, or variable names in that
order. Secret inputs are password fields; stored values are never displayed.
Every input starts blank. Tab advances fields and Ctrl+S asks
`Save settings for <plugin>?`, with Cancel focused. Only filled inputs are sent
and merge into stored settings. Inputs clear after save or cancellation.

All mutations refuse with `Read-only mode` in read-only sessions. Calls run in
thread workers. Errors appear as plain terminal-safe notices, and variable-save
errors never include submitted values.
