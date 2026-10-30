# M2 reply shapes and desktop behaviour: Grok Bot 0.77.0

Offline, read-only research of `_bundle-077`; no live service or private configuration was read. Only this document was written.
These are interface observations in our own words, not a supported API contract. **VERIFIED** means code/schema evidence;
**INFERRED** means interpretation; **UNKNOWN** means the supplied client does not settle the question. Schema evidence proves the
declared shape, not that every deployed server produces it. The supplied empty-list probes do not verify item shapes.

Notation: `?` = optional, `null` = explicitly nullable, `[]` = array, `record<K,V>` = map. IDs/text are strings and gateway times,
counts and dimensions are numbers. Backend protobuf int64 values are called `int64` (bigint in generated JS; decimal strings in
protobuf JSON), bytes are byte arrays (base64 in protobuf JSON). Backend message-valued fields may be absent.
`Entry` and `Agent` mean the transcript and roster shapes in [protocol-tui.md](protocol-tui.md) sections 2 and 5.
`ActionRefusal` below means `{failureCode:string,message:string}` (VERIFIED: **P `GrokBotHarnessRefusal|`**).

All citations below are paths **relative to the bundle root**, followed by a short search string:

- **C** = `dist/node-agent-coordinator/main.cjs`.
- **M** = `dist/electron-main/main-app.cjs`.
- **P** = `dist/electron-main/proto.cjs`.
- **R** = `dist/renderer/assets/index.eager-app-BtIHj2If.js`.
- **S** = C, search `async function are()`: decode the adjacent `wz` base64/raw-DEFLATE value in memory to obtain the gateway schema.
  A citation such as **S `$defs.SandAgentTask`** is an exact key/search in that decoded schema; `methods.<name>` identifies the
  command. This extra decoding step is necessary: the definition names are not plaintext in the compressed value.
- **A/name** = `dist/renderer/assets/name`, with the search string following it.

## 1. Threads

**VERIFIED — replies:** `createThreadFromMessage({agentId,entryId})` returns `null`; `getAgentThread({id,rootId})` returns
`{entries:Entry[]}`. There is no returned thread ID/session ID or metadata on either reply. Window replies alone optionally include
`threadCounts:record<string,number>`; see protocol-tui section 3 for the other fields. Sources: **S `methods.createThreadFromMessage`,
`$defs.SandAgentThread`, `$defs.SandTranscriptWindow`**.

**VERIFIED — entry representation:** normal message entries have `taskId?:string`, `replyTo?:string`, `replyQuote?:string`;
send-message entries have `replyTo?:string`, and their nested messages can have `task_id?:string`. The entry schemas do not declare
`rootId`, `threadRootId`, `threadCount` or `threadCounts` on individual rows. The roster/client overlay has
`unreadThreadCount?:number`. Sources: **S `$defs.SandMessageEntry`, `$defs.SandSendMessageEntry`, `$defs.SandSendMessage`,
`$defs.SandAgentSummary`, `$defs.SandAgentClientOverlay`**.

**VERIFIED — the implemented desktop thread list is the agent-task list:** the sidebar thread store fetches `getAgentTasks`,
tracks pins/unread entry IDs, and opens `{agentId,taskId,focusEntryId?}`. Opening refreshes tasks; closing clears the selected task.
The thread transcript uses `fh(taskId,{parentSessionId})`, producing `task:<id>` or `task:<id>:<parentSessionId>`, and retains/loads
that session through the regular transcript store. Thus this task-thread view has its own session, as described in protocol-tui
section 4. Sources: **R `openThread:e=>`, `readSidebarThreadRows:`, `function fh(`, `function Gh(`, `function wye(`**.

**UNKNOWN — older root-thread semantics:** no desktop invocation of `getAgentThread` or consumption of `threadCounts` was found.
The map's key meaning, inclusion of the root row, relation to modern task threads, and whether that older representation has a
separate session cannot be established from those schemas. `createThreadFromMessage` returning null is not proof of no session.
Settle with gateway producer source or a capture before/after creating a thread, including tasks, windows, thread read and sessions.

## 2. Attachments

**VERIFIED — gateway contracts** (all fields below required unless marked optional). Sources for this table: **S
`methods.uploadAttachment`, `methods.uploadAttachmentChunk`, `methods.readAttachmentText`, `methods.readAttachmentChunk`,
`methods.readAttachmentImage`**, and their named definitions.

| Command | Reply and identifying fields |
|---|---|
| `uploadAttachment` | `{path:string}`; uploaded path is the result identity, not an upload token |
| `uploadAttachmentChunk` | `{committedPath:string\|null}`; caller supplies `uploadId:string`, filename, offset:number, totalSize:number, bytesBase64:string; null is not a final path |
| `readAttachmentText` | `null` or `{kind:binary,bytes:number}` or `{kind:text,bytes:number,text:string,truncated:boolean}`; bytes describes file size |
| `readAttachmentChunk` | `null` or `{bytesBase64:string,mime:string\|null,totalSize:number,resolvedName?:string}` |
| `readAttachmentImage` | `null` or `{dataUrl:string,width:number\|null,height:number\|null,scale?:number}` |

