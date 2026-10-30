# Grok Bot 0.77.0 parity inventory

Inventory: 173 gateway commands and 401 unique backend RPCs (574 entries). GrokBotService has 401 methods; all 55 SandBoxService methods are shared and deduplicated by name, with identical request fields.

`parity.json` is the machine-checkable checklist. It contains every extracted gateway command and the union of GrokBotService and SandBoxService RPCs, including excluded operations. Shared RPC names appear once; request field names use JSON lowerCamelCase. Arguments list top-level accepted fields, including optional fields; an empty list means no request fields. Nested object schemas, response types and requiredness are not encoded.

Sources: the read-only 0.77.0 coordinator command validators, electron-main protocol request descriptors, and invocation evidence in electron-main and renderer assets; repository `gbot/protocol.py` and `docs/protocol-0.72.md`. No live services were queried. Generated declarations alone do not count as desktop invocations. Static absence is not proof against dynamically computed calls; exclusions should be revisited when the app changes.

<<<<<<< HEAD
`done` tracks the current USED_COMMANDS / USED_RPCS sets; M1 is the existing baseline and later milestones retain their feature assignment. Other milestones follow feature scope even for excluded entries. A milestone is a planning bucket, not a promise to implement declined operations. Counts describe protocol entries, so gateway and backend variants of a feature are both counted.

| Area | Planned | Done | Handoff | Declined | Milestone |
|---|---:|---:|---:|---:|---|
| roster | 2 | 3 | 0 | 2 | M1, M3 |
| conversation | 7 | 22 | 0 | 13 | M1, M2 |
| cards | 0 | 14 | 3 | 10 | M1, M2 |
| rooms | 1 | 5 | 2 | 4 | M2, M3 |
| tasks | 0 | 13 | 0 | 6 | M2 |
| bots | 3 | 14 | 0 | 3 | M3 |
| avatar-voice | 0 | 5 | 1 | 1 | M3 |
| templates | 2 | 8 | 0 | 4 | M3 |
| account-billing | 4 | 0 | 2 | 2 | M5 |
| automations | 22 | 0 | 0 | 0 | M4 |
| channels | 23 | 0 | 1 | 16 | M4 |
| computer | 4 | 1 | 0 | 8 | M1, M4 |
| connectors | 16 | 4 | 4 | 6 | M1, M4 |
| email | 2 | 0 | 0 | 6 | M4 |
| internal | 1 | 0 | 0 | 123 | M1, M5 |
| memory-files | 11 | 0 | 0 | 0 | M5 |
| plugins-skills | 12 | 0 | 0 | 2 | M4 |
| publishing | 26 | 0 | 0 | 6 | M5 |
| search | 1 | 3 | 0 | 1 | M2 |
| secrets-vault | 22 | 1 | 9 | 10 | M1, M4 |
| settings | 15 | 1 | 2 | 1 | M1, M5 |
| sharing | 15 | 0 | 0 | 3 | M5 |
| teams | 7 | 0 | 0 | 14 | M5 |
| voice-meetings | 0 | 0 | 0 | 19 | M5 |
`done` is exactly the current USED_COMMANDS / USED_RPCS sets, with implemented feature entries assigned to their milestone (M1 is the existing baseline). Other milestones follow feature scope even for excluded entries. A milestone is a planning bucket, not a promise to implement declined operations. Counts describe protocol entries, so gateway and backend variants of a feature are both counted.

