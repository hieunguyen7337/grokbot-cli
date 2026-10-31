# Terminal UI protocol facts: Grok Bot 0.77.0

Static, offline research of `_bundle-077`; no service was contacted. These are interoperability notes in our own words, not a supported
API contract. **VERIFIED** means present in code/schema, **INFERRED** means an interpretation of that evidence, and **UNKNOWN** means
the supplied client cannot establish it. Optional (`?`) and nullable (`null`) are different. IDs are strings; timestamps and sequence
values exposed to JavaScript are numbers. `T[]` means an array.

Citation shorthand (all paths relative to the extracted bundle root):

- **C** = `dist/node-agent-coordinator/main.cjs`.
- **M** = `dist/electron-main/main-app.cjs`.
- **P** = `dist/electron-main/proto.cjs`.
- **R** = `dist/renderer/assets/index.eager-app-BtIHj2If.js`.
- **S** = C, unique search `async function are()`; it decodes the adjacent `wz` base64 value with raw DEFLATE into the gateway JSON
  schema. Citations such as **S `$defs.SandAgentSummary`** identify exact keys in that decoded schema. The schema declares source
  `sand/src/shared/rpc/gateway.ts`. Only interface facts, not the encoded content or implementation, are recorded here.

## 1. SSE `/events`

**VERIFIED — declared channels and payloads.** The embedded contract has these 29 channels. This table gives every outer payload field;
named nested records refer to the exact `$defs` of the same name in S. `AgentId` means string. Every row is cited by **S
`events.<channel>`** and the referenced `$defs`.

| Channel | Payload |
|---|---|
| `agents` | `{activeAgentId:string, agents:SandAgentSummary[], ordered?:OrderedStamp, coverage?:Coverage\|null}` |
| `agent-upserted` | `{activeAgentId:string, agent:SandAgentSummary, ordered?:OrderedStamp}` |
| `agent-activity` | `{agentId:string, live:SandAgentLiveOverlay\|null, client:SandAgentClientOverlay\|null}` |
| `transcript` | Discriminated events below |
| `outline` | `{agentId:string, type:appended\|updated, item:SandConversationOutlineItem}` or `{agentId:string, type:snapshot, items:SandConversationOutlineItem[]}` |
| `subagents` | `{parentAgentId:string, subagents:SandSubagentInfo[]}` |
| `async-tasks` | `{parentAgentId:string, tasks:SandAsyncTaskInfo[]}` |
| `automations` | `{agentId:string, automations:SandAutomation[]}` |
| `workflows` | `{agentId:string, workflows:SandSkill[]}` |
| `todos` | `{agentId:string, todos:SandAgentTodo[]}` |
| `agent-automations-changed`, `agent-meetings`, `agent-tasks`, `bot-secrets`, `bot-skills`, `library-docs` | Each `{agentId:string}` |
| `forever-box` | `SandForeverBoxStatus` (section 10) |
| `box-disk-pressure` | `{level:hard\|soft}` or null |
| `teach-recording` | `{agentId:string\|null, maxDurationMs:number, startedAtMs:number\|null, state:idle\|recording}` |
| `computer-action` | `{agentId:string, type:click\|drag\|move\|scroll, x:number, y:number, button?:string, count?:number}` |
| `cloud-agent-update` | `{bcId:string, status:creating\|error\|expired\|finished\|running\|unknown, updatedAtMs:number}` |
| `host-settings` | `{fields:SandHostSettingsField[]}` (setting-name strings) |
| `mcp-auth` | `{accountKey:string, requestingAgentId:string\|null, serverId:string, serverName:string, failureDetail?:string, outcome?:connected\|cancelled\|null, serverIdentifier?:string, serverUrl?:string}` |
| `mcp-servers` | `{servers:{serverIdentifier:string,status:string,toolCount:number,pendingSignIn?:true,statusDetail?:string,statusReason?:string}[]}` |
| `messages-grants` | `{requestId:string, grants:(automation\|contacts\|fullDiskAccess)[]}` |
| `server-page-title-changed` | `{atMs:number, page:{kind:canvas,canvasId:string}\|{kind:document,documentId:string,storeId:string}, title:string, contentChanged?:boolean\|null}` |
| `server-roster-changed` | `{kind:agent,agentId:string}` or `{kind:user-settings,explicit:boolean,fields:(autoReview\|hasSeenOnboarding\|jobRole\|libraryPins\|mainAgent\|mcpServers\|pinnedAgents\|sidebarSections\|timeZone)[]}` or `{kind:resync}` |
| `tray` | `{type:pushed,tray:SandErrorTray}`, `{type:dismissed,id:string}`, `{type:snapshot,trays:SandErrorTray[]}`, or `{type:cleared}` |
| `voice-call-nudge` | `{agentId:string,callId:string,kind:ack\|outcome\|overheard\|progress,update:string}` |

