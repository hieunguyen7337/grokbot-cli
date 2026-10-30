# Temporal command routing: Grok Bot desktop 0.77.0

Offline research of `_bundle-077`; only this document was written. No service, private configuration or credentials were accessed.
**VERIFIED** means observed client code or protobuf declarations, **INFERRED** means a conclusion beyond those observations, and **UNKNOWN** means the client cannot establish it. Verification of a caller is not verification of deployed server behaviour.
Existing background: [protocol-m2](protocol-m2.md) section 10; [protocol-m3](protocol-m3.md) sections 1, 4–8 and 10.

Bundle citations below use paths relative to the extracted bundle root and a short, searchable identifier:

- **M**: `dist/electron-main/main-app.cjs`.
- **C**: `dist/node-agent-coordinator/main.cjs`.
- **P**: `dist/electron-main/proto.cjs`.
- **R**: `dist/renderer/assets/index.eager-app-BtIHj2If.js`.

Notation: `?` optional; `[]` array; `a→b` rename; unrenamed fields are copied. Times converted to protobuf int64 use bigint; protobuf JSON represents these as decimal strings.
`S` below means copy sessionId only when nonempty; fresh/rollback/interrupt instead copy it whenever non-null, including empty. `N` means successful gateway value null.
Backend action envelopes are `{status:ok,value}`, `unimplemented`, `refused` with failureCode/message, or `unavailable` with kind/message.
The coordinator unwraps ok, throws a refusal/domain error or transport error otherwise (**VERIFIED: C `function Pr(`**).

## 1. Backend action adapter, command by command

**VERIFIED:** the first two supplied anchors actually lie in the same `Rut` method switch in this bundle. They are grouped below as its send/action portion and its client-state portion, followed by the outer `F_t` switch.
Nested delivery/outcome switches are reply decoders, not additional gateway-command inventories. Sources: **M `async function Rut(`, `function F_t(`**.
Every row in the following three tables is **VERIFIED**; each case is searchable as `case"<command>"` in M, with helper citations
where the implementation is delegated. RPCs belong to `aiserver.v1.GrokBotService` unless another service is named.

### Send/action portion: anchor `case"sendPrompt"`

| Command | Backend call and request mapping | Gateway value / response handling |
|---|---|---|
| sendPrompt | SendGrokBotUserMessage: agentId, clientNonce→messageId, prompt→text; sentAtMs=now; richText?, replyToId?, replyQuote?, isFork=(true only), attachmentPaths/attachmentNames default []; traceparent?, enterEpochMs?/composedAtMs?→int64; source→ClientSurface; S; nonempty machineId?; onePasswordAppInstalled/rendersMcpElicitationForms only if true; mcpConfigJson?, taskId?, language?; initiator/sendSource→enums; firstSentAtMs→firstSentAgeMs=max(0,floor(now−firstSentAtMs)) | ACCEPTED_BOX, ACCEPTED_TEMPORAL, DUPLICATE → `{accepted:true}`; REFUSED → refusal; unknown delivery → refusal. dispatched/mode/workflowId are not returned. M `function Iut(`, `function eQn(` |
| promptAcceptanceStatus | GetGrokBotSendStatus: agentId, clientNonce→messageId, S, taskId?, same firstSentAgeMs calculation | NOT_FOUND→`{outcome:not-found}`; unspecified/unknown→unknown-durability; otherwise found record: accountSlot=host, clientNonce, agentId, inputDigest empty, status=accepted/rejected/pending, acceptedAtMs=number or 0, echoEntryId or null, rejectionCode only for rejected, otherwise null. M `function Mut(` |
| interruptAgentRun | InterruptGrokBotAgentRun: id→agentId, reason=user_interrupt, sessionId if non-null | `{hadActiveRun}` |
| startFreshConversation | StartFreshGrokBotConversation: id→agentId, sessionId if non-null | N |
| rollBackConversation | RollBackGrokBotConversation: id→agentId, sessionId if non-null | N |
| respondToWidget | RespondGrokBotWidget: agentId, entryId, value, S | refusal if present; otherwise `{accepted}` |
| submitSecret | SubmitGrokBotSecret: agentId, entryId, value, S | refusal or accepted=false → failureCode=secret-request/save-refused, backend message or localized fallback; otherwise N |
| resolveCredentialRequest | ResolveGrokBotCredentialRequest: agentId, entryId, resolution approved/denied→APPROVED/DENIED, S | refusal or accepted=false → refusal; otherwise N |
| dismissWidget | DismissGrokBotWidget: agentId, entryId, S | refusal if present; otherwise `{accepted}` |
| submitUserForm | SubmitGrokBotUserForm: agentId, entryId, copied values map, platform→enum, saveToVault=(true only), S | refusal→failureCode=user-form/refused, backend message; accepted=false→failureCode=user-form/stale, message=command name; otherwise N |
| dismissUserForm | DismissGrokBotUserForm: agentId, entryId, mode dismissed→DISMISSED, otherwise ESCALATED; platform→enum; S | refusal→ordinary refusal; accepted=false→failureCode=user-form/stale, message=command name; otherwise N |
| reactToMessage | ReactToGrokBotMessage: agentId, entryId, emoji, S | refusal if present; otherwise N |
| createThreadFromMessage | CreateGrokBotThreadFromMessage: agentId, entryId; no sessionId forwarded | refusal if present; otherwise N |
| resolveLocalToolPermission | ResolveGrokBotLocalToolPermission: agentId, entryId, requestId, resolution allow-once/deny/always/never→ALLOW_ONCE/DENY/ALWAYS/NEVER, S | refusal if present; otherwise N |
| resolveConnectorGrant | ResolveGrokBotConnectorGrant: agentId, requestId, resolution allowed/skipped/always_this_bot/always_all_team_bots→corresponding uppercase enum, entryId?, S | refusal if present; otherwise N |
| resolveVirtualCardApproval | ResolveGrokBotVirtualCardApproval: agentId, entryId, requestId, approved/denied→enum; payAnotherWay only if true; paymentMethodId?; attestation? reduced to `{challengeId}`; no sessionId | refusal, or approved with spendRequestId and optional approvalUrl; denied; needs_auth; NEEDS_PASSKEY→needs_enrollment when no enrolledCredentialIds, else needs_passkey plus IDs; failed/unspecified/invalid approved result→failed with message. M `function mQn(` |
| beginSpendApproval | BeginGrokBotSpendApproval: agentId, requestId, paymentMethodId? | nonempty challengeId and ceremonyToken→challenge with ceremonyId/challengeId/ceremonyPath/ceremonyToken, otherwise not_required. Special refusal metadata can yield needs_enrollment/not_required. M `function fQn(`, `function qs(` |
| listVirtualCardPaymentMethods | ListGrokBotStripeLinkPaymentMethods: empty request | OK→ok, paymentMethods, unavailableCount; NEEDS_AUTH→needs_auth; ACCOUNT_CLOSED→account_closed; other→unavailable. Each method copies id/name/isDefault and optional brand/last4/expMonth/expYear/ineligibleReason; kind CARD/BANK_ACCOUNT/other→card/bank_account/other. M `function hQn(`, `function yQn(` |
| controlOutboundCall | control transfer/hang_up/retry_recording selects TransferGrokBotOutboundCall / HangUpGrokBotOutboundCall / RetryGrokBotOutboundCallRecording, each `{outboundCallId}` | accepted→N, otherwise refusal. M `async function oQn(` |
| searchPlacesArea | SearchGrokBotPlacesArea: agentId, entryId, cardIndex, area={southWest,northEast}, language default empty, S | FOUND parses placesCardJson→found/card, parse failure→failed; EMPTY/UNAVAILABLE/RATE_LIMITED/NOT_SEARCHABLE→empty/unavailable/rate_limited/not_searchable; other→failed. M `function AQn(` |
| resolveAutoReviewApproval | ResolveGrokBotAutoReviewApproval: agentId, requestId, approved/denied/always→enum; approvalPlatform default desktop; approvedCommand?, S, mcpElicitationContent? | N |
| handBackForeverBox | EndGrokBotBoxHandoff: id→agentId, requestId, trigger viewer-closed/dismissed/button or absent→VIEWER_CLOSED/DISMISSED/BUTTON | N; M `function XGn(` |