| Area | Planned | Done | Handoff | Declined | Milestone |
|---|---:|---:|---:|---:|---|
| roster | 2 | 3 | 0 | 2 | M1, M3 |
| conversation | 7 | 15 | 0 | 20 | M1, M2 |
| cards | 0 | 13 | 3 | 11 | M1, M2 |
| rooms | 1 | 5 | 2 | 4 | M2, M3 |
| tasks | 0 | 7 | 0 | 12 | M2 |
| bots | 7 | 12 | 0 | 3 | M3 |
| avatar-voice | 5 | 0 | 1 | 1 | M3 |
| templates | 7 | 0 | 0 | 4 | M3 |
>>>>>>> tui-m3a
| connectors | 16 | 4 | 4 | 6 | M1, M4 |
| plugins-skills | 12 | 0 | 0 | 2 | M4 |
| automations | 22 | 0 | 0 | 0 | M4 |
| channels | 23 | 0 | 1 | 16 | M4 |
| email | 2 | 0 | 0 | 6 | M4 |
| secrets-vault | 22 | 1 | 9 | 10 | M1, M4 |
| computer | 4 | 1 | 0 | 8 | M1, M4 |
| sharing | 15 | 0 | 0 | 3 | M5 |
| publishing | 26 | 0 | 0 | 6 | M5 |
| teams | 7 | 0 | 0 | 14 | M5 |
| memory-files | 11 | 0 | 0 | 0 | M5 |
| settings | 15 | 1 | 2 | 1 | M1, M5 |
| account-billing | 4 | 0 | 2 | 2 | M5 |
| voice-meetings | 0 | 0 | 0 | 19 | M5 |
| search | 1 | 3 | 0 | 1 | M2 |
| internal | 1 | 0 | 0 | 123 | M1, M5 |

**roster.** List and open bots, expose live state, and manage sidebar visibility and update notifications.

**conversation.** Read transcript pages, tails and threads; send messages with attachments; interrupt, start fresh or roll back; react, provide feedback and manage unread state.

**cards.** Answer approvals, permissions, widgets, forms, secrets and message drafts; inspect and dismiss activity trays. Payment approval and embedded app forms may require an app handoff.

**rooms.** Create group conversations and edit bot and human membership; read shared room documents and canvases. Agent turn delivery is infrastructure rather than a terminal action.

**tasks.** Inspect todos, agent tasks, subagents and background work; mark work done or read, pin tasks and dismiss suggestions.

**bots.** Create, edit, duplicate and delete bots, import templates, choose the main bot, and control drafting and other bot behavior.

**avatar-voice.** Set or generate bot avatars and choose voice profiles, speed and language. Audible voice preview needs the app.

**templates.** Browse templates and public marketplace listings, inspect versions and import details, and check export policy. Publishing and visibility changes are tracked separately.

**connectors.** Browse and install MCP connectors, authenticate accounts, manage tools and instructions, and configure permissions. Browser OAuth can be launched from the terminal; embedded MCP HTML apps require a browser.

**plugins-skills.** Browse and synchronize skills, manage bot plugin selections, variables and delegated credentials, and add, edit or remove bot skills.

**automations.** Inspect and manage scheduled automations, workflows and routines, import workflow text or URLs, run work immediately and use automation webhooks.

**channels.** Manage bot channels, listener integrations, messaging links, Slack and Microsoft Teams installations and account links. Native messaging consent needs the app.

**email.** Create and list bot email inboxes. Other declared inbox and thread operations remain excluded when the desktop has no invocation; sending draft replies is tracked under cards.

**secrets-vault.** Manage bot secrets, password-manager connections, vault credentials and saved forms. Passkey ceremonies and payment card entry require browser or app UI.

**computer.** Inspect and update the bot computer and return control after a handoff. Opening the live desktop requires the app; machine registration and response relays are infrastructure.

**sharing.** Manage bot visibility, in-place sharing, managers, access rules and invitation links, including previewing, accepting and revoking invitations.

**publishing.** Publish template versions and skills, manage plugin listings, and inspect, publish, update or unpublish cloud-agent apps and their application secrets.

**teams.** Inspect team bots and context, share memories with a team, handle review items and configure team link previews. Staff administration remains excluded.

**memory-files.** Browse library documents and pins, inspect bot memories, and upload, list or delete bot and user-store files.

**settings.** Manage host and runtime preferences, upgrade scheduling, egress policy, bot analytics and teach recording. Desktop demonstration capture needs the app.

**account-billing.** Inspect terms and payment-method information. Payment entry and card scanning require browser or app UI.

**voice-meetings.** The app supports voice sessions, call control, meeting records and audio transcription. These operations are explicitly declined for the terminal audio scope.

**search.** Search bots, conversation content and media, and inspect global-search availability. Location cards can request a places-area search.

**internal.** Retain service administration, store transport, migration, presence and window bookkeeping in the inventory for completeness; these do not create terminal UI requirements.

Notable UI-only features outside the gateway/RPC inventory:

- Local light/dark/system theme selection and bot colors in chat.
- Local zoom, spell-check and hardware-acceleration preferences.
- Keyboard shortcuts, composer text editing and local window presentation.