**VERIFIED.** Transcript payloads are `{type:snapshot,activeAgentId,entries, cloudAgentPeerIds?:string[],ordered?,coverage?}`;
`{type:appended|updated, entry,agentId?:string,ordered?,replay?:true}`; `{type:removed,id:string,
seq?:number,agentId?:string,ordered?}`; or `{type:cleared,agentId?:string,ordered?}`. `OrderedStamp` is
`{replicaKey:string,epoch:string,sequence:number}`. Coverage is `{kind:complete-roster}` or
`{kind:transcript-live-range,fromSequence:number, throughSequence:number}`. No channel above has a top-level `sessionId` field. The
coordinator encodes nondefault transcript sessions in `replicaKey` as `transcript:<agentId><NUL><sessionId>`; the default omits the NUL
and session. Sources: **S `events.transcript`, `$defs.OrderedStamp`; C `function KF(n)`**.

**VERIFIED.** The client fetches bare `/events`, uses Bearer authentication, parses JSON from SSE `data:` lines into
`{channel,payload}`, and does not require an SSE `event:` name. Non-data comments are ignored except `:echo <nonce>`; it posts
`/events/echo?nonce=...` to test a stream. Any received bytes refresh the 35-second stall watchdog; an unsuccessful echo probe aborts
the stream. Reconnect backoff starts at 1 second, doubles to a 10-second cap, and resets after connection. Connection deadline is 15
seconds; echo probe deadline is 1.5 seconds. It re-resolves the connection, emits transport status, seeds `listAgents`, and rehydrates
interested stores on return. Sources: **C `az="/events"`, `PB=":echo "`, `dispatchEventBlock(e,t)`, `async liveStreamAnswers(e)`,
`WB=35e3`, `async runEventLoop()`, `agents roster seed skipped`; R `noteReconnect:`**.

**INFERRED:** omitting `channels` requests the complete feed, since that is what the desktop does. **UNKNOWN:** whether explicitly empty
`channels=` has exactly the same meaning, the server heartbeat frame/interval, or additional undeclared runtime channels. This bundle
contains the consumer/contract, not the HTTP SSE server implementation. There is no declared `reset` channel; `cleared`, snapshots,
ordered epoch changes, and `server-roster-changed.kind=resync` are verified reset mechanisms, not interchangeable signals. Settle
remaining wire questions with gateway server source or a consented read-only SSE capture with both query forms.

**VERIFIED:** live overlay requires isRunning/isComposingMessage/isRetrying and awaitingUserResponse (nullable); optional isRunningTurn
(nullable), currentActivity, activeGroupMemberId, boxHandoff, runningSessionIds, awaitingSessionIds, workingTaskSessionIds, groupTurns
and lastTurnSettlement. Client overlay requires hasUnread/unreadCount; optional unreadThreadCount, lastViewedAt, lastActivityAt,
newestEntryId, lastMessageId, lastMessageTaskId, lastMessagePreview, lastMessagePreviewSource, lastMessageTaskPreviewSource, stateUpdatedAt, notifyOnUpdatesEnabled, isHiddenFromSidebar
and isRemovedFromSidebar. The last three are nullable booleans; times/counts are numbers, IDs/previews strings, and preview sources
structured records. Sources: **S `$defs.SandAgentLiveOverlay`, `$defs.SandAgentClientOverlay`**.

## 2. Transcript identity, kinds, and updates