**VERIFIED — enum/default details:** ClientSurface desktop/mobile/absent→DESKTOP/MOBILE/UNSPECIFIED; initiator user,
template_import, template_share, card_action, plugin_setup, teach_recording→uppercase enum, absent→UNSPECIFIED;
sendSource chat/push/app_intent/action_button_dictation→uppercase enum, unknown/absent→UNSPECIFIED;
form platform desktop/ios/android→DESKTOP/IOS/ANDROID, absent→UNSPECIFIED. The outer adapter supplies source=desktop when a send
has no source. A valid detected timezone becomes `x-cursor-timezone`; ordinary action timeout is 20 seconds. Sources:
**M `function eQn(`, `function tQn(`, `function nQn(`, `function Tut(`, `function cYn(`, `YGn=`**.

### Client-state and trailing action portion: anchor `case"setAgentUnread"`

| Command | Backend call and request mapping | Gateway value / response handling |
|---|---|---|
| setAgentUnread | SetGrokBotAgentClientState: id→agentId; isUnread true→markUnread=true, otherwise markRead=true; markFollowedThreadsRead only when true | N, discards state |
| setAgentHiddenFromSidebar | SetGrokBotAgentClientState: id→agentId, isHidden→hiddenFromSidebar | positive state.updatedAtMs→`{stateUpdatedAt:Number(...)}`, otherwise N |
| setAgentNotifyOnUpdates | SetGrokBotAgentClientState: id→agentId, isEnabled→notifyOnUpdatesEnabled | N; coordinator also mirrors to gateway |
| setAgentDraftingDisabled | SetGrokBotAgentDraftingDisabled: id, isDisabled→disabled | N |
| dismissAgentSuggestions | DismissGrokBotAgentSuggestions: agentId, copied suggestionIds, reason hidden/acted→HIDDEN/ACTED | N |
| voteFeedback | VoteGrokBotFeedback: agentId, entryId, action up/down/submit/revert→UP/DOWN/SUBMIT/REVERT, categories default [], comment?, S | refusal if present; otherwise N |
| sendDraft | SendGrokBotDraft: agentId, entryId, translated draft oneof, S, shownSignatureHtml? | refusal if present; otherwise `{accepted}`; draft mapping below |
| discardDraft | DiscardGrokBotDraft: agentId, entryId, S | refusal if present; otherwise `{accepted}` |
| getSubagents | ListGrokBotSubagents: id→agentId | subagents array: subagentId, subagentType, title, **status forced running**, startedAtMs→number; freshUntilMs only if positive, converted to number |

**VERIFIED — draft oneof:** imessage-draft→imessage: optional to/chatId/recipientName, body, machineId, approvalId;
meeting-chat-draft→meetingChat: meetingId, meetingTitle?, body, markInternal only if true;
email-draft→email: from, to[], cc default [], subject, body; remaining slack draft→slack: workspace?, target, thread?, body.
Source: **M `function kQn(`**. The adapter does not forward unrelated gateway draft metadata.

