# Grok Bot 0.72.1: protocol used by gbot

This is an unofficial interoperability note, written in our own words.
It describes static evidence for 0.72.1 and this repository's implementation;
it is not a supported service contract or proof of live service behavior.

## Session and transport

Sign-in uses OAuth PKCE. The authenticated backend `EnsureSandBox` call supplies
per-sandbox gateway connection details: a gateway URL and token. The client then
sends authenticated `POST /api/<command>` requests with a JSON object body.
Commands with no arguments use an empty object on the wire. Replies are JSON
values, not necessarily objects: arrays and null are valid command results.

`GET /events?channels=` subscribes to SSE; channel names are comma-separated.
A decoded frame has the shape `{"event":"event-name","data":{"channel":"channel-name","payload":{}}}`.
For transcript updates, payloads identify the agent, update type and entry;
`appended` carries a new entry. The CLI follows transcript events rather than
repeatedly requesting the tail. Reply waiting subscribes before sending a prompt.
Backend authentication refresh is retried once; gateway failures can trigger one
fresh sandbox connection. A prompt keeps its clientNonce across that retry.

## Used command contracts

Only the 17 names in `gbot/protocol.py` USED_COMMANDS are covered here.
Field names below are wire interface names. `?` means optional; omission and null
are distinct. IDs and textual values are strings; limits, sequence numbers and
timestamps are numbers. Reply descriptions give the shape, with selected fields
rather than every nested property of the app's schemas.

### Roster, transcript and prompt

| Command | Argument fields | Reply shape |
|---|---|---|
| listAgents | None | Array of bot summaries, including id, name and pending/running state |
| getAgentTranscriptTail | id, limit; beforeSeq?, sessionId?, unreadBoundaryAt? | Object with entries array and optional nextBeforeSeq, ordering and unread metadata |
| sendPrompt | agentId, prompt; optional fields below | Object with accepted? (boolean or null), or null |

The CLI sends agentId, prompt and clientNonce for sendPrompt. The 0.72.1
validator additionally accepts these optional fields:

- attachmentNames, attachmentPaths: arrays of strings.
- automationWriteProvenance: template_import, untrusted or null.
- clientNonce, machineId, mcpConfigJson, replyToId, richText, sessionId, taskId,
  traceparent: strings.
- composedAtMs, enterEpochMs, firstSentAtMs: numbers.
- directAddressedAcceptance: true.
- initiator: card_action, plugin_setup, teach_recording, template_import,
  template_share, user or null.
- isFork, onePasswordAppInstalled: boolean or null.
- sendSource: action_button_dictation, app_intent, chat, push, unknown or null.
- source: desktop, mobile or null.

The gateway wrapper normalizes null send results to an empty object; acceptance
is not a completed bot answer. Answers arrive through transcript updates.
Transcript entries discriminate on kind; pending cards are send-message entries
whose nested message.type determines the interaction.

### Computer and host state

| Command | Argument fields | Reply shape |
|---|---|---|
| getForeverBoxStatus | id | Object with agentId, state, vncUrl (string or null), optional host/image/update/window information; or null |
| getHostStatus | includeManagedCapabilities? (boolean or null) | Object with hostVersion, latestHostVersion (string or null), hostUpdateAvailable (boolean or null), isBusy (boolean), capabilities? (string array) |
| getBoxSecretsStatus | None | Object with isApplied (boolean), keys (string array), lastAppliedAtMs (number or null), cardKeys? (string array) |

The CLI displays secret application status, not secret values.

### Answer commands

Every command below takes agentId and entryId, plus optional sessionId.
These shared fields identify the exact pending transcript card and session.

| Command | Additional argument fields | Reply shape |
|---|---|---|
| resolveAutoReviewApproval | requestId; resolution: always, approved or denied; approvalPlatform? (android, desktop, ios or null); approvedCommand? (string) | null |
| resolveLocalToolPermission | requestId; resolution: allow-once, always, deny or never | null |
| respondToWidget | value (string) | Object with accepted (boolean), or null |
| dismissWidget | None | Object with accepted (boolean) |
| submitSecret | value (string) | null |
| submitUserForm | values (object); platform? (android, desktop, ios or null); saveToVault? (boolean or null) | null |
| dismissUserForm | mode: dismissed or escalated; platform? (android, desktop, ios or null) | null |

The CLI uses mode dismissed and saveToVault false. Accepted schema values do not
establish that every mode has a corresponding desktop UI action.

### Connector listing

