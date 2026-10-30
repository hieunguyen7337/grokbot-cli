# Slash command areas

Add a module under `gbot/tui/slash/` with a `COMMANDS` tuple. Discovery imports
modules automatically and sorts commands by name; names must be unique and use
lowercase letters, digits and hyphens. Choose `home`, `session`, or `any` scope,
and set `needs_bot=True` when a selected bot is required. The handler receives
the context and stripped argument text on the UI thread, and so does a
`PanelAction`'s `run`: put service calls in a thread worker
(`ctx.app.run_worker(fn, thread=True, exit_on_error=False)`) and come back
with `app.call_from_thread`, so a slow gateway never freezes the screen.

```python
from gbot.tui.panels import ListPanel, PanelRow
from gbot.tui.slash import SlashCommand

def show_items(ctx, args):
    ctx.app.push_screen(ListPanel("Items", lambda: [PanelRow("one", "One")]))

COMMANDS = (SlashCommand("items", "Show items", show_items),)
```

Use `ListPanel` for worker-loaded rows, `DetailPanel` for fields and numbered
actions, and `FormPanel` for input. Route every mutation through a confirmed
`PanelAction` or `FormPanel(confirm=...)`; the service call must only run after
the user confirms. Treat remote text as untrusted and use the kit's plain-text
rendering. Never put a secret in a notice or error.

Add offline tests for discovery, scope and bot requirements, menu and palette
dispatch, loading and error states, validation, confirmation and cancellation,
and hostile text. Add snapshots for new layouts as appropriate. Once the area
is implemented and verified, update its status in `docs/parity.json` according
to that file's conventions.