**VERIFIED — failures/retry:** ordinary refusal uses backend failureCode/message, substituting null/command name if empty.
Connect Unimplemented becomes unimplemented; NotFound with `x-grok-bot-refusal=box_harness` becomes agent-scoped unimplemented;
unavailable/resource exhaustion→network, deadline→timeout, authentication/permission→access_denied, internal/unknown/data loss→http_5xx.
Local-tool permission has an explicit unavailable-metadata gateway fallback. Send network ambiguity (excluding Unavailable with
retry-after) checks GetGrokBotSendStatus before a resend: not-found retries once; found and not rejected counts as accepted;
other outcomes retain the original error. Sources: **M `function ki(`, `function qs(`, `function Put(`, `function sQn(`**.

### Outer operation switch: anchor `case"getAgentTasks"`

Here `TaskRows` means tasks mapped to id/name/description/status/updatedAtMs, optional nonempty subagentIds and present
unreadEntryId/unreadPreview/unreadAtMs/pinnedAtMs; int64s become numbers; unknown status defaults open. No followed field is copied.
`RoutineRows` means parse valid recordJson, discard embedded viewerCapabilities, add canOpen/canToggle/canEdit/canDelete from
viewerPermissions.allowedActions when supplied; discard invalid records, sort by nextRunAt (missing last), then createdAt. `Template` means shareId/name/avatarShape/avatarColor,
trimmed description/shareUrl/published, valid sourceAgentId?, activeVersion?, positive createdAtMs/updatedAtMs?, recognized visibility?.
**VERIFIED: M `function F_t(`, `function ESt(`, `function uq(`, `function NM(`, `function Ype(`**.

| Command | Backend call and request mapping | Gateway value / response handling |
|---|---|---|
| createAgentFromTemplate | CreateGrokBotAgentFromTemplate; section 3 | normalized `{agent,transcript:[],setup}` |
| setGroupMembers | SetGrokBotRoomMembers: id→agentId, copied memberAgentIds | requires returned ROOM and matching agentId; normalized Agent, not raw protobuf. M `function dot(` |
| getServerAgentRoster | ListGrokBotAgents with empty request, capability-gated | disabled or ready/agents/boxAgentCount; section 7 |
| deleteAgent | DeleteGrokBotAgent: id | N, NotFound counts as success; section 4 |
| getAgentAutomations | ListGrokBotAgentAutomations: id→agentId, detected timeZone if available | RoutineRows; M `function vpt(` |
| getAgentTasks | ListGrokBotAgentTasks: agentId, **includeRecentlyDone=true** | TaskRows |
| markAgentTaskDone | MarkGrokBotAgentTaskDone: agentId, taskId | TaskRows |
| markAgentTaskRead | MarkGrokBotAgentTaskRead: agentId, taskId, entryId | TaskRows |
| setAgentTaskPinned | SetGrokBotAgentTaskPinned: agentId, taskId, **isPinned→pinned** | TaskRows |
| deleteAgentAutomation | DeleteGrokBotAgentAutomation: id→agentId, automationId, timeZone?; removes cached webhook credential first | RoutineRows; M `function vpt(` |
| getAutomationWebhookCredential | ListGrokBotAgentAutomations: id→agentId,timeZone?; match parsed record id to automationId, require webhook trigger; DashboardService.CreateAutomationWebhookApiKey with **server row automationId**, if key not cached | `{url,key}`; URL uses backend base and escaped server automationId; account identity is pinned/rechecked. M `function vpt(` |
| runAutomationWebhook | Obtain credential as preceding row, then HTTP POST to its URL: bearer key, JSON context field; no GrokBotService run RPC | runUuid string→`{runId}`, otherwise runId=null; non-OK HTTP→error. M `function vpt(`, `function OVn(` |
| setAgentAutomationEnabled | SetGrokBotAgentAutomationEnabled: id→agentId, automationId, isEnabled, timeZone? | RoutineRows; M `function vpt(` |
| listAccountAutomations | ListGrokBotAccountAutomations: copied agentIds, timeZone? | per agent `{agentId,automations:RoutineRows}`; readIndividually/unavailable retain true flag and empty list, inconsistent flags/data or invalid id rejected. M `function vpt(` |
| getMainAgent | GetGrokBotUserRuntimeSettings: empty | normalized settings pointer; section 6 |
| setMainAgent | SetGrokBotMainAgent: agentId | normalized settings pointer; section 6 |
| ensureDefaultMainAgent | EnsureGrokBotDefaultMainAgent: empty | agentId/outcome; section 6; unclassified refusal receives temporal-creation-refused failure code |
| getCloudAgentInfo | BackgroundComposerService.GetBackgroundComposerInfo: trimmed bcId, includeDiff=false, doNotThrowIfSetupNotFinished=true; conditional supporting reads below | null for empty/missing; normalized cloud info with supporting-read outcomes. M `function h_t(`, `async function Oft(` |
| getCloudAgentConversation | BackgroundComposerService.GetBackgroundComposerConversation: trimmed bcId, exchangeOnly=true; retry without exchangeOnly on Unimplemented/InvalidArgument | empty bcId→null; error→failed/reason; success→read/messages, filtered/mapped as below. M `function VKn(`, `async function p_t(` |
| readMcpAppResource | ReadGrokBotMcpAppDocument: agentId, sessionId default empty, entryId; resourceUri/documentSha256 are not RPC fields | `{document:{resourceUri,html,meta?}}`; parses metaJson; missing IDs/NotFound→error. M `function M_t(` |
| callMcpAppTool | CallGrokBotMcpAppTool: agentId, sessionId default empty, entryId, toolName, argumentsJson, userActivated | resultJson oneof→resultJson; failure→error plus code only if needs_activation; absent result→error; usedActivation only if true; missing IDs/NotFound→error. M `function M_t(`, `function oYn(` |
| resolveAgentCreation | GetGrokBotRuntimeCapabilities: empty when capability cache needs reading; **no Resolve RPC** | local box/temporal scoped route; section 3 |
| authenticateMcpServer | DashboardService.CheckHttpMcpStatus, with optional GetAvailableMcpServers lookup; exact mapping below | started/authorizationUrl/serverName, already-authenticated, not-configured, unreachable/reason or not-supported/reason. M `function u_t(` |
| completeMcpOAuth | DashboardService.CompleteMcpOAuth: state→stateId, code→authorizationCode | N; M `function u_t(` |
| publishBotTemplate | ActivateGrokBotTemplateVersion: shareId, version | Template plus requested version; missing template→error. M `function C_t(` |
| getBotTemplateVersion | GetGrokBotTemplateVersion: shareId, version; then GET blobGetUrl and decode recipe | shareId, recipe profile name/avatarShape/avatarColor/trimmed description, shareUrl, memory/skills/routines/plugins; published=response.active, version, active, positive createdAtMs?, recognized visibility?. Missing URL/bad recipe→error. M `function C_t(` |
| getBotTemplateForSourceAgent | GetGrokBotTemplateForSourceAgent: sourceAgentId | null when missing template, otherwise Template; M `function C_t(` |
| getBotTemplateExportPolicy | GetGrokBotTemplateExportPolicy: empty; account/team cache can avoid call | `{exportPolicy}` for all/team_only/none, otherwise empty object; stale value can survive failed refresh. M `function C_t(`, `function Wqe(` |
| deleteBotTemplate | DeleteGrokBotTemplate: shareId | N; M `function C_t(` |
| setBotTemplateVisibility | SetGrokBotTemplateVisibility: shareId, visibility team→TEAM, otherwise PUBLIC | Template, requires template; M `function C_t(` |