**VERIFIED.** `seq?:number` and `id:string` are separate. Backend rows also have `updatedSeq`, and backend cursors contain `agentId`,
`sessionId`, `generation`, and `afterUpdatedSeq`. Coordinator state is keyed by agent plus session and tracks rows by seq within a
generation; a generation change clears that state. Renderer identity compares id and, when both are present, seq; it can hold multiple
rows with the same id. Sources: **P `GrokBotTranscriptCursor|`, `GrokBotTranscriptEntry|`; C `function Mt(n,e)`, `ae=(p,_,C,N)=>`,
`N&&ke({type:"cleared"`; R `function hh(e,t)`, `var bh=class`**.

**INFERRED:** the safe sequence scope is agent/session/generation, not a global counter. **UNKNOWN:** the writer's precise uniqueness
and reuse guarantees, including whether sessions share an allocator. Never merge bots by seq alone. Backend persistence source or
historical multi-session row captures would settle it.

**VERIFIED:** renderer message-link recognition accepts IDs shaped like `t12u`, `t12ua0`, `t12a3`, `t12s4`, `tbs4`, and `task-<10
lowercase hex>-t12s4` (also the task background form). It extracts the task ID from that last format. Sources: **R `var y8t=`, `var
Vve=`, `function Hve(e)`**. **INFERRED:** `t` identifies a turn, `u` user, `a` assistant, `s` send-message, and `b` background.
**UNKNOWN:** authoritative meanings of all numeric suffixes and every producer format; IDs are opaque strings in the schema. Producer
source would settle this; do not implement parsing as an identity requirement.

**VERIFIED — normal transcript kind union** (S `$defs.SandTranscriptEntry` and each named entry definition):

| Kind | Meaning and important fields |
|---|---|
| `message` | `role:user\|assistant`, `content:string`, `isStreaming:boolean`; optional author/fromUser/fromAgent/toAgent, attachments, taskId, replyTo/replyQuote, richText, clientNonce |
| `send-message` | Bot-delivered text, media, or interactive card: `message:SandSendMessage`; optional `streaming`, resolution and delivery fields |
| `tool-call` | `name:string`, `status:pending\|done\|failed`, `summary?:string` |
| `notice` | Informational/system text in `text:string` |
| `event` | Typed timeline event in `event:SandTimelineEvent` (membership, names, tasks, automations, channels, desktop goals, cloud-agent launch, sharing, development events) |
| `mcp-app` | Embedded tool application: serverIdentifier/serverName, resourceUri, toolCallId/toolName; optional arguments/result/document metadata/error |
| `feedback` | Turn or meeting feedback request; requestId, state, optional sentiment; meeting variant has meetingId |
| `user-attachment` | User-supplied file: file_path, optional file_name, dimensions, byteSize, author, clientNonce |
| `voice-call` | Call summary and optional conversation |

All normal variants have id, optional seq/timestampMs/reactions. Retained history additionally permits `spend-initiation` with agentId,
requestId, timestampMs, version=1 and initiation object; it is absent from the normal live union. There is no top-level `error`,
`system`, or `card` kind in that union. Errors also use tray events; card type is `send-message.message.type`. Sources: **S
`$defs.SandRetainedTranscriptPage`, `$defs.SandSpendInitiationEntry`, `$defs.SandErrorTray`, `$defs.SandSendMessage`**.

**VERIFIED:** nested message types are connector, text, bot-template-share, attachment, auto-review-approval, publish-approval,
cookie-origin-approval, meeting-join-consent, virtual-card-approval, connector-grant, local-tool-permission, cursor-agent,
mobile-tool-permission, calendar-event, phone-call, visualization, connectors, credential-request, email-draft, imessage-draft,
meeting-chat-draft, slack-draft, email-offer, user-form, scm-connect, permission-request, listener-connect, slack-connect, team-access,
secret-request, appearance-picker, notifications-enable, onepassword-connect, widget and app-secrets-request. Source: **S
`$defs.SandSendMessage`**.

**VERIFIED:** `updated` supplies a replacement entry, not a text delta. The coordinator emits it for a newer row version at an existing
identity, including replays. Relevant mutable fields include message content/streaming, tool status, approval status, respondedValue,
widgetDismissed/widgetSkipped, secretProvided, formResolution, credentialResolution and draftSendState. Sources: **C `ae=(p,_,C,N)=>`; S
`$defs.SandMessageEntry`, `$defs.SandSendMessageEntry`, `$defs.SandToolCallEntry`**.

## 3. Transcript paging and chat opening

**VERIFIED — argument/reply contracts** (S `methods.<command>` and the reply `$defs`):