**VERIFIED — upload behaviour:** the box commit path first tries chunking, even for files smaller than a chunk; each read is at most
4 MiB. It generates a UUID `uploadId`, sends increasing byte offsets, and returns the first non-null `committedPath`. If the chunk
method is unsupported it falls back to one base64 `uploadAttachment`. Both accept optional agentId and `storeSized?:boolean|null`.
The latter lets the box accept the larger store-oriented size class during double writes. Desktop validation rejects empty files;
box limits are 25 MiB normally and 200 MiB for recognized video extensions; store-oriented limits are 25 MiB for images,
250 MiB for other files and 1 GiB for videos. These are client limits, not proof of every server limit. Sources: **M
`async function W(oe,K,he,te)`, `async function $(oe,K,he)`, `var kae=4*1024*1024`, `function SA(`, `function q4(`, `function K4(`;
S `$defs.SandUploadAttachmentArgs`, `$defs.SandUploadAttachmentChunkArgs`**.

**VERIFIED — sending:** `sendPrompt` uses committed paths or completed store aliases in `attachmentPaths:string[]`, with original
display names in the corresponding `attachmentNames:string[]`. It does not send uploadId/uploadToken as an attachment path.
Staging/commit precedes sending; protocol-tui section 4 describes the remaining send arguments. Sources: **M
`commitStagedAttachments`, `attachmentPaths:[...o.attachmentPaths`, `kind:"store",alias:`; R `attachmentPaths:t.attachmentPaths`**.

**VERIFIED — transcript references:** user files are `kind:user-attachment`, `file_path:string`, optional file_name:string,
width/height/byteSize:number, secondaryText:string, replyTo/replyQuote:string (common identity/author fields: protocol-tui section 2).
Normal messages and send-message entries can carry `attachments?:{url:string,byteSize?:number}[]`; normal messages also have
`images?:{url:string,alt?:string,width?:number,height?:number}[]`. A bot attachment is
`message:{type:attachment,url:string,file_name?:string,source_path?:string,alt?:string,width?:number,height?:number,
channel?:string,reply_to?:string,task_id?:string}`. Image/video/file classification is media resolution, not separate transcript
entry kinds; search-media kinds are in section 4. Sources: **S `$defs.SandUserAttachmentEntry`, `$defs.SandMessageAttachment`,
`$defs.SandSendMessageImage`, `$defs.SandMessageEntry`, `$defs.SandSendMessage`**.

**VERIFIED — image variants:** `rendition` is `preview|original|null` (optional); tile and fit are optional strings in the schema,
but the argument validators narrow them: `tile-<N>` with N=16..1024, `fit-<N>` with N a multiple of 256 up to 8192.
Tile selects preview, fit selects original. Image helpers calculate tile thumbnails using the shorter edge with a 1024-pixel
longer-edge ceiling, and fit dimensions using the longer edge without upscaling; preview processing also halves dimensions.
`scale` is optional rendition metadata, not another upload identifier. Sources: **M `function rre(`, `function ore(`,
`function d2e(`, `function l2e(`, `function SR(`, `function s2e(`; S `$defs.ResolvedImageAttachment`**.
**UNKNOWN:** exact remote resampling/cropping/scale conventions require the image-serving implementation or paired rendition reads.

**VERIFIED — backend store uploads are a different protocol:** the desktop tries Begin, uploads to signed HTTP targets, then Complete;
Abort abandons a session. Begin can choose USE_BOX, SINGLE_PUT, MULTIPART or REFUSED. Multipart part size/count come from Begin;
they are not the gateway's 4 MiB chunk rule. Complete returns the alias used for sending. Sources: **M
`beginGrokBotAttachmentUpload({`, `case A.GrokBotAttachmentUploadMode.MULTIPART`, `completeGrokBotAttachmentUpload`,
`abortGrokBotAttachmentUpload`; P `GrokBotAttachmentUploadMode`**.

| Backend RPC | Request → reply (VERIFIED, P search each `<RPC>Request` / `<RPC>Response`) |
|---|---|
| `BeginGrokBotAttachmentUpload` | agentId:string, sessionId?:string, fileName:string, sizeBytes:int64, supportsStoreAttachmentRefs:boolean, supportsMultipart:boolean, sha256Hex?:string → mode:enum, useBoxReason:string, refusal:enum, limitBytes:int64, uploadToken:string, sessionExpiresAtMs:int64, put?:Target, partSizeBytes:int64, partCount:number |
| `CompleteGrokBotAttachmentUpload` | uploadToken:string → refusal:enum, limitBytes:int64, alias:string, fileName:string, sizeBytes:int64, contentType:string |
| `AbortGrokBotAttachmentUpload` | uploadToken:string → empty response |