**VERIFIED — adjacent create branches:** before that switch, createAgent invokes the section 3 creator; createGroup invokes CreateGrokBotRoom with clientNonce→agentId, name, description default empty, memberAgentIds[], humanMemberUserIds default [].
The latter requires temporal creationRoute/scope and clientNonce, validates returned room/identity, normalizes agent/transcript=[], and sets namedBy=app if human members were requested. Sources: **M `function F_t(`, `function dot(`**.

**VERIFIED — MCP authentication detail:** trim serverId; `grok:` prefix→serverIdentifier without prefix; a numeric server-row ID
→serverIds=[ID]; another valid identifier plus requestingAgentId→serverIdentifiers=[identifier], grokBotAgentId=requestingAgentId.
CheckHttpMcpStatus adds oauthRedirectUri, normalized accountKey (empty→default), forceReauth=true only when requested,
userInitiated=true, nonempty dataCenter?, and valid shareWithBot→shareWithBotAgentId/shareWithBotPluginId(int64)/
shareAcknowledgedWarningVersion. The optional name/account lookup GetAvailableMcpServers passes grokBotAgentId only for the bot
identifier case, otherwise empty. A valid OAuth redirect is required. Status selection matches id or serverIdentifier;
requiresAuth with valid authUrl→started; signedIn or available/no-auth/not-forced→already-authenticated; missing row→not-configured;
unavailable/no-auth→unreachable; remaining no-link/invalid-link→not-supported. Sources: **M `function BKn(`, `function NKn(`,
`function LKn(`, `function Ez(`, `function u_t(`**.

**VERIFIED — cloud helper detail:** info returns bcId/status/name/prompt/branchName/prUrl/prState/prStateSource/prNumber/mergeableState/lastActivityAtMs, updatedAtMs when valid, filesChanged/linesAdded/linesRemoved/files/artifacts/project.
includeFiles defaults true: if filesChanged>0, GetOptimizedDiffDetails with bcId,excludeBeforeAfterDiffs=true maps diffs to file rows.
A nonempty unmerged PR URL triggers GetPullRequestMergeStatus with prUrl. Root project metadata triggers ListWorkersForManager
with managerBcId=bcId and counts CREATING/RUNNING workers. includeArtifacts=true and finished/error/expired status triggers
GetTurnSummaryBackgroundComposer with bcId, then, if summary exists, ListBackgroundComposerArtifacts with bcId; maps absolutePath,
sizeBytes,updatedAtUnixMs to path/number sizeBytes/number updatedAtMs and plans downloadable files from the summary.
Supporting reads return skipped/listed/failed/unavailable rather than flattening errors. Conversation maps bubbleId→id and text,
counts human/wake turns from zero, skips steer, non-subscription simulated, blank, thinking and tool-result bubbles;
subscription simulations become wake rows with wake metadata; AI send-message suffix becomes sent, ordinary AI becomes assistant;
human triggeringUserInfo.authId becomes person submitter unless sentByAgentId exists. Sources: **M `async function Oft(`, `function Gqe(`, `async function _1n(`, `async function A1n(`, `async function u1n(`, `async function k1n(`, `function HKn(`, `function jKn(`**.

## 2. How the adapter is selected, and gbot's current commands