| Command | Arguments | Reply |
|---|---|---|
| `getAgentTranscriptTail` | id:string, limit:number; beforeSeq?, sessionId?:string, unreadBoundaryAt?:number, background?:boolean\|null | TranscriptPage |
| `openAgentTail` | id, limit; sessionId?, unreadBoundaryAt? | TranscriptPage |
| `getAgentTranscriptPage` | id, limit, untilMs:number; beforeSeq?:number, sinceMs?:number | `{entries:retained-entry[],nextBeforeSeq?:number}` |
| `getAgentTranscriptWindow` | id, limit; beforeSeq? | `{entries:entry[],nextBeforeSeq?:number,threadCounts?:record<string,number>}` |
| `openAgentWindowed` | id, limit | Same window reply |
| `getAgentTranscript` | id | entry[] |

TranscriptPage is `{entries:entry[],nextBeforeSeq?:number,ordered?:OrderedStamp,
precedingTimestampMs?:number,cloudAgentPeerIds?:string[],unreadAnchor?:Anchor|null}`. Anchor is `{kind:none}` or
`{kind:at,entryId:string,newerRows:number,seq?:number}`. No listed gateway command accepts `afterSeq`; sessionId belongs only to the two
tail commands here. `unreadBoundaryAt` becomes backend `unreadBoundaryMs` and locates the unread boundary. Sources: **S
`$defs.SandTranscriptPage`, `$defs.SandTranscriptWindow`; C `uo=async(p,_)=>`, `fte=b(`, `Ste=b(`**.

**VERIFIED:** selecting a chat invokes `openAgentTail` with limit 500, current nonempty sessionId, and optional unreadBoundaryAt.
Scrolling back calls `getAgentTranscriptTail` with limit, beforeSeq and the same session; results are merged as older history and
advance nextBeforeSeq. Backend pages are reversed into chronological display order. Sources: **R `function Dqn(e)`,
`n.openAgentTail({id:e,limit:500`, `landedOlderPages+=1`; C `Ue=async(p,_)=>`**. **UNKNOWN:** exact window/retained-page server
filtering and all boundary inclusivity rules; gateway implementation or read-only paging captures would settle them.

## 4. Sessions, threads, and sending

**VERIFIED:** session kinds are MAIN, SLACK_DM, SLACK_THREAD, DM, GROUP, TEAMS_DM, TEAMS_THREAD and TEAMS_GROUP_CHAT (plus UNSPECIFIED).
They are routing contexts, not merely desktop tabs. `ListGrokBotAgentSessions` takes agentId and returns sessions containing
agentId/sessionId/kind/createdAtMs/updatedAtMs and optional lastActivityAtMs (backend int64 times). Sources: **P
`GrokBotAgentSessionKind`, `GrokBotAgentSession|`, `ListGrokBotAgentSessionsRequest|`**.

**VERIFIED:** empty/omitted session selects the default. `awaitingSessionIds` lists waiting contexts; awaitingUserResponse is
`{tabId:string,reason:string, since:number,reasonCopy?:SandAutoReviewAwaitingCopy}`. Live overlays separately carry runningSessionIds
and workingTaskSessionIds. Owner selection uses the chosen session when multiplayer sessions are enabled; otherwise default. A nonowner
uses their matching viewerSessionId. Task sessions use `task:<10-hex-taskId>` or `task:<taskId>:dm:<numeric-userId>`; group contexts
have `group:` prefix. Sources: **S `$defs.SandAgentSummary`, `$defs.SandAgentAwaitingState`; C `function gn(n)`; R `function Af(e)`,
`function jf(e)`, `function Uve(e)`, `var Sfe=`**. **INFERRED:** tabId is a historical routing label associated with the waiting
context; **UNKNOWN:** whether it always equals sessionId. A multi-context status/session capture or backend producer source would
establish that equality.

**VERIFIED:** `createThreadFromMessage({agentId,entryId})` returns null and maps to backend CreateGrokBotThreadFromMessage.
`getAgentThread({id,rootId})` returns `{entries:entry[]}`. Task/thread views and their read markers are separate from the default chat.
Sources: **S `methods.createThreadFromMessage`, `methods.getAgentThread`; M `case"createThreadFromMessage"`; R `openThread:e=>`**.