**VERIFIED:** Target is `{url:string,headers:record<string,string>,expiresAtMs:int64}`. Refusals are UNSPECIFIED, TOO_LARGE,
AGENT_FULL, EXPIRED, INCOMPLETE, SIZE_MISMATCH, NOT_AN_IMAGE, TARGET_CHANGED, UNSUPPORTED_TYPE. Sources: **P
`GrokBotAttachmentUploadRequestTarget|`, `GrokBotAttachmentUploadRefusal`**.

## 3. Reactions and feedback

**VERIFIED:** `reactToMessage({agentId,entryId,emoji,sessionId?})` returns null. Emoji is an unrestricted string in the declared
contract; there is no small allowlist. The desktop picker loads emojibase data. Reactions on entries are
`reactions?:{by:string,emoji:string,name?:string}[]`. The desktop selects one reaction per reacting identity; tapping its current
emoji sets the desired reaction to null and sends that same emoji again, i.e. toggle-to-remove. It updates optimistically, waits
for an echo, and can reread after failure. Sources: **S `methods.reactToMessage`, `$defs.SandReaction`; R `function Qve(`,
`function Th(`, `function Ah(`, `function pye(`, `function EBt(`**.
**INFERRED:** a direct repeated gateway call has the same toggle semantics; the backend/host producer is needed to prove it under
retries/concurrency. Do not treat repeated calls as idempotent.

**VERIFIED:** `voteFeedback` returns null; required agentId/entryId:string and action=`up|down|submit|revert`, optional
sessionId:string, categories:string[], comment:string. Categories are not an enforced gateway enum. The turn-feedback UI offers
`not_what_i_asked`, `inaccurate`, `low_quality`, `too_slow`; submit carries the chosen categories/comment and revert resets the form.
It is offered on transcript feedback prompts, including a separate meeting variant with thumbs and comment flow. Prompt state is
`prompt|improve|voted`, sentiment optional `up|down|null`; meeting prompts also carry meetingId:string. Sources: **S
`methods.voteFeedback`, `$defs.SandFeedbackPromptState`, `$defs.SandTurnFeedbackPromptEntry`, `$defs.SandMeetingFeedbackPromptEntry`;
A/chunk-view-BBReUFja.js `not_what_i_asked`, `voteFeedback`, `data-meeting-feedback`**.

## 4. Search

**VERIFIED — replies:** `searchAgents` returns `{agentId:string,entryId:string,role:user|assistant,snippet:string,timestampMs:number}[]`;
despite its name these are message matches. `searchMedia` returns `{agentId:string,entryId:string,ext:string,fileName:string,
height:number|null,width:number|null,kind:MediaKind,mime:string|null,timestampMs:number}[]`. MediaKind is
`archive|audio|document|file|image|json|markdown|pdf|table|text|video`. Both take query:string, limit?:number. The desktop's search
overlay has separate message/media stores; message search suppresses blank queries and media search allows them. Sources: **S
`methods.searchAgents`, `methods.searchMedia`, `$defs.SandMessageMatch`, `$defs.SandMediaMatch`; R `function rAn(`,
`function iAn(`, `n.messageSearch.setQuery`**.

**VERIFIED:** `SearchGrokBotPlacesArea` searches a map region for an existing places card, not conversation text. Request:
agentId/entryId/sessionId/language:string, cardIndex:number, area?:{southWest?:LatLng,northEast?:LatLng};
LatLng={latitude:number,longitude:number}. Reply: `{outcome:enum,placesCardJson:string}`; outcomes UNSPECIFIED, FOUND, EMPTY,
UNAVAILABLE, FAILED, RATE_LIMITED, NOT_SEARCHABLE. The adapter invokes this RPC for `searchPlacesArea` and parses its card result.
Sources: **P `SearchGrokBotPlacesAreaRequest|`, `SearchGrokBotPlacesAreaResponse|`, `GrokBotPlacesSearchArea|`,
`GrokBotPlacesAreaSearchOutcome`; M `case"searchPlacesArea"`**.

**VERIFIED — declared per-conversation search:** `searchConversation({agentId,query,beforeSeq?,limit?})` returns
`{isComplete:boolean,matches:{entryId:string,role:user|assistant,seq:number,snippet:string,timestampMs:number}[]}`.
Sources: **S `$defs.SandConversationSearchArgs`, `$defs.SandConversationSearchResult`, `$defs.SandConversationMatch`**.
**UNKNOWN — desktop UI:** no renderer call site for searchConversation was found; the verified overlay uses searchAgents/searchMedia.
A command declaration does not establish an in-chat Find UI, client-side transcript filtering, or keyboard shortcut. Settle with a
UI capture while invoking Find in a conversation, or renderer source identifying the handler. No search service was probed.

## 5. Tasks, todos, suggestions and unread threads

