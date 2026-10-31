# Cloud agents and published apps

`/apps` works anywhere and opens `Published apps`: one row per app with its slug,
apex and visibility. When cloud-agent apps are off for the account, the panel
shows `Cloud-agent apps are off for this account.` instead of a list; a refusal
from the server is shown as its own sentence. A note line says the app gate
opens in the Grok Bot app.

Keys, shown only when they apply:

- `e` edit the selected app: a form with slug, apex, visibility (private, team or
  public) and two toggles, mute redeploy prompts and require confirmation for
  updates. Saving asks `Update app <slug> as <visibility>?`.
- `u` unpublish the selected app after `Unpublish <slug>?`.
- `g` reload.

In a bot session, `/cloud-agent BC_ID` opens `Cloud agent <bc_id>`: the agent's
status, title, branch, repository, creation time and file and artifact counts,
the last 20 messages of its conversation and its publish proposals. A missing
agent shows `No cloud agent with that id.`; a refused part shows the server's
sentence while the other parts still load. Up and down select a proposal.

Keys, shown only when they apply:

- `s` stop the cloud agent after `Stop cloud agent <bc_id>?`.
- `c` confirm the selected proposal after `Publish <slug> as <visibility>?`; the
  session's bot is sent as the proposal's agent.
- `d` dismiss the selected proposal after a confirmation naming its slug.
- `k` app secrets: enter the app's project directory, then a list of the secret
  names there opens (values are never shown). `n` sets one through a masked
  input and asks `Save secret <name>?`; after saving, gbot tells the bot which
  names were saved and which were refused, and shows the refusals as a notice.
  `g` reloads the names.
- `g` reload.

Every change refuses read-only mode with `Read-only mode`, asks with Cancel
focused and names the bot, runs in a thread worker and reloads the panel after
the write. Server refusals appear as plain notices.

What stays in the Grok Bot app: the app gate, which the app opens in its own web
view with a short-lived ticket (gbot never requests that ticket), and app links,
which gbot never shows. Reply fields for these commands are not fully known, so
gbot reads them defensively and ignores fields it does not recognise.