**VERIFIED — all sendPrompt fields** (S `$defs.SandSendPromptArgs`; C `var hB=`, `Ene=Dx`): only agentId:string and prompt:string are
required by the gateway. The backend action adapter additionally requires clientNonce.

- Optional strings: clientNonce, richText, replyToId, replyQuote, traceparent, mcpConfigJson, sessionId, machineId, taskId, language.
- Optional string arrays: attachmentPaths, attachmentNames.
- Optional numbers: enterEpochMs, composedAtMs, firstSentAtMs.
- Optional booleans or null: isFork, onePasswordAppInstalled, rendersMcpElicitationForms.
- Optional literal true: directAddressedAcceptance.
- Optional enums or null: automationWriteProvenance=`template_import|untrusted`;
  initiator=`card_action|plugin_setup|teach_recording|template_import|template_share|user`;
  sendSource=`action_button_dictation|app_intent|chat|push|unknown`; source=`desktop|mobile`.

Reply is `{accepted?:boolean|null}` or null, not the completed answer. The renderer journals the intended session/task, nonce and send
state and uses acceptance lookup/retry logic. Sources: **S `$defs.SandSendPromptResult`, `methods.promptAcceptanceStatus`; R
`sendJournal.sendPrompt(t)`, `sessionId:n,taskId:r`; C `sendDedupeProvenBaseUrls`**.

## 5. Agent roster and sidebar

**VERIFIED:** listAgents returns an array; agent-upserted wraps one identical SandAgentSummary. Complete field inventory below; `?`
applies to each name in its cell. Source for every row: **S `$defs.SandAgentSummary`**.

| Type | Fields |
|---|---|
| string, required | id, name, description, path |
| number, required | createdAt, updatedAt |
| boolean, required | hasUnread, isActive, isComposingMessage, isGroup, isRunning, notificationsEnabled, notifyOnUpdatesEnabled |
| string\|null, required | avatarDataUrl, lastMessageId |
| structured\|null, required | awaitingUserResponse:AwaitingState, lastEntry:Preview |
| string[], required | memberIds |
| string? | activeGroupMemberId, ownerDisplayName, serverId, slackWorkspaceName, snapshotEpoch, title, viewerSessionId, voiceLanguage |
| string\|null? | avatarColor, avatarShape, avatarVersion, lastMessageAuthorId, lastMessagePreview, lastMessageTaskId, newestEntryId, voiceId |
| number? | addedUserCount, lastActivityAt, lastViewedAt, localActivityAt, snapshotSeq, teamId, teamRank, unreadCount, unreadThreadCount, voiceSpeed |
| boolean\|null? | draftingDisabled, isAccessOwnerOnly, isHiddenFromSidebar, isRemovedFromSidebar, isRetrying, isRunningTurn, isTeamDefault, published, viewerCanManage, viewerIsOwner |
| true? | isAccessGrantsOnly |
| string[]? | awaitingSessionIds, runningSessionIds, workingTaskSessionIds |
| enums | origin:dev\|user (required); harness?:temporal; namedBy?:app\|user\|null; purpose?:disk-saver\|plugin-auth\|null; viewerAccess?:direct\|group\|team\|null; visibility?:owner\|team\|null |
| enums/arrays? | slackStatus?:connected\|declined\|needs_update\|none\|pending\|reconnect\|removed\|request_unsent\|null; viewerAllowedActions?:(manage_credentials\|share_in_place)[] |
| records? | currentActivity:SandAgentActivity; groupTurns:SandAgentGroupTurn[]; people:GrokBotRoomPerson[]; suggestions:SandAgentSuggestion[] |
| records\|null? | avatarPhoto:RosterPhotoReference; boxHandoff:SandBoxHandoffInfo; lastMessagePreviewSource:PreviewSource; lastTurnSettlement:SandTurnSettlement; pushMessageContent:SandPushMessageContentPayload |

Preview is text (text, optional authorId/sessionPreview), attachment (count, optional kind counts), link (url), or null. PreviewSource
discriminates rendered message/card summaries; preserve it rather than treating it as message text. Activity is
`{kind:thinking|tool,tool?:string,detail?:string,target?:string, callId?:string}`. Group turns contain roomId, isComposingMessage,
isRunningTurn? and currentActivity?. People contain displayName, isViewer, avatarPhoto, optional avatarDataUrl/userId. Sources: **S
`$defs.SandAgentActivity`, `$defs.SandAgentGroupTurn`, `$defs.GrokBotRoomPerson`, `$defs.RosterPhotoReference`**.