**VERIFIED — replies:** each get command returns an array of the corresponding record below. All task mutation commands return
`AgentTask[]` too, not null or a single changed row. Sources: **S `methods.getAgentTasks`, `methods.getAsyncTasks`,
`methods.getSubagents`, `methods.getAgentTodos`, `methods.markAgentTaskDone`, `methods.markAgentTaskRead`,
`methods.setAgentTaskPinned`**.

| Record | Complete field inventory (VERIFIED; S definition named in first column) |
|---|---|
| `SandAgentTask` / AgentTask | id/name/description:string, status:open\|done, updatedAtMs:number; followed?:boolean\|null, pinnedAtMs?:number, subagentIds?:string[], unreadAtMs?:number, unreadEntryId?:string, unreadPreview?:string |
| `SandAsyncTaskInfo` | id:string, kind:cloud-agent\|shell\|subagent, label:string, startedAtMs:number, status:running; detail?:string, subagentType?:string, detailKind?:durable_pending_wake_ledger\|reattached_after_host_restart\|null, detailParams?:{subagentType?:string}, labelKind?:background_command\|background_task\|cloud_agent\|null, labelParams?:{id:string} |
| `SandSubagentInfo` | subagentId/subagentType/title:string, startedAtMs:number, status:aborted\|done\|error\|running, freshUntilMs?:number |
| `SandAgentTodo` | id/content:string, status:cancelled\|completed\|in_progress\|pending, updatedAt:number |

**VERIFIED — UI mutations:** Done marks the matching task done and updates its time optimistically, closing an open thread for it.
Read takes agentId/taskId/entryId and clears unreadEntryId/unreadPreview/unreadAtMs only for the matching unread entry.
Pin takes agentId/taskId/isPinned:boolean and updates the pinned-thread store. Replies reconcile the task list; failures refresh it.
These UI operations do not mean deleting a transcript or stopping a run. Sources: **R `markDone:async(`,
`e.unreadEntryId!==r`, `setAgentTaskPinned({`, `pinnedThreadSnapshots:`**.
**UNKNOWN:** exact server retention of recently-done rows, read race rules, and pin timestamp policy need producer code or paired
mutation captures. The backend adapter requests `includeRecentlyDone:true`; **M `case"getAgentTasks"`**.

**VERIFIED:** `dismissAgentSuggestions({agentId,suggestionIds:string[],reason:acted|hidden})` returns null.
Roster `suggestions?:{id:string,title:string,detail:string,prompt:string,icon:bell|calendar|chart|mail|people|search|sparkle|sun}[]`.
The renderer passes dismissal through its roster source. Sources: **S `methods.dismissAgentSuggestions`,
`$defs.SandAgentSuggestion`; R `dismissAgentSuggestions:e=>`**. **INFERRED:** acted distinguishes using a suggestion from hiding it;
exact generation/reappearance policy is UNKNOWN and requires producer source or a suggestion-interaction capture.

**VERIFIED — views:** tasks are sidebar thread rows and a task transcript header with name, description, unread state and pin/done
actions (section 1). Async tasks have a separate panel with kind-specific icons, label and localized detail; subagents are tabs in
the outline panel, labeled with type/title and status. Sources: **R `data-task-thread-back-button`, `function tat(`,
`function Zit(`, `function Kit(`, `function Bsn(`, `function zsn(`, `function Lsn(`**.
**UNKNOWN — todos UI:** getAgentTodos has a schema but no desktop invocation/view was found. Do not equate todos with task threads.
Settle with a UI capture showing a todo list or its renderer implementation. Task session routing is protocol-tui section 4 and
section 1 above; the task's id, rather than a todo id or async-task id, is passed to `fh` (**R `function Gh(`**).

## 6. Conversation outline

**VERIFIED:** `getConversationOutline({id})` returns OutlineItem[]. Each has id:string and kind; remaining fields by variant:
thinking: text:string,durationMs?:number; user: text:string,hidden?:boolean|null,steer?:boolean|null,timestampMs?:number;
assistant-text: text:string; send-message: message:SandSendMessage,timestampMs?:number;
tool-call: name:string,status:done|failed|pending,summary?:string. These expand the kinds in protocol-tui section 11.
Source: **S `methods.getConversationOutline`, `$defs.SandConversationOutlineItem`**.

**VERIFIED:** the desktop presents a separate expandable, virtualized outline panel, with parent and subagent tabs; selecting a tab
reads that subject's outline. Running subagent tabs request a refresh interval; outline events also update the store.
Sources: **R `function Bsn(`, `function Psn(`, `sand-outline-panel__tabs`, `outline:e=>Ae.ingest(e)`**.

## 7. Groups and rooms

**VERIFIED — gateway replies:** createGroup returns `{agent:Agent,transcript:Entry[]}`; setGroupMembers returns `Agent|null`.
Arguments/roster basics are already in protocol-tui section 8. Sources: **S `methods.createGroup`, `$defs.SandCreateAgentResult`,
`methods.setGroupMembers`**.

