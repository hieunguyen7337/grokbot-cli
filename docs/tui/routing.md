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

`sendPrompt` and `promptAcceptanceStatus` stay on the gateway until a live comparison
on a test bot establishes parity. `setGroupMembers` stays with `rooms.set_members`,
which already chooses the backend for temporal groups. Creation and templates remain
on their existing paths for later units; their replies still teach the registry.
Every other command remains on the gateway because this unit only verifies the
explicit routes above. Gateway parity statuses are unchanged, including planned M3
toggles; routing support alone does not supply their CLI or TUI controls.