**VERIFIED — ordinary decision:** C validates supported action names/arguments, extracts the target using Zz, and requires its
known harness to be temporal. No owner test or general feature flag occurs in this per-command decision. Harness state comes from
roster id/harness rows, successful creation/server roster, and restoreTemporalAgentRouting. Absent harness preserves previous
knowledge or defaults box; an explicit unfamiliar harness becomes unsupported. The router rejects supported actions on unsupported
harnesses except MCP auth/completion. Sources: **C `function n3(`, `function Hx(`, `function Zz(`, `function iz(`, `function Fne(`**.

**VERIFIED — exceptions/checks:** resolveAutoReviewApproval and resolveConnectorGrant use backend for nonempty `group:` session
suffixes even without temporal target knowledge; this tests the session syntax, not room ownership. OAuth completion uses backend
for a recently remembered authorization state; authentication without oauthRedirectUri stays gateway. Template operations use
the remembered shareId→sourceAgentId harness; getBotTemplateForSourceAgent uses sourceAgentId; export policy uses backend if any
temporal IDs are known. MCP resource reads require documentSha256; tool calls require agentId and entryId before trying backend.
Those two special branches and template import fall back on unimplemented. Sources: **C `function n3(`, `function Ws(`, `function Zz(`**.

**VERIFIED — backend attempts without temporal target:** promptAcceptanceStatus, resolveVirtualCardApproval, beginSpendApproval,
listVirtualCardPaymentMethods, controlOutboundCall, searchPlacesArea, getMainAgent, setMainAgent, ensureDefaultMainAgent;
also resolveLocalToolPermission and both cloud-agent reads. These are explicit exceptions, not the general temporal rule.
setAgentNotifyOnUpdates also makes a background gateway mirror call. Virtual-card settlement mirrors apply to the box path.
Sources: **C `_ne=new Set`, `Xt=Q.method`, `function HK(`, `if(!kt&&!$K(Q.method)&&!Xt&&!Ce)`**.

**VERIFIED — no case versus unsupported backend:** commands outside Hx go to gateway even for temporal targets. A recognized
action with invalid temporal arguments fails validation. An unimplemented backend action required by temporal routing fails
instead of falling back, except beginSpendApproval→not_required and searchPlacesArea→not_searchable. Non-required backend attempts
can fall back; getMainAgent then returns agentId=null, set/ensure main throw unsupported errors, listVirtualCardPaymentMethods
returns unavailable. kickstartAgent for temporal returns isIntroductionInFlight=false locally. Sources: **C `function n3(`**.

**VERIFIED — creation/room policy:** dev origin or any helper purpose forces host creation and rejects an explicit temporal route.
For groups with no humans, route or nonce, any non-temporal member permits legacy gateway creation; otherwise resolve creation
route. A box route with humans fails; temporal room creation requires scoped route and nonce. The observed creator does not test
serverRoomsEnabled separately. Runtime capabilities name temporalCreationEnabled, durableIdentityEnabled,
durableIdentityWritesEnabled, agentMessagingEnabled, serverRoomsEnabled; only the first three gate blank temporal creation here,
and durableIdentityEnabled gates server roster. Main-agent UI uses sand_grok_main_agent. Team metadata uses grok_bot_multiplayer,
grok_bot_external_grant_access and grok_bot_team_bot_access_list; grok_bot_team_agents_list_coalesce affects refresh jitter.
These renderer gates do not override C's ordinary action harness test. Sources: **C `function Xq(`, `function n3(`;
M `function aDn(`, `function yj(`; P `GrokBotRuntimeCapabilities|`; R `function MGn(`, `function HWn(`, `function cd(`**.

The following is the complete `USED_COMMANDS` inventory obtained statically from gbot/protocol.py and service module COMMANDS declarations; it is repository context, not a claim that gbot already implements this desktop router. Bundle verdicts are **VERIFIED**:

| Group for a known temporal target | Entries from USED_COMMANDS | Evidence |
|---|---|---|
| Backend adapter | sendPrompt, interruptAgentRun, startFreshConversation, rollBackConversation, resolveConnectorGrant, setGroupMembers, setAgentUnread, reactToMessage, voteFeedback, createThreadFromMessage, dismissAgentSuggestions, getSubagents, getAgentTasks, markAgentTaskDone, markAgentTaskRead, setAgentTaskPinned (recomputed by the orchestrator from `gbot.protocol.USED_COMMANDS` at 857007e) | C `function Hx(`, `function n3(`; M named cases and `function dot(` |
| Creation route, not existing target harness | createGroup | C `if(Q.method==="createGroup")`; M `function dot(` |
| No action-adapter case: gateway | listAgents, getAgentTranscriptTail, openAgentTail, getForeverBoxStatus, getHostStatus, getBoxSecretsStatus, getMcpState, listBoxMcpServers, getEffectiveMcpPlugins, listMcpServerTools, getTrays, dismissTray, clearTrays | C `function Hx(`, `function n3(` |

**VERIFIED caveat:** transcript presentation is a separate server-tail/SSE subsystem; absence of a command-action case does not
mean the desktop displays temporal gateway transcripts. C suppresses temporal gateway transcript events. gbot's USED_RPCS are
already direct backend calls; they do not pass through this command choice. Repository rooms.set_members already branches on
harness for SetGrokBotRoomMembers. Sources: **C `gatewayTranscript(`, `function iz(`**; repo gbot/protocol.py and gbot/service/rooms.py.

## 3. Resolve, create, introduce and import