| Backend RPC | Request → reply (VERIFIED; P search `<RPC>Request` / `<RPC>Response`) |
|---|---|
| `CreateGrokBotRoom` | agentId/name/description:string, memberAgentIds:string[], humanMemberUserIds:number[] → `{agent?:GrokBotAgent}` |
| `SetGrokBotRoomMembers` | agentId:string, memberAgentIds:string[] → `{agent?:GrokBotAgent}` |
| `AddGrokBotRoomPeople`, `RemoveGrokBotRoomPeople` | agentId:string,userIds:number[] → `{agent?:GrokBotAgent}` |
| `ReadGrokBotGroupChatCanvas` | groupChatId/storeId/canvasId:string → `{renderBundleGzip:bytes,dataJson?:bytes,assets:CanvasAsset[],visualizationRuntimes:RuntimePin[]}` |
| `ReadGrokBotGroupChatDocument` | groupChatId/storeId/documentId:string → `{content:string,assets:{name:string,url:string,expiresAtMs:int64}[]}` |

**VERIFIED:** CanvasAsset fields are name/url/contentType/placeholder/etag:string, expiresAtMs/sizeBytes/expiresInMs:int64,
width/height:number, previews:{width:number,url:string,contentType:string,sizeBytes:int64}[]. RuntimePin={name:string,sha256:string}.
GrokBotAgent is the backend roster message, not the gateway Agent object (conversion applies); its full base inventory is outside
this reply supplement. Sources: **P `GrokBotGroupChatCanvasAssetUrl|`, `CanvasAssetPreview|`, `CanvasVisualizationRuntimePin|`,
`GrokBotAgent|`; M `createGrokBotRoom({`**.

**VERIFIED — route choice:** box creation uses createGroup. A temporal creation route uses CreateGrokBotRoom with clientNonce as
agentId; the desktop adapter checks that returned identity and seeds an empty transcript. Human membership requires server room
creation; a box route with humans is rejected. Without explicit routing/nonce/humans, a group containing a non-temporal member can
take the box path. setGroupMembers uses SetGrokBotRoomMembers for temporal rooms, gateway for box rooms. Human add/remove always use
the desktop backend RPCs. Group-shared canvas/document reads use the room RPCs, carrying groupChatId rather than treating the viewer
as store owner. Sources: **C `if(Q.method==="createGroup")`, `let Ne=HK(Q.method)`; M `createGrokBotRoom({`,
`setGrokBotRoomMembers({`, `readGrokBotGroupChatCanvas(`, `readGrokBotGroupChatDocument(`; R `addGroupPeople:`, `removeGroupPeople:`**.

**VERIFIED — display:** memberIds resolves bot roster rows; people represents humans, with displayName:string,isViewer:boolean,
avatarPhoto:photo-reference|null, userId?:number,avatarDataUrl?:string. Member-management UI removes bots via setGroupMembers and
humans via removeGroupPeople. Each bot can carry `groupTurns?:{roomId:string,isComposingMessage:boolean,
isRunningTurn?:boolean|null,currentActivity?:Activity}[]`. The renderer matches roomId to the open group and derives typing,
working or reading phases; activeGroupMemberId is a fallback. Sources: **S `$defs.GrokBotRoomPerson`, `$defs.SandAgentGroupTurn`;
R `d.roster.removeGroupPeople`, `function Gsn(`, `function Wsn(`, `function Xsn(`**.

## 8. Remaining cards and app-dependent requests

**VERIFIED — connector grant:** send-message.message has `{type:connector-grant,ask:Grant,task_id?:string}`.
Grant={requestId/serverId/serverName:string,status:allowed|expired|pending|skipped,interrupted?:true,
interruptedBy?:{name:string},remembered?:all_team_bots|this_bot|null}. Gateway resolveConnectorGrant takes agentId/entryId/requestId,
resolution=`allowed|skipped|always_this_bot|always_all_team_bots`, sessionId? and returns null. The backend twin returns
`{dispatched:boolean,workflowId?:string,refusal?:ActionRefusal}`; enum values are 1 ALLOWED, 2 SKIPPED, 3 ALWAYS_THIS_BOT,
4 ALWAYS_ALL_TEAM_BOTS, 5 ALLOW_IN_CHANNEL (0 UNSPECIFIED). Value 5 is not accepted by the gateway schema. The card uses the source
resolver, with sessionId and waiting-on-user gating; it offers one-time/remembered allowance and skip. No browser/passkey is needed
by this grant card itself. Sources: **S `$defs.SandConnectorGrantAsk`, `methods.resolveConnectorGrant`; P
`ResolveGrokBotConnectorGrantResponse|`, `GrokBotConnectorGrantResolution`; A/chunk-view-B8GCqrjM.js `always_this_bot`, `skipped`**.