**VERIFIED:** working means no awaitingUserResponse and either running or composing; composing selects streaming presentation, awaiting
selects blocked/ needs-you. Unread uses hasUnread or positive unreadThreadCount; activity recency also uses lastViewedAt/lastActivityAt.
Hidden rows are filtered except special team-default rows. Pins and sidebar sections are settings, not fields on a row. Sources: **R
`function nm(e)`, `function tm(e)`, `function BE(e,t)`, `function JD(e)`, `function nQe(e)`, `function _m(e)`, `function vm(e,t)`,
`function ym(`; S `$defs.SandHostSettingsField`**.

## 6. Unread and read acknowledgement

**VERIFIED:** setAgentUnread takes id:string, isUnread:boolean, atMs?:number, markFollowedThreadsRead?:boolean|null; returns null. The
backend adapter calls SetGrokBotAgentClientState with markUnread or markRead, optionally markFollowedThreadsRead; it does not forward
atMs. Client overlay maps positive unreadCount to hasUnread and supplies unreadThreadCount/lastViewedAt/lastActivityAt. Sources: **S
`methods.setAgentUnread`; M `case"setAgentUnread"`; P `SetGrokBotAgentClientStateRequest|`; C `function h6(n)`**.

**VERIFIED:** opening a temporal/backend-hosted chat reads the tail and explicitly calls setAgentUnread with false; failure is returned
as coordinator-only isReadMarkFailed so the optimistic read mark can roll back. Computer-hosted opening invokes gateway openAgentTail,
including when a server tail is used beside it. Reselecting an unread bot calls setAgentUnread(false); explicit markAgentRead
additionally sets markFollowedThreadsRead=true. Sources: **C `mark read after an open failed`, `gateway openAgentTail beside the server
tail`; R `beginOptimisticMarkReadOnOpen`, `function lUn(e,t)`, `markAgentRead:e=>`**. **INFERRED:** gateway openAgentTail performs the
computer-hosted read side effect; the HTTP handler is absent, so this is not proof of its server implementation.

**VERIFIED:** markAgentTaskRead requires agentId/taskId/entryId strings, returns the task array, and clears that thread's optimistic
unread marker. Sources: **S `methods.markAgentTaskRead`; R `e.markAgentTaskRead({agentId:t,taskId:n,entryId:r})`**. **UNKNOWN:** full
server unread-increment policy (for example silent/background entries); backend state-update source would settle it.

## 7. Run control

**VERIFIED:** interruptAgentRun takes `{id,sessionId?}`, replies `{hadActiveRun:boolean}`, and backend dispatch uses reason
`user_interrupt`. The UI waits for running state to end after interrupting the relevant sessions. **INFERRED:** this stops the current
session's turn; it is not proof that every external tool/process is terminated synchronously. Sources: **S `methods.interruptAgentRun`;
M `case"interruptAgentRun"`; R `function fWt(`**.

**VERIFIED:** kickstartAgent takes `{id}` and returns `{isIntroductionInFlight:boolean}` or null; temporal agents short-circuit to
false. startFreshConversation and rollBackConversation each take `{id,sessionId?}` and return null; there is no gateway fromSeq
argument. UI fresh action is “Reset”; rollback is “Edit” and restores editable user text to the composer. Sources: **S
`methods.kickstartAgent`, `methods.startFreshConversation`, `methods.rollBackConversation`; C `O==="kickstartAgent"`; R
`data-sand-tray-action`, `"OfhWJH":`, `"ePK91l":`, `qjn(d.snapshotsFor`**. **UNKNOWN:** exact checkpoint, retained-memory, and
external-side-effect rollback semantics; backend/host implementation is needed, not a destructive live probe.

## 8. Groups and rooms