**VERIFIED — resolution:** resolveAgentCreation is a local adapter action with empty arguments. It obtains runtime capabilities
through GetGrokBotRuntimeCapabilities with empty request; response has capabilities with the five booleans named in section 2.
temporalCreationEnabled=false/absent gives kind=box; true requires durableIdentityEnabled and durableIdentityWritesEnabled or
throws FailedPrecondition. Enabled returns kind=temporal and scope: a JSON-encoded pair of backend URL and accountScopeOfToken.
The token itself is not the scope. Capability caching uses account subject/team key, up to 60 seconds; incomplete capability sets
are not retained. Creation scope binds backend/account and is rechecked before the call and token acquisition.
Sources: **M `function lot(`, `function yj(`, `function sDn(`, `function aDn(`; P `GetGrokBotRuntimeCapabilitiesResponse|`**.

**VERIFIED — dialog-to-usable sequence:** (1) new-bot dialog validates nonblank name, maximum 255, and supplies shape/color;
(2) launcher reserves clientNonce; creator trims/slices name, defaults description empty, sets origin=user and
isKickstartRequested=true, includes chosen avatarShape/avatarColor and optional templateId; (3) roster resolves route if missing,
persists the temporal creation attempt scoped to the account, adds language, and submits createAgent; retries reuse the nonce;
(4) coordinator sends the temporal action to main, not gateway; (5) the RPC below returns a validated Agent with transcript=[];
(6) onCreated registers temporal routing, installs the local row, refreshes server roster and later clears persisted creation when
confirmed there; (7) launcher associates/selects the bot and awaits first content. For temporal it skips a separate kickstart RPC;
C also makes any temporal kickstart command a local false acknowledgement. Sources: **R `function N$t(`, `async function P$t(`,
`function FUn(`, `Qe=FUn`, `kickstartAwaitingFirstMessage:async`; C `function n3(`; M `function lot(`**.

**VERIFIED — actual CreateGrokBotTemporalAgent request:** clientNonce→agentId; name/description; title/avatarShape/avatarColor
default empty; avatarPngBase64, if supplied, becomes PNG data URL in avatarDataUrl; harness=TEMPORAL;
kickstartRequested=(isKickstartRequested=true); introductionSuppressed=(explicit suppression OR kickstart not requested);
language?; createdAutomatically only if isAutomatic=true. It does not forward templateId, origin, purpose, supportsTemporalHarness
or creationRoute. Timeout 45 seconds. RPC uses **CreateGrokBotAgentRequest/Response**, not Temporal-named messages;
omitted legacyAgentId/createIntent/createCaller use protobuf defaults. Reply declares agent and harness; caller validates the
agent's agentId equals nonce and agent.harness=temporal, then normalizes via Hb. Normal dialog has no PNG/title/instructions input;
PNG is supported by the lower creator. No post-create avatar upload is necessary for that lower path.
Sources: **M `function lot(`, `function Hb(`; P `createGrokBotTemporalAgent:{`, `CreateGrokBotAgentRequest|`, `CreateGrokBotAgentResponse|`**.