**VERIFIED — Messages grants:** this is event `{requestId:string,grants:(automation|contacts|fullDiskAccess)[]}`, not a declared
send-message card type. The app opens its Messages helper. It checks machine permissions, opens native permission flows/settings,
and calls resolveMessagesGrants({requestId}) when satisfied or when closing an unresolved helper; there is no approve/deny enum.
Resolve/cancel return null; requestMessagesGrants and awaitMessagesGrants return `{kind:pending}` or
`{kind:refused,message:string,reason:aborted|no-desktop|unavailable}` or `{kind:settled,via:expired|resolved}`.
Sources: **S `events.messages-grants`, `$defs.SandMessagesGrantsGatewayReply`, `methods.resolveMessagesGrants`,
`methods.cancelMessagesGrants`; R `"messages-grants":e=>ct.openHelper(e)`, `e.source.resolveMessagesGrants({requestId:t})`;
M `messages/automation-prompt-unavailable`**. **INFERRED:** a terminal resolver alone cannot grant macOS privacy permissions;
the helper/OS interaction remains necessary. No backend ResolveMessagesGrants twin was found in parity.

**VERIFIED — virtual-card approval:** message={type:virtual-card-approval,approval:Approval,task_id?:string}.
Approval requires requestId/title/context/currency/merchantName/merchantUrl:string,amountCents:number,lineItems:LineItem[],
status:approved|denied|expired|failed|pending; optional spendRequestId/failureReason:string,flights:Flight[],shipTo:{name,address:string}.
LineItem={label:string,amountCents:number,imageUrl?:string,quantity?:number,kind?:discount|fee|item|shipping|tax|null}.
Flight={arrivesAt/departsAt/destination/flightNumber/origin:string,durationMinutes:number,
airlineLogoUrl?:string,operatedBy?:string}. Sources: **S `$defs.SandVirtualCardApproval`, `$defs.SandVirtualCardLineItem`,
`$defs.SandVirtualCardShipTo`, `$defs.SandVirtualCardFlight`**.

**VERIFIED — resolutions:** gateway resolveVirtualCardApproval accepts approved|denied|expired|failed and returns null; optional
spendRequestId/failureReason/paymentMethodId:string,attestation:{challengeId:string},payAnotherWay:boolean|null.
The desktop backend action accepts only approved|denied (protobuf 1/2); request has agentId/entryId/requestId, optional
paymentMethodId and attestation, payAnotherWay:boolean. Reply has outcome enum, spendRequestId/approvalUrl/message?:string,
refusal?:ActionRefusal,enrolledCredentialIds:string[]. Outcomes map to approved, denied, needs_auth, needs_passkey, failed; the
adapter splits needs_passkey with no enrolled IDs into needs_enrollment. The UI lists payment methods, begins spend approval,
can run a passkey ceremony, can open approvalUrl and offers pay-another-way. This needs app/browser/payment/passkey capabilities
when required, not a blind gateway approval. Sources: **S `methods.resolveVirtualCardApproval`; P
`ResolveGrokBotVirtualCardApprovalRequest|`, `ResolveGrokBotVirtualCardApprovalResponse|`, `GrokBotVirtualCardOutcome`;
M `function mQn(`; A/chunk-view-CL36--X8.js `grok_bot_spend_approval_passkey`, `payAnotherWay`, `beginSpendApproval`**.

**VERIFIED — credentials:** message={type:credential-request,credentialRequest:Request,reply_to?:string,task_id?:string}.
Brokered Request requires kind:brokered-login,accessRequestId/appLink/goal:string,requestedAtMs/expiresAtMs:number,
entries:{entryId,reason,website:string}[]; reusedEntries? has the same shape. Browser Request requires kind:browser-login,
catalogRevision/connectionId/credentialId/purpose/targetSite:string,requestedAtMs/expiresAtMs:number; optional
autoFill:boolean|null,targetWebSocketDebuggerUrl:string. Entry credentialResolution? is approved|denied|failed|filling|retryable|null.
Sources: **S `$defs.SandCredentialRequest`, `$defs.SandBrokeredCredentialRequest`, `$defs.SandBrowserLoginCredentialRequest`,
`$defs.SandBrokeredAccessRequestEntry`, `$defs.SandSendMessageEntry`**.

**VERIFIED — credential answer paths differ:** ResolveGrokBotCredentialRequest takes agentId/entryId/sessionId:string,
resolution=1 APPROVED or 2 DENIED (0 UNSPECIFIED), replies `{accepted:boolean,refusal?:ActionRefusal}`. An internal desktop action
resolveCredentialRequest maps approved/denied to it and yields null on acceptance, but this command is absent from S.methods.
The current card instead opens brokered requests in 1Password app/browser, and browser-login uses ApproveOnePasswordCredentialRequest
or DenyOnePasswordCredentialRequest through desktop credentials.approve/deny: entryId/agentId:string,harness:enum, plus
credentialId/connectionId/catalogRevision/targetSite:string for approval. The desktop result is `{ok:boolean,detail?:string}`.
Do not assume the generic resolver performs credential filling. Sources: **M `approveOnePasswordCredentialRequest(`,
`denyOnePasswordCredentialRequest(`; P `ResolveGrokBotCredentialRequestRequest|`, `ResolveGrokBotCredentialRequestResponse|`,
`GrokBotCredentialRequestResolution`; M `case"resolveCredentialRequest"`; A/chunk-view-EojBDPbS.js
`approveOnePasswordInBrowser`, `onepassword://`, `credentialId:r.credentialId`**.
**UNKNOWN:** the complete platform/1Password prerequisite matrix and generic resolver compatibility require credential-provider
source or an authorized app capture of each credential kind. No credential material was read.