**VERIFIED:** createGroup requires name:string and memberAgentIds:string[]; optional description:string, humanMemberUserIds:number[],
namedBy:app|user|null, creationRoute:{kind:box}|{kind:temporal,scope:string}, clientNonce:string. Roster uses isGroup=true, memberIds,
optional people, activeGroupMemberId and groupTurns. Human membership has add/remove backend calls. Transcript author
envelopes/fromUser/fromAgent distinguish speakers; timeline events include bot and person membership changes. Sending targets the
group's agentId through the same sendPrompt contract. Sources: **S `methods.createGroup`, `$defs.SandAgentSummary`,
`$defs.SandMessageEntry`, `$defs.SandTimelineEvent`; M `addGrokBotRoomPeople`, `removeGrokBotRoomPeople`; R `isRoomAgent?.`**.

**VERIFIED:** no isSharedRoom property occurs in this gateway roster schema or the inspected renderer. Rooms with `people` can include
other humans; they are not limited to a collection of bots. Sources: **S `$defs.GrokBotRoomPerson`; R `function lm(e)`, `function
dm(e,t)`; M `humanMemberUserIds`**. **UNKNOWN:** compatibility meaning of an isSharedRoom flag from another version or service; obtain
that producer schema before using the flag. Group scheduling and simultaneous member-turn guarantees also require host/backend
implementation.

## 9. Gateway connection lifecycle

**VERIFIED:** EnsureSandBox accepts optional wake/supportsAsleepBox and returns gateway URL/token, pod identity/runState and computer
URLs/credentials. The app caches/reuses a live or recently healthy connection; discovering sleep clears that cache. Status 417 maps to
pod_hibernated. Person-triggered operations notify box intent, invalidate sleep state, re-resolve and retry through the wake path;
background demand has different policy. Sources: **P `EnsureSandBoxRequest|`, `EnsureSandBoxResponse|`; C `function Ea(n,e)`,
`noteBoxAsleep(){`, `async ensureConnection(e)`, `async dispatchAfterBoxFoundAsleep`; M `async ensureBox(t)`**.

**UNKNOWN:** whether minting a new EnsureSandBox connection invalidates an older token, or whether an idle open /events stream keeps the
pod awake. Neither is established by the client cache, wake path, or VNC resume hints. Backend token validation and
hibernation-accounting source would settle both. A separately authorized token-overlap test could settle the former; idle SSE/pod-state
observation could settle the latter. Neither was attempted here.

## 10. Desktop computer and VNC

**VERIFIED:** getForeverBoxStatus and ensureForeverBox take `{id:string}` and return status or null; updateForeverBox takes the same
args and returns status. handBackForeverBox takes id, optional requestId and trigger `button|dismissed|viewer-closed|null`, returning
null. Status and `forever-box` payload are `{agentId:string,state:absent|hibernated|running,vncUrl:string|null,
diskPressure?:{level:hard|soft},handoff?:{instruction:string,requestId:string}|null,
hostUpdateAvailable?:boolean|null,hostVersion?:string|null, imageUpdateAvailable?:boolean|null,pull?:{percent:number}|null,
windows?:{vncUrl:string,windowIndex:number}[]}`. Sources: **S `methods.getForeverBoxStatus`, `methods.ensureForeverBox`,
`methods.handBackForeverBox`, `methods.updateForeverBox`, `$defs.SandForeverBoxStatus`**.

**VERIFIED:** vncUrl is a browser-viewer URL, not raw RFB bytes or an image URL; the coordinator constructs/rewrites `/vnc.html` URLs
with a websockify path and proxy credentials. The desktop uses an Electron webview for previews and interactive viewing, with monitor
selection and RFB lifecycle notifications. Sources: **C `function BB(`, `function _z(`;
`dist/renderer/assets/chunk-box-desktop-modal-Cnkd1G6L.js` search `src:n.vncUrl`;
`dist/renderer/assets/chunk-teach-recording-controls-zngo9SRz.js` search `rfb_connect` and `webview`**. **UNKNOWN:** whether arbitrary
terminal VNC clients can use this URL unchanged; proxy/RFB connection details need separate research.

## 11. Tool and progress display

