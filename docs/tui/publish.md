# Publishing

`/publish` works in a bot session and opens `Publish <bot>`. It shows the bot's
marketplace state (published, unpublished, or unknown when the roster does not
say), the last result sentence, then the bot's template (name, share ID,
published, active version, visibility) and a sentence for the account's template
export policy.

Keys appear only when they apply:

- `p` list the bot in the marketplace (`List <bot> in the Grok Bot marketplace?`);
  shown unless the bot is already listed.
- `u` take it off the marketplace; shown unless the bot is already unlisted.
- `a` publish a template version: type a number (the active version is
  prefilled), then confirm `Publish version <n> of <template>?`.
- `v` template visibility: choose public or team, then confirm. Public is not
  offered when the policy allows teams only.
- `d` delete the template: type the template name, then confirm.
- `g` reload.

When the policy is off for the account, the template actions are hidden and the
sentence says why. A bot without a template shows one sentence saying so.

Every change refuses in read-only mode with `Read-only mode`, asks through a
confirmation with Cancel focused, runs in a worker thread and reloads the panel.
A server refusal (sharing disabled, public sharing disabled, template deleted, or
a bot that must be shared first) is shown as its readable message, not an error
trace. Creating a template, skills and plugin listings stay in the Grok Bot app.