**VERIFIED — user-computer is not one extra card kind:** local operation consent uses message.type=local-tool-permission,
ask={action:enum,requestId/target:string,status:enum,description?/machineId?/machineLabel?/recipientName?/title?/toolId?:string,
targetKind?:command_already_running,standingGrant?:{kind:offered,recipient:string}|{kind:unavailable,reason:enum}|null}.
Unavailable reasons: group-chat, harness-cannot-persist, invalid-recipient, machine-unsupported, team-policy.
Actions are list-directory, read-ai-tool-setup,
read-file, read-messages, run-command, run-phone-tool, send-imessage, send-input, use-app, write-file. Status is
allowed|always|denied|expired|never|pending. Resolution values are allow-once|deny|always|never (RPC 1/2/3/4);
resolveLocalToolPermission returns null; the app uses its backend twin even for box bots. This is already answerable by gbot.
Sources: **S `$defs.SandLocalToolPermissionAsk`, `$defs.SandStandingGrantUnavailableReason`, `methods.resolveLocalToolPermission`; C `Xt=Q.method`,
`if(!kt&&!$K(Q.method)&&!Xt&&!Ce)`; P `GrokBotLocalToolPermissionCardResolution`**.

**VERIFIED:** a legacy permission-request has permission={kind:camera|filesystem|microphone|other|screen-recording,
reason/title:string,detail?:string}, no resolution marker. Separate user-computer transport has request frames for exec/upload/
download/retireApproval/cancel/messagesOp/localTool/discoverAiTool, not transcript rows. Sources: **S `$defs.SandPermissionRequest`;
P `GrokBotUserComputerRequestFrame|`**. **UNKNOWN:** no generic answer operation for the legacy card, or single universal resolution
enum for transport requests, was established. Settle by naming the intended request subtype and tracing its desktop handler.
Computer handoff entry fields boxRequestId?/boxRequest?/boxInstruction?/boxSnapshot?:string, boxReason?:auth|captcha|other|payment|null,
boxResolution?:dismissed|handed_back|replied|null are VERIFIED (**S `$defs.SandSendMessageEntry`**); hand-back/viewer operation is
protocol-tui section 10. Human browser/VNC interaction may be needed for auth/captcha/payment (**INFERRED**).

## 9. Trays

**VERIFIED — replies:** getTrays returns SandErrorTray[]; dismissTray({id:string}) and clearTrays({}) return null.
Tray requires id/agentId/title:string,createdAt:number,kind:error. Optional strings: dedupeKey,detail,rawDetail,requestId;
numbers: count; number[]: occurrences; severity?:error|info|null; usageLimitKind?:cursor|on_demand|sand_included|null;
unifiedMoreUsage?:buy_credits|none|null; errorKind/titleKind?:string-enum|null, errorParams?:{address?:string,platform?:string,
technicalDetail?:string},titleParams?:{name:string},actions?:TrayAction[]. Error/title enum identifiers describe localized failure
categories (not callable actions). Sources: **S `methods.getTrays`, `methods.dismissTray`, `methods.clearTrays`,
`$defs.SandErrorTray`, `$defs.SandTrayErrorParams`, `$defs.SandErrorTrayTitleParams`**.

**VERIFIED — TrayAction union:** dashboard-action has action:requestLimitIncrease,args:record<string,string>,label:string,
successMessage:string|null; open-buy-credits has label:string,entrypoint:string|null; roll-back has sessionId:string,fromSeq?:number;
open-url has label/url:string; start-fresh has sessionId:string; upgrade|upgradeChoice has url:string; switch-model has no additional
fields. Every variant except switch-model permits emphasis?:primary. Source: **S `$defs.SandErrorTrayAction`**.

**VERIFIED — actual DOM action values:** only buy-credits, start-fresh and roll-back occur as data-sand-tray-action values.
Buy-credits opens the credits flow; start-fresh confirms then calls startFreshConversation with agentId/sessionId;
roll-back calls rollBackConversation with agentId/sessionId, recovers blocked user text into the composer when appropriate, and
dismisses the tray. fromSeq helps recover text locally; it is not sent to rollBackConversation. Upgrade/dashboard actions use the
separate CTA component; they have no data-sand-tray-action value. Sources: **R `data-sand-tray-action`, `function TMn(`,
`function EMn(`, `function L8(`**.