| Command | Argument fields | Reply shape |
|---|---|---|
| getMcpState | None | Object with servers array: identifiers, name, transport, status, toolCount and optional account/policy details |
| listBoxMcpServers | serverIdentifiers (string array) | Object with servers array: serverIdentifier, status, toolCount, optional statusDetail and pendingSignIn |
| getEffectiveMcpPlugins | None | Array of plugin objects: pluginId, name, displayName, installMode, isEnabled; optional mcpServerNames and team/configuration metadata |
| listMcpServerTools | serverId (string) | Array of tools: name, isDisabled; optional description, title, permissions and isReadOnly |

The CLI requests listBoxMcpServers with an empty identifier array and merges
state, computer rows and plugin enablement by identifiers/names. Tool listing
adds only tool names to CLI output and isolates individual server errors.
These calls inspect connections; they do not perform OAuth, grant access or link
accounts. The note makes no claim about live connector catalog availability.

## Pending items and their answers

The roster exposes awaitingUserResponse and optional awaitingSessionIds.
Discovery reads the selected bot, or waiting roster bots, then their default and
awaiting-session transcript tails. It follows nextBeforeSeq until exhausted and
deduplicates by bot and entry ID. An explicit answer re-fetches all bots' pending
cards even if their roster waiting flag has not yet updated.

| message.type | Pending indicator | gbot action / wire answer |
|---|---|---|
| auto-review-approval | approval.status is pending | approve/deny → resolveAutoReviewApproval |
| meeting-join-consent | approval.status is pending | approve/deny → resolveAutoReviewApproval |
| local-tool-permission | ask.status is pending | approve/deny → resolveLocalToolPermission |
| widget | No respondedValue, widgetDismissed or widgetSkipped | respond → respondToWidget; dismiss → dismissWidget |
| secret-request | secretProvided is not true | secret → submitSecret, except channel credentials |
| user-form | No formResolution | respond → submitUserForm; dismiss → dismissUserForm, except restricted forms |
| virtual-card-approval, publish-approval, cookie-origin-approval | approval.status is pending | App-only |
| connector-grant | ask.status is pending | App-only |
| credential-request | credentialResolution absent or retryable | App-only |
| mobile-tool-permission | permission.status is not granted | App-only |
| permission-request | No answered marker in the legacy schema | App-only |
| app-secrets-request | A request.secrets item has state requested | App-only |

Spend-guard widgets, authentication/checkout forms, login/card vault forms and
channel-credential secret requests are app-only. Unknown message types are not
silently mapped to generic approval. The CLI exposes allowed_actions per item,
shows its proposed answer, and asks for confirmation before sending it.
Approvals map to approved/denied for reviews and allow-once/deny for local tools;
persistent choices use always, or never for local tools only.

## How this was derived

The read-only source notes were `R-sol/out/protocol-0.72.md` and
`R-sol/out/protocol-0.72.json`, produced by static reading of the installed app's
command validators and embedded reply schemas. This note cross-checks those
findings against gbot's command handlers, pending-item classifier and protocol
table. No app code, minified identifiers, byte offsets or complete command catalog
are reproduced here. No live backend or gateway calls were made to derive it.

`gbot doctor` re-extracts the installed app's command table and compares used
command names and argument kinds with USED_COMMANDS. It warns on missing names
or kind changes; it does not verify every field, reply shape or pending subtype.
The offline doctor option skips gateway calls but still checks local sign-in
state and app evidence. App updates may change fields without failing this check.

## Answering cards

Answers use the backend `aiserver.v1.GrokBotService`; include `agentId` and a nonempty `sessionId` when available. Fields use lower camel case and enum values are integers.

| Card and action | RPC and remaining fields |
|---|---|
| Auto-review approve, deny, always | `ResolveGrokBotAutoReviewApproval`: `requestId`, `resolution` 1, 2, or 3, `approvalPlatform` desktop |
| Local tool approve, deny, always, never | `ResolveGrokBotLocalToolPermission`: `entryId`, `requestId`, `resolution` 1, 2, 3, or 4 |
| Widget respond / dismiss | `RespondGrokBotWidget`: `entryId`, `value` / `DismissGrokBotWidget`: `entryId` |
| Secret | `SubmitGrokBotSecret`: `entryId`, `value` |
| Form respond / dismiss | `SubmitGrokBotUserForm`: `entryId`, `values`, `saveToVault: false`, `platform: 1` / `DismissGrokBotUserForm`: `entryId`, `mode: 1`, `platform: 1` |
| Email or Slack draft approve | `SendGrokBotDraft`: `entryId`, `email` (from, to, cc, subject, body) or `slack` (target, body, optional workspace and thread) |
| Draft deny | `DiscardGrokBotDraft`: `entryId` |

Resolve replies require `dispatched: true`; other answers require `accepted: true`. A missing flag means false. Refusals include a failure code and may include a message.