**VERIFIED — template import (protocol-m3 section 10's backend-first exception):** C attempts adapter before target-harness lookup;
only unimplemented falls back to gateway. Main sends CreateGrokBotAgentFromTemplate with shareId, caller-reserved agentId,
expectedActiveVersion?, setupDelegationSupported=true, creatorContext?, language?, importEntry?; isAutoOpen=true overrides entry
to AUTO_OPEN_LINK; BOT_TEMPLATE_IMPORT_ENTRY_CHAT_LINK maps CHAT_LINK. isAutomatic affects analytics, not RPC fields.
Response agent must match requested agentId and be temporal. Result is normalized agent, empty transcript and setup.
Sources: **C `if(O==="createAgentFromTemplate")`; M `function B_t(`, `function dYn(`;
P `CreateGrokBotAgentFromTemplateRequest|`, `CreateGrokBotAgentFromTemplateResponse|`**.

**VERIFIED — import reply flags:** setupHandledByServer=true skips blobGetUrl download and returns an empty recipe with
isSetupSendSuppressed=true. Otherwise a nonempty blobGetUrl is fetched without redirects, bounded by a deadline/size limit and
decoded as recipe; absent URL/download or decode failure yields unavailable setup while retaining the created agent.
gettingStartedTrusted controls trusted-source/getting-started skill handling; conversationalSetupEnabled adds isConversationalSetup;
updateStateSplit adds splitStateTools when setup is a recipe. Temporal setup always strips skills; remaining automations/plugins/
memories may require client setup, but if none remain isSetupSendSuppressed=true. Server-confirmed setup always suppresses sends.
Sources: **M `function B_t(`, `async function lYn(`, `function rXe(`, `function oXe(`**.

**UNKNOWN — produced introduction and eventual readiness:** client code requests/suppresses setup, but cannot prove which server workflow creates the greeting, its exact content, timing or all resource side effects.
Settle with server implementation or an authorized creation/import capture through roster confirmation and first transcript events. No such mutation was performed.

## 4. Delete and box mirror cleanup

**VERIFIED:** deleteAgents splits IDs using known temporal harness. Box IDs use gateway deleteAgents with ids=box IDs.
Each temporal ID invokes server action deleteAgent, which calls DeleteGrokBotAgent with id and 60-second timeout, empty response.
NotFound is treated as already deleted; PermissionDenied becomes refused; other failures are classified. Aborted/unavailable IDs
are failed. Successful temporal IDs trigger **gateway deleteAgents with `{ids:successfulTemporalIds}` and demand=background**;
this call is not awaited for deletion success, and failures only log deferred mirror cleanup. The combined reply contains box
transcript or [], optional refusedAgentIds and failedAgentIds. No backend success list is exposed.
Sources: **C `U=async(O,$)=>`, `sand.coordinator.box_delete_mirror_deferred`; M `function vSt(`;
P `DeleteGrokBotAgentRequest|`, `DeleteGrokBotAgentResponse`**.
**UNKNOWN:** actual server erasure/retention and mirror retry persistence need server/host source or a controlled deletion capture;
the empty response and background call do not prove those effects. UI/main-agent restrictions are protocol-m3 sections 4 and 8.

## 5. Temporal bot settings and full client state

All rows are **VERIFIED**. Temporal alone does not send every settings action to a backend identity RPC.

| Action | Actual desktop path and fields | Bundle evidence |
|---|---|---|
| setAgentVoice | temporal with viewerIsOwner=false→no write; otherwise direct SetGrokBotAgentVoice with id=agentId, only supplied voiceId/voiceSpeed/voiceLanguage; null voiceId→empty string; declared reply agent is discarded | R `function dWn(`; M `setVoice:async`; P `SetGrokBotAgentVoiceRequest|`, `SetGrokBotAgentVoiceResponse|` |
| setAgentAvatarBytes / clear | ordinary owned temporal row→gateway setAgentAvatarBytes with id,pngBase64 (null clears); refresh server roster afterwards. Nonowner with serverId→UpdateGrokBotAgent with id=serverId,partialUpdate=true, avatarChange oneof avatarDataUrl=PNG data URL or clearAvatar empty message for null; require returned agent, normalize as team row | R `function NGn(`, `setAgentAvatarBytes:async`; M `updateIdentity:async`, `function sVn(` |
| updateAgent | ordinary owned temporal row→gateway updateAgent with id,profile,editedFields; no temporal adapter case. Nonowner with serverId→UpdateGrokBotAgent with id=serverId,partialUpdate=true and changed name?/description?/title?/avatarShape?/avatarColor?, optional avatarChange as above; reply agent required, team-normalized | R `function NGn(`, `refreshServerRoster:`, `function MWn(`; M `updateIdentity:async`; P `UpdateGrokBotAgentRequest|` |
| setAgentHiddenFromSidebar | owned temporal→SetGrokBotAgentClientState with agentId=id,hiddenFromSidebar=isHidden; positive state.updatedAtMs→stateUpdatedAt acknowledgement, otherwise null. Nonowner uses direct desktop sidebar adapter with the same backend fields and discards response | M `case"setAgentHiddenFromSidebar"`, `setSidebarHidden:async`; R `setAgentHiddenFromSidebar:(t,r)=>` |
| setAgentNotifyOnUpdates | SetGrokBotAgentClientState with agentId=id,notifyOnUpdatesEnabled=isEnabled; discard state, return null; background gateway mirror of original command/args | M named case; C `function HK(` |
| setAgentDraftingDisabled | SetGrokBotAgentDraftingDisabled with id,disabled=isDisabled; empty response→null. UI permits owned nongroup rows | M named case; P `SetGrokBotAgentDraftingDisabledRequest|`; R `function I5t(` |

**VERIFIED — SetGrokBotAgentClientState full schema:** request agentId:string, optional booleans markRead,markUnread,
notificationsEnabled,notifyOnUpdatesEnabled,hiddenFromSidebar,markFollowedThreadsRead. Reply has state?:GrokBotAgentClientState.
State fields: agentId:string; lastViewedAtMs?:int64; unreadCount:uint32; lastActivityAtMs?:int64; lastEntryId?/lastEntryKind?/lastMessageId?/lastMessagePreview?:string;
notificationsEnabled/notifyOnUpdatesEnabled/hiddenFromSidebar:boolean; updatedAtMs:int64; lastEntryPreview?:message; lastMessageTaskId?:string;
removedFromSidebar?:boolean; unreadThreadCount:uint32. Sources: **P `SetGrokBotAgentClientStateRequest|`,
`SetGrokBotAgentClientStateResponse|`, `GrokBotAgentClientState|`**.
lastEntryPreview is a oneof: text(text,copyJson?); sentAgentMessage/receivedAgentMessage(peerName,text); attachments(count,kinds:[kind,count]); link(url); widgetPrompt(prompt); widgetAnswered(prompt,answer);
widgetOptions(prompt,options[]). **VERIFIED: P `GrokBotAgentEntryPreview|` and its dotted nested message names**.
See protocol-m3 sections 5–7 for avatar processing/UI controls; no claimed backend behaviour is inferred from those controls.
**UNKNOWN:** whether the gateway later persists an owned temporal profile/avatar edit through its own backend client requires host
implementation or a gateway-side trace. The desktop call path above does not establish that second hop.

## 6. Main agent and startup pointer

**VERIFIED:** getMainAgent→GetGrokBotUserRuntimeSettings with empty request; setMainAgent→SetGrokBotMainAgent with agentId:string;
both replies have settings?:GrokBotUserRuntimeSettings. Adapter parses settings.mainAgentId as valid agent ID or null and returns
agentId plus ownerJobRole when settings.jobRole is recognized. ensureDefaultMainAgent→EnsureGrokBotDefaultMainAgent with empty
request, reply agentId:string,outcome:enum; adapter returns valid id or empty string and mapped outcome. Declared outcomes:
UNSPECIFIED=0, CREATED=1, PRESENT=2, HAS_MAIN_AGENT=3, TOMBSTONED=4, PINNED_FULL=5, BUSY=6; renderer accepts created/present/
hasMainAgent, refreshes pointer and pins it. These are user settings operations, not readMainAgentContext.
Sources: **M `function T_t(`, `function k_t(`; P `GetGrokBotUserRuntimeSettingsResponse|`, `SetGrokBotMainAgentRequest|`,
`EnsureGrokBotDefaultMainAgentResponse|`, `EnsureGrokBotDefaultMainAgentResponse.Outcome`; R `function uUn(`, `function Ake(`**.

**VERIFIED — complete top-level settings fields:** updatedAtMs:int64; pinnedAgents?,sidebarSections?,autoReviewInstructions?,toolPermissions?:messages; hasSeenOnboarding?:boolean; mainAgentId?/jobRole?:string; termsSeenAtMs?:int64;
emailProvider and xToolAccess enums. The pointer adapter ignores the other settings. **P `GrokBotUserRuntimeSettings|`**.
**VERIFIED — startup/read:** renderer creates the main-agent store in MGn; its load/read invokes source.getMainAgent and therefore
the settings RPC above. sand_grok_main_agent gates UI subscriptions/loading/visibility; the current ID comes from settings,
not a roster isMain field. Store also rereads on reconnect/server changes and protects an optimistic set from a stale null echo.
Sources: **R `function MGn(`, `function uUn(`, `function cd(`, `function $ce(`; M `function T_t(`**.
**UNKNOWN:** a server prohibition on deleting the current main bot, and its provisioning persona, require server source or controlled
captures; protocol-m3 section 8's UI protections do not settle them.

## 7. Server roster, identities and merges

**VERIFIED — fetch:** getServerAgentRoster checks durableIdentityEnabled through runtime capabilities; disabled/FailedPrecondition
produces status=disabled. Otherwise ListGrokBotAgents with empty request (20-second timeout) returns agents,slackConnections,
truncated,teamsConnections. Adapter retains only harness=temporal, drops malformed agentId, returns ready/agents plus boxAgentCount
=all rows minus temporal rows (including malformed temporal rows in that temporal count). It does not forward truncated or either
connection list. Sources: **M `function Ale(`, `function yj(`; P `ListGrokBotAgentsRequest|`, `ListGrokBotAgentsResponse|`**.

**VERIFIED — ordinary normalization Hb:** backend **agentId→gateway id**, backend **id→serverId** when nonempty;
legacyAgentId is not used for matching. Copies name,description,title,avatarShape/avatarColor/avatarVersion, converted
createdAtMs→createdAt/updatedAtMs→updatedAt, harness; avatarDataUrl=null, avatarPhoto from photo resolver. ROOM→isGroup=true,
valid memberAgentIds→memberIds; otherwise memberIds=[]. Adds default empty path, inactive/nonrunning/noncomposing flags,
null lastEntry/lastMessageId/awaitingUserResponse, hasUnread=false, notificationsEnabled/notifyOnUpdatesEnabled=true, user origin.
Copies voice fields through dbFromWire (empty voice ID→null, speed/language normalized), suggestions with mapped icons.
**It does not copy draftingDisabled, viewerIsOwner, viewerCanManage, viewerSessionId, people, visibility or teamId.** Those fields
existing in protobuf is not evidence that this adapter supplies them. Sources: **M `function Hb(`, `static dbFromWire(`;
P `GrokBotAgent|`**. Voice normalization/options are protocol-m3 section 6.

**VERIFIED — ordinary merge pWn:** maps normalized rows by id, exactly matching gateway id to backend agentId through Hb;
no legacyAgentId fallback. Missing temporal gateway rows are pruned after a complete server list unless pending-created/protected;
server-only temporal rows are added. For matching rows, server identity/profile/avatar/createdAt/harness/serverId/isGroup/memberIds
replace gateway values; updatedAt is maximum. Server voice fields override supplied gateway voice fields; missing server voice
fields retain gateway values. Old suggestions are removed and replaced only when server suggestions exist. Avatar data is retained
only when avatarVersion is unchanged and no server data URL exists. Gateway run/unread/client state and draftingDisabled remain
from the existing row; created-only Hb rows lack draftingDisabled. Origin/purpose/activity fallback preserves local context.
Sources: **R `function pWn(`, `function w7(`, `function sWn(`; M `function Hb(`**.

**VERIFIED — separate team metadata merge:** ListGrokBotTeamAgents with empty request is preferred; Unimplemented falls back to
ListGrokBotAgents with includeTeamAgents=true. OM uses backend agentId as logical agentId and id as serverId; no legacyAgentId
match. It maps viewerIsOwner (absent defaults true), optional viewerCanManage, viewerSessionId, visibility/teamId/published/access
flags, ownerDisplayName, team-default, room members/people, viewer access/actions and connection signals. OM does not copy
draftingDisabled or voice fields. R's vGn joins these remote agentId values to row.id; lGn supplies ownership/manage/session and
team metadata, uses team identity/avatar for nonowners, preserves ordinary identity for owners, and adds unmatched nonowner rows.
viewerCanManage can also be restricted by a separate local override map; nonowner team defaults force sidebar visibility.
Sources: **M `function Wut(`, `function OM(`; R `function vGn(`, `function lGn(`, `function RWn(`, `function tGn(`**.

**INFERRED — implementation consequence:** a gbot backend router should retain the logical agentId and separate serverId, preserve
gateway/client overlays, and avoid assuming raw ListGrokBotAgents JSON is already a gateway Agent. Client code verifies the mapping,
not which incomplete sources will be available for a particular account. **UNKNOWN:** deployed capability values, roster completeness
when truncated, and producer-side drafting-state propagation would be settled by authorized read-only GetGrokBotRuntimeCapabilities,
ListGrokBotAgents/ListGrokBotTeamAgents reads and a roster/status event capture. No live reads were made.