**VERIFIED:** tray state combines gateway trays with locally synthesized server-turn failures; dismissing a synthesized one is
local, while dismissing a host tray calls dismissTray. Clear drops local failures and calls clearTrays; events/reconnect reload host
state. Sources: **R `function NYn(`, `e.dismissTray({id:t}`, `e.clearTrays(fc)`**.

## 10. Gateway commands versus backend twins on gateway-hosted bots

**VERIFIED — routing rule:** a backend adapter existing in M does not prove the desktop uses it for a box bot. C's command router
checks harness/session and exceptions before choosing the gateway. Ordinary box-targeted actions take gateway; temporal bots use
backend actions. Local-tool permission and virtual-card/payment/place-search exceptions can use backend even for box bots.
Connector/auto-review resolutions in recognized room sessions can also use backend. Sources: **C `function n3(`,
`let Ne=HK(Q.method)`, `Yt=(Q.method`, `if(!kt&&!$K(Q.method)&&!Xt&&!Ce)`**.

| Gateway command(s) with parity backend counterpart | Desktop choice for box bot; VERIFIED evidence |
|---|---|
| createThreadFromMessage ↔ CreateGrokBotThreadFromMessage | gateway ordinarily; C router above; M `case"createThreadFromMessage"` is temporal adapter |
| reactToMessage ↔ ReactToGrokBotMessage; voteFeedback ↔ VoteGrokBotFeedback | gateway ordinarily; C router; M `case"reactToMessage"`, `case"voteFeedback"` |
| getAgentTasks ↔ ListGrokBotAgentTasks | gateway for box; backend includeRecentlyDone for temporal; C router, M `case"getAgentTasks"` |
| markAgentTaskDone / markAgentTaskRead / setAgentTaskPinned ↔ MarkGrokBotAgentTaskDone / MarkGrokBotAgentTaskRead / SetGrokBotAgentTaskPinned | gateway for box; backend adapters map isPinned to pinned; C router, M `case"markAgentTaskDone"`, `case"setAgentTaskPinned"` |
| dismissAgentSuggestions ↔ DismissGrokBotAgentSuggestions | gateway for box; C router, M `case"dismissAgentSuggestions"` |
| getSubagents ↔ ListGrokBotSubagents | gateway for box; C router, M `case"getSubagents"` |
| getAgentTodos ↔ ListGrokBotAgentTodos | UNKNOWN desktop choice: no invocation found; S `methods.getAgentTodos` verifies only availability |
| createGroup ↔ CreateGrokBotRoom; setGroupMembers ↔ SetGrokBotRoomMembers | route-dependent, see section 7; C `if(Q.method==="createGroup")`; M `setGrokBotRoomMembers({` |
| uploadAttachmentChunk ↔ UploadGrokBotAgentAttachmentChunk | gateway fallback chunking; no desktop call to backend chunk twin found; preferred store upload uses Begin/Complete/Abort instead; M `async function $(oe,K,he)`, `beginGrokBotAttachmentUpload({` |
| readAttachmentChunk ↔ ReadGrokBotAgentAttachmentChunk | conditional: backend attachment-read feature/room path or gateway; store references can instead resolve signed URLs; M `sand_attachments_via_server`, `function jJe(`, `resolveGrokBotAttachmentReads(` |
| resolveConnectorGrant ↔ ResolveGrokBotConnectorGrant | gateway for ordinary box session; recognized room sessions can use backend; C `Yt=(Q.method`, M `case"resolveConnectorGrant"` |
| resolveVirtualCardApproval ↔ ResolveGrokBotVirtualCardApproval | backend authorization, then gateway settlement for box card; gateway returns null, desktop source returns outcome record; C `gateway-virtual-card-settlement`, `Zre(yt)`, M `case"resolveVirtualCardApproval"` |
| resolveLocalToolPermission ↔ ResolveGrokBotLocalToolPermission | backend even for box bots; see section 8; C `Xt=Q.method` |
| searchPlacesArea ↔ SearchGrokBotPlacesArea | backend even for box bots, with not_searchable fallback if unsupported; C `if(Q.method==="searchPlacesArea")`; M `case"searchPlacesArea"` |

No direct parity twin was identified for getAgentThread, uploadAttachment, readAttachmentText, readAttachmentImage, searchAgents,
searchMedia, getAsyncTasks, getConversationOutline, getTrays, dismissTray or clearTrays. **VERIFIED:** their gateway replies are in
sections 1–9; text/image reads can still use the shared backend byte/signed-URL attachment machinery (**M `function jJe(`,
`resolveGrokBotAttachmentReads(`**). **UNKNOWN:** server-side implementation behind a gateway command is not desktop routing evidence.

The repository's current Card alias, raw-preserving Entry/Bot models and pending detection are context only: connector/credential/
virtual-card cards being recognized does not mean they can be answered by the existing planner (`gbot/pending.py`,
`gbot/service/models.py`, `gbot/service/cards.py`). No implementation or tests were changed.