**VERIFIED:** three sources coexist: roster/live `currentActivity` (thinking or tool, optional tool/detail/target/callId); `outline`
items (thinking text and optional durationMs, user text, assistant-text, send-message, tool-call); and transcript tool-call entries with
pending/done/failed. Streaming messages have isStreaming or streaming. Subagents supply subagentId/type/title/status (aborted|done|error|running)/
startedAtMs/freshUntilMs?; async tasks supply id/kind/label/startedAtMs, status=running plus optional detail/subagentType/localization
metadata. Sources: **S `$defs.SandAgentActivity`, `$defs.SandConversationOutlineItem`, `$defs.SandToolCallEntry`,
`$defs.SandSubagentInfo`, `$defs.SandAsyncTaskInfo`; R `"agent-activity":e=>`, `outline:e=>`, `subagents:e=>`**. **INFERRED:** a TUI
should present activity independently of new chat messages; busy is not equivalent to a growing transcript or a pending tool-call row.

## 12. Other main-view/sidebar dependencies

**VERIFIED:** ordered replicas, unread anchors, deletion/clear events, restored history, optimistic sends/reactions, acceptance lookup,
session/task selection, and transport recovery affect correctness. Pin order/sidebar sections come from host/backend user settings.
Access/ownership/team gates affect row visibility and actions. Rich cards, attachments, MCP apps, diagrams/visualizations, voice, tasks,
error trays, and computer handoffs are separate presentation surfaces. Sources: **S `$defs.OrderedStamp`, `$defs.SandHostSettingsField`,
`$defs.SandSendMessage`, `$defs.SandErrorTray`; R `je.noteTranscriptEvent(e)`, `transcript.replicas`, `sendJournal.sendPrompt(t)`,
`function Af(e)`**.

**VERIFIED:** desktop routing includes backend-hosted temporal agents and WatchGrokBotTranscripts alongside gateway events; not every
renderer event comes from /events. Backend stream rehydration can synthesize transcript snapshots/ updates and roster resync. Some card
operations route to backend RPCs. Sources: **P `WatchGrokBotTranscriptsRequest|`; C `server transcript tail falling back`,
`onTurnFailed:`, `server-roster-changed`; M `case"respondToWidget"`**. **UNKNOWN:** complete feature parity from gateway-only access;
server-side capability/permission behavior requires its implementation or authorized captures.

## Changes since 0.72

**VERIFIED comparison with repository `docs/protocol-0.72.md`:** the earlier note covered a small command subset, not the full UI. This
audit establishes 29 declared SSE channels, ordered replicas, session-aware tail routing, read acknowledgement and richer roster state.
Fields absent from its send list but present in 0.77 are replyQuote, language and rendersMcpElicitationForms. Sources: **S `events`,
`$defs.SandAgentSummary`, `$defs.SandSendPromptArgs`**. These are newly documented differences, not proof of introduction after 0.72.

The earlier note's gateway answer commands should not be taken as the current desktop routing model: 0.77 has backend action dispatch
and transcript watching, and current `gbot/protocol.py` already lists backend answer RPCs. Preserve that distinction. Sources: **M
`case"resolveAutoReviewApproval"`, `case"submitUserForm"`; P `WatchGrokBotTranscriptsRequest|`**. **UNKNOWN:** exact release-by-release
additions without the 0.72 bundle/schema.

## Live observations (read-only capture, 2026-10-30)

A 150-second read-only capture against one account (shapes only; no content kept) settled some UNKNOWNs above:

- `/events` with no `channels` query delivers every channel (a `box-disk-pressure` frame arrived unasked). The
  server sends `retry: 1000` once, then a `:ping` comment every 15 seconds, so an idle stream never reaches a
  120-second read timeout and the client's 35-second stall watchdog is satisfied by pings alone.
- `listAgents` rows carried the summary fields in section 5, including `hasUnread`, `unreadCount`, `lastViewedAt`,
  `lastActivityAt`, `lastMessagePreview`, `lastEntry`, `isRunningTurn`, `isRetrying`, `lastTurnSettlement` and the
  avatar fields; groups had `memberIds` of 3 and 4 bots. No row had `isSharedRoom`.
- `getAgentTranscriptTail {id, limit: 100}` returned `entries`, `nextBeforeSeq` and `precedingTimestampMs`. In the
  default session `seq` rose strictly with gaps; ids followed `t<n>u` (user) and `t<n>s<k>` (bot steps). User
  entries are `kind: message` with top-level `role`, `content`, `clientNonce` and `isStreaming`.
- Read commands that need a bot take `id` except `getAgentTasks` (`agentId`), `getBotTemplateForSourceAgent`
  (`sourceAgentId`) and `getAgentThread` (`id`, `rootId`); transcript reads require `limit`.
