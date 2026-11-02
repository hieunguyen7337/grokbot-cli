# Temporal command routing

`gbot.service.routing.Router` wraps both CLI `ContextTransport` and service transports.
Each CLI context or service owns one `Harness` registry, shared by its transports.
Gateway `listAgents` and creation replies teach gateway IDs; backend `ListGrokBotAgents`
teaches `agentId`, never the backend server `id`. Missing harness preserves prior knowledge
or defaults to box. Callers can also use `Harness.learn(rows)`.

Only known `temporal` targets take the following routes. Target selection prefers
`agentId`, then `id`. Other harnesses and unknown targets retain the gateway path.
All RPCs belong to `aiserver.v1.GrokBotService`. Unlisted gateway fields are discarded.
`S` copies a nonempty session ID; `R` copies any non-null session ID, including empty.
`null` means the gateway success value is `None`.

| Command | RPC | Request mapping | Gateway reply |
|---|---|---|---|
| setAgentUnread | SetGrokBotAgentClientState | id→agentId; isUnread=true→markUnread=true, otherwise markRead=true; markFollowedThreadsRead only if true | null |
| setAgentHiddenFromSidebar | SetGrokBotAgentClientState | id→agentId; isHidden→hiddenFromSidebar | positive state.updatedAtMs→numeric stateUpdatedAt; otherwise null |
| setAgentNotifyOnUpdates | SetGrokBotAgentClientState | id→agentId; isEnabled→notifyOnUpdatesEnabled | null; background gateway mirror with original arguments |
| setAgentDraftingDisabled | SetGrokBotAgentDraftingDisabled | id; isDisabled→disabled | null |
| dismissAgentSuggestions | DismissGrokBotAgentSuggestions | agentId, suggestionIds; reason→GROK_BOT_AGENT_SUGGESTION_DISMISS_REASON_HIDDEN/ACTED | null |
| voteFeedback | VoteGrokBotFeedback | agentId, entryId, comment?; categories default []; action→GROK_BOT_FEEDBACK_ACTION_UP/DOWN/SUBMIT/REVERT; S | null |
| reactToMessage | ReactToGrokBotMessage | agentId, entryId, emoji; S | null |
| createThreadFromMessage | CreateGrokBotThreadFromMessage | agentId, entryId; no sessionId | null |
| resolveConnectorGrant | ResolveGrokBotConnectorGrant | agentId, requestId, entryId?; resolution→GROK_BOT_CONNECTOR_GRANT_RESOLUTION_ALLOWED/SKIPPED/ALWAYS_THIS_BOT/ALWAYS_ALL_TEAM_BOTS; S | null |
| getSubagents | ListGrokBotSubagents | id→agentId | subagents array; status forced running; numeric startedAtMs; positive numeric freshUntilMs only |
| getAgentTasks | ListGrokBotAgentTasks | agentId; includeRecentlyDone=true | TaskRows |
| markAgentTaskDone | MarkGrokBotAgentTaskDone | agentId, taskId | TaskRows |
| markAgentTaskRead | MarkGrokBotAgentTaskRead | agentId, taskId, entryId | TaskRows |
| setAgentTaskPinned | SetGrokBotAgentTaskPinned | agentId, taskId; isPinned→pinned | TaskRows |
| interruptAgentRun | InterruptGrokBotAgentRun | id→agentId; reason=user_interrupt; R | hadActiveRun |
| startFreshConversation | StartFreshGrokBotConversation | id→agentId; R | null |
| rollBackConversation | RollBackGrokBotConversation | id→agentId; R | null |
| deleteAgents | DeleteGrokBotAgent per temporal ID | ids split by harness; backend gets id; one gateway batch for remaining IDs | box transcript or []; optional combined refusedAgentIds/failedAgentIds |

TaskRows contains id/name/description/status/updatedAtMs and present unreadEntryId,
unreadPreview, unreadAtMs, pinnedAtMs, plus nonempty subagentIds. Decimal int64 strings
become integers. Status is normalized to open/done, defaulting to open. `followed`
is not copied. Backend refusals use `cards.check_reply` errors; unimplemented RPCs
raise without falling back to the gateway.

Deletion treats backend NotFound as deleted, PermissionDenied as refused and other
errors as failed. Deleted temporal IDs get a separate background gateway cleanup.
Mirror failures never change backend success. Service mirrors use its background
transport; context and service shutdown drain pending mirrors. No sleeps are used.

## Send path

For known temporal targets (by `agentId`), `sendPrompt` and `promptAcceptanceStatus`
use the backend and never fall back to the gateway. Box and unknown targets keep the
gateway commands unchanged. int64 fields are sent as decimal strings.

| Command | RPC | Request mapping | Gateway reply |
|---|---|---|---|
| sendPrompt | SendGrokBotUserMessage | agentId; clientNonce→messageId (required); prompt→text; sentAtMs=now; richText?, replyToId?, replyQuote?, traceparent?, mcpConfigJson?, taskId?, language?; isFork only if true; attachmentPaths/attachmentNames default []; enterEpochMs?/composedAtMs?→int64; S; nonempty machineId; onePasswordAppInstalled/rendersMcpElicitationForms only if true; firstSentAtMs→firstSentAgeMs=max(0, floor(now−firstSentAtMs)) | ACCEPTED_BOX, ACCEPTED_TEMPORAL or DUPLICATE → `{accepted: true}`; REFUSED, an unknown delivery or a refusal → `ValueError("Send refused: ...")` |
| promptAcceptanceStatus | GetGrokBotSendStatus | agentId; clientNonce→messageId; S; taskId?; firstSentAgeMs as above | NOT_FOUND → `{outcome: not-found}`; FOUND with status ACCEPTED/REJECTED/PENDING → record (accountSlot=host, clientNonce, agentId, inputDigest "", status, acceptedAtMs or 0, echoEntryId or null, rejectionCode only for rejected); anything else → `{outcome: unknown-durability}` |

Not forwarded: `source`, `initiator` and `sendSource`, because their protobuf enum
names are not documented, and `directAddressedAcceptance`. The reply field names
`delivery`, `outcome`, `status` and an optional nested `record` are inferred, and enum
values are matched by their documented suffix, so the unknown prefix does not matter.
Retries keep the same `messageId`; a 401 refreshes once and resends the same body.

`ListGrokBotAgentSessions` (`conversation.list_sessions`, `gbot sessions`) is a plain
backend read for any bot: agentId in, sessions out with kind (prefix
`GROK_BOT_AGENT_SESSION_KIND_` stripped, lower case, unknown → unspecified) and integer times.

`setGroupMembers` stays with `rooms.set_members`,
which already chooses the backend for temporal groups. Creation and templates remain
on their existing paths for later units; their replies still teach the registry.
Every other command remains on the gateway because this unit only verifies the
explicit routes above. Gateway parity statuses are unchanged, including planned M3
toggles; routing support alone does not supply their CLI or TUI controls.

## Live check (2026-10-31)

A read-only run over the 14 non-group bots confirmed the task and subagent reads.
`ListGrokBotAgentTasks` and `ListGrokBotSubagents` take the gateway agent id in
`agentId`; `ListGrokBotSubagents` rejects the backend id with `invalid_argument`.
An empty list arrives as `{}`, because protobuf JSON omits empty repeated fields,
and the router returns `[]` for it. No bot had open tasks or running subagents at
the time, so row parsing is covered only by the offline tests.
