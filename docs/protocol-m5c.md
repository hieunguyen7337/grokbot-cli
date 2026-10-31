# M5c protocol research: desktop 0.77.0 memories, files, host, runtime, egress, teach and billing

Offline bundle inspection; no service, private configuration or credential file was accessed. VERIFIED means client code or a declared descriptor establishes the claim; INFERRED is interpretation beyond that; UNKNOWN means this pass did not establish it. Live reply shapes are not covered here: `protocol-m4-live.md` captures no M5 RPC, so every reply shape below is from the bundle. `?` denotes optional, `[]` repeated, `map` a string-to-string map. int64 fields are decimal strings on the wire. Descriptor scalar codes: 1 double, 3 int64, 5 int32, 8 bool, 9 string, 12 bytes, 13 uint32, 11 message, 14 enum. **Secret** marks credentials, tokens, signed URLs and card data; **Personal** marks names, addresses, user identifiers and locale or time zone.

Bundle citation keys (paths relative to the bundle root `dist/`; each citation gives a short search string):

- **C** = `node-agent-coordinator/main.cjs` (gateway command table with policy labels, event-name map, GrokBotService descriptor).
- **M** = `electron-main/main-app.cjs` (main process: backend adapter and desktop command validators).
- **P** = `electron-main/proto.cjs` (message descriptors and enum tables).
- **R** = `renderer/assets/index.eager-app-BtIHj2If.js` (renderer).

Routing terms used below. **Gateway** means a camelCase command in the C command table. **Backend** means a GrokBotService unary RPC that M calls with the gateway agent id. Every PascalCase name here is in the GrokBotService descriptor (C, `typeName:"aiserver.v1.GrokBotService"`) unless stated otherwise. Temporal bots use the backend path for every RPC in sections 1, 2, 3, 4, 6, 7 and 9.

## 1. Memories

**VERIFIED routing:** backend. M `listUserBotMemories:async` calls `listGrokBotUserBotMemories({agentId})`. The renderer also has a validator for the command (R, `listGrokBotUserBotMemories:`). C has no gateway entry. Search: M `listUserBotMemories:async`; P `ListGrokBotUserBotMemoriesRequest|1 agent_id`.

- **ListGrokBotUserBotMemories**: request `{agentId:string}`; reply `{memories:GrokBotMemoryFact[]}`. Read-only. Smallest capture: `{agentId}` with the gateway agent id.
- **GrokBotMemoryFact** (P `GrokBotMemoryFact|1 fact_id`): `factId:string`, `text:string`, `learnedAtMs:int64`. The record has no scope field.
- **Scopes.** User scope: UNKNOWN (no field carries it). Bot scope: INFERRED, since the list is keyed by one agent id and the RPC name reads as user-to-bot memories. Team scope: INFERRED, reached only through **PromoteGrokBotMemoriesToTeam** (request `{agentId, factIds:string[]}` from the request class fields; reply and whether it copies or moves facts: UNKNOWN). Search: C `promoteGrokBotMemoriesToTeam:{name`.
- **Other parity entries touching memories** (names only, from `docs/parity.json`): PromoteGrokBotMemoriesToTeam (area teams, M5). No parity entry edits or deletes a memory; no edit or delete RPC name for memories exists in the GrokBotService names searched.
- **Changes state:** the list does not. Promote does (INFERRED from name). App prompt before promote: UNKNOWN in this pass.

## 2. Library

**VERIFIED routing:** all backend (M `listGrokBotLibraryDocs(new A.ListGrokBotLibraryDocsRequest`; M pin client `listGrokBotLibraryPins({agentId:o}`). C has no gateway entry for these four RPCs.

**What the library is:** INFERRED from the doc fields, a set of external documents the bot has touched or created, plus a per-bot pin list. The event name `agents-library-docs` is mapped to client event `library-docs` (C, `"agents-library-docs":"library-docs"`).

- **ListGrokBotLibraryDocs**: request `{agentId}`; reply `{docs:GrokBotLibraryDoc[]}`. Read-only.
- **GrokBotLibraryDoc** (P `GrokBotLibraryDoc|1 key`): `key:string`, `provider:string`, `externalId:string`, `url:string`, `title?:string`, `createdByBot:bool`, `lastAction:string`, `firstTouchedAtMs:int64`, `lastTouchedAtMs:int64`, `kind:string`. The `url` may point at a private document: treat it as **Personal**. Values of `provider`, `kind` and `lastAction` are free strings in the descriptor (value sets UNKNOWN).
- **ListGrokBotLibraryPins**: request `{agentId}`; reply `{pins:GrokBotLibraryPin[]}`. Read-only.
- **GrokBotLibraryPin** (P `GrokBotLibraryPin|1 page`): one-of `target` with `page:GrokBotLibraryPinPage`, `media:GrokBotLibraryPinMedia`, `externalDocKey:string`, `appKey:string`; plus `pinnedAtMs:int64`.
- **GrokBotLibraryPinPage**: `storeId:string` and one-of `canvasId:string` or `documentId:string` (descriptor `GrokBotLibraryPinPage|1 store_id`).
- **GrokBotLibraryPinMedia** (P `GrokBotLibraryPinMedia|1 kind`): `kind:GrokBotLibraryPinMediaKind` (UNSPECIFIED, IMAGE, VIDEO, FILE, LINK), `source:string`, `name:string`, `postedAtMs:int64?`.
- **SetGrokBotLibraryPin**: request `{agentId, pin:GrokBotLibraryPin, isPinned:bool}`; reply `{pins:GrokBotLibraryPin[]}`, the list after the change. **Changes state.**
- **MergeGrokBotLibraryPins**: request `{agentId, pins:GrokBotLibraryPin[]}`; reply `{pins:GrokBotLibraryPin[]}`. Client-side the call is a bulk push; a NotFound status is read as "absent" and not raised (M, `merge:async`). Server merge rule (union, replace or other): UNKNOWN.
- **Client filtering:** pins that do not map to a known target are dropped, not errored (M `function Jce(`, `flatMap`).
- **What a pin does:** VERIFIED only that a pin is stored per bot with a time stamp and that the set is returned whole after each change. Its effect in the library view (ordering, badge, visibility): UNKNOWN. Pin-change refresh: `server-roster-changed` with kind user-settings and field `libraryPins` (see `protocol-m4b.md` section 12).
- **App prompt before a pin change:** UNKNOWN in this pass.

## 3. Agent files

**VERIFIED routing:** backend for all four. Gateway: none (C). Desktop validators exist for list, delete and upload in R and M.

- **GrokBotAgentFile** (P `GrokBotAgentFile|1 name`): `name:string`, `path:string`, `sizeBytes:int64`, `contentType:string`, `updatedAtMs:int64`, `etag:string`.
- **ListGrokBotAgentFiles**: request `{agentId, pageToken:string}`; reply `{files:GrokBotAgentFile[], nextPageToken:string, totalBytes:int64, canEdit:bool}`. Read-only. The desktop sends `pageToken` as the empty string and reads one page only, ignoring `nextPageToken` (M, `listGrokBotAgentFiles({agentId:a,pageToken:""}`). A terminal must follow `nextPageToken` to list every file.
- **Upload protocol, step by step** (M, `upload:async({agentId:a,fileName:i,contentType:s,bytes:d})`):
  1. Client computes the lowercase hex SHA-256 of the bytes.
  2. **BeginGrokBotAgentFileUpload**: request `{agentId, fileName, sizeBytes:int64, sha256Hex:string, contentType:string}`; reply `{uploadToken:string **Secret**, finalName:string, url:string **Secret** (signed upload URL), headers:map **Secret** (values may be signed-request material), expiresAtMs:int64}`.
  3. HTTP **PUT** to `url`, with exactly the returned `headers` and the raw bytes as body (M, `fetch(e,{method:"PUT"`). A non-OK status raises a storage rejection carrying the HTTP status.
  4. **FinishGrokBotAgentFileUpload**: request `{agentId, uploadToken **Secret**}`; reply `{file:GrokBotAgentFile}`. A reply with no file is an error.
- **Timeouts:** 30 seconds on the list, begin and finish RPCs (M, `yGn=3e4`). No timeout for the storage PUT was found (UNKNOWN).
- **Size and type limits:** UNKNOWN. The begin reply has no limit field. No client-side size or type check was found in M or R. INFERRED: enforced server-side or at storage. Compare the attachment begin in `protocol-m2.md` section 2, which returns `limitBytes` and a mode.
- **Comparison with attachments** (`protocol-m2.md` section 2): attachments return a mode (USE_BOX, SINGLE_PUT, MULTIPART or REFUSED), support multipart, have Complete and Abort RPCs, and are session- or thread-scoped. Agent files have one signed PUT, no multipart, no abort, and finish by token. Both send a SHA-256 up front.
- **DeleteGrokBotAgentFile**: request `{agentId, name}`; reply `{}`. **Changes state.** The renderer asks for confirmation first: a dialog that names the file and the bot, with confirm and cancel labels (R, `confirmLabel` near `deleteGrokBotAgentFile` remove call).
- **Events:** no file-change event name in the C event map. The desktop re-reads its own list after upload and remove (R, `t.reread(n.agentId)`).

## 4. User store files

**VERIFIED routing:** backend. M `listUserStore` calls `listGrokBotUserStoreFiles({agentId})`; `removeUserStore` calls `deleteGrokBotUserStoreFile({agentId, path})`. Both have renderer validators.

- **GrokBotUserStoreFile** (P `GrokBotUserStoreFile|1 name`): `name:string`, `path:string`, `sizeBytes:int64`, `updatedAtMs:int64`. It has no `etag` and no `contentType`.
- **ListGrokBotUserStoreFiles**: request `{agentId}`; reply `{files:GrokBotUserStoreFile[]}`. Read-only.
- **DeleteGrokBotUserStoreFile**: request `{agentId, path}`; reply `{}`. **Changes state.** The renderer picks the remove path by a store discriminator: bot store uses DeleteGrokBotAgentFile, user store uses this RPC. Both paths sit behind the same confirmation dialog (R, `i.store===` remove branch).
- **Comparison.** Agent files are bot-owned, uploaded by the user, addressed by name and carry an etag. User-store files are addressed by path, are listed and deleted but not uploaded in any RPC name found here, and carry no etag or content type. INFERRED: the user store is a per-user area scoped to a bot; the library is a separate surface of external documents and pins (section 2). No user-store upload RPC was found among the names searched.

## 5. Host settings

**VERIFIED scope:** desktop machine, not the backend. C lists `getHostSettings`, `setHostSettings`, `updateHostNow` and `isEgressTunnelAvailable` as gateway commands with policy labels (`person` for the first three, `background` for the last). No GrokBotService method named for host settings exists. The main process holds the values (INFERRED from the settings-sync code), and it mirrors a subset to the box with `syncHostSettingsToBox` (fields `messagesEnabled` and `selectedTeam`, M `syncHostSettingsToBox`). Search: C `getHostSettings:"person"`; M `syncHostSettingsToBox[:(]`.

- **getHostSettings**: no arguments (C `getHostSettings:I().noArgs`). Reply: the settings object (C reads it as a value; wrapper shape UNKNOWN). Read-only.
- **setHostSettings**: an object with all fields optional (C `Mte=b({`). Fields:
  - `notifications`: `{isEnabled:bool?, allowedApps:string[]?, minIntervalMs:number?, maxPerWindow:number?, windowMs:number?}` (`Pte`).
  - `selectedTeam`: `{teamId:number, accountScope:string}` or null.
  - `mcpCustomInstructions`, `mcpCustomInstructionsByServerId`, `mcpCustomInstructionsAccountScope`, `mcpDisabledToolsByServerId`, `mcpBoxServers`: MCP settings maps and lists.
  - `userTimeZone`, `userTimeZoneOverride`, `osLocale`: strings, **Personal**.
  - `computerUseModel`: `{modelId, maxMode:bool, parameters:{id,value}[]}` or null.
  - `autoReviewInstructions`: `{isEnabled:bool, allowInstructions:string[], blockInstructions:string[]}`.
  - `toolPermissions`: `{scopes:{tools:string[], reads, writes}[]}`, values `always_allow`, `needs_approval`, `blocked`.
  - `localToolPermission`, `localToolPermissionMachineId`, `localToolPermissionByMachineId`: per-machine local tool permission.
  - `webauthnProxyEnabled`, `messagesEnabled`, `hasSeenOnboarding`: bools.
  - `pinnedAgentIds:string[]`, `sidebarSections:{id,name,agentIds[],isCollapsed?}[]`.
  - `featureFlagOverrides:map<string,bool>`, `experimentOverrides`.
  **Changes state.** Writes are local to the desktop, except the mirrored fields.
- **updateHostNow**: arguments `{force?:bool, includeErrorDetail?:bool}` (C `updateHostNow:I().args`); reply is a record (shape UNKNOWN). The renderer calls it with `force:true` only when the computer status kind is host, and treats `started:false` as an error (R, `updateHostNow({force:!0}`). **Changes state.**
- **isEgressTunnelAvailable**: no arguments; reply boolean (C `isEgressTunnelAvailable:{args:"none",reply:"boolean"}`). Read-only. Backend equivalent: none found.
- **Meaning for backend-hosted bots:** INFERRED, little. Most fields describe the desktop. The few that matter to bots (`pinnedAgentIds`, `sidebarSections`, `userTimeZone`, MCP settings) duplicate backend runtime settings (section 6). `updateHostNow` applies to a host-kind computer, not to a backend-hosted bot (INFERRED from the renderer branch).

## 6. Runtime settings and sandbox

**VERIFIED routing:** backend for all commands in this section. C has no gateway entry for them. The sandbox run-state class in M holds `this.client = n ?? de(A.GrokBotService, deps)`, and the upgrade-schedule client uses `A.GrokBotService` too.

**Sandbox id:** no request in this section carries a sandbox id. INFERRED: the backend resolves it from the caller's account. The renderer does keep a local `boxId` in its own status (R, `boxId`), which is not sent here.

- **UpdateGrokBotUserRuntimeSettings**: request fields (P `UpdateGrokBotUserRuntimeSettingsRequest|5 pinned_agents`): `pinnedAgents:{agentIds:string[]}?`, `sidebarSections:{sections:[]}?`, `sidebarSectionsBase?`, `hasSeenOnboarding:bool?`, `autoReviewInstructions?`, `xToolAccess?`, `autoReviewRuleSave?` (`{surface, textSource, connector:string}`), `botsHidden:bool?`. Reply `{settings:GrokBotUserRuntimeSettings}`. **Changes state.** App prompt: none found for the sidebar writes (they are direct); the rule-save path is UNKNOWN.
- **GetGrokBotUserRuntimeSettings**: request `{}`; reply `{settings}`. Read-only. **GrokBotUserRuntimeSettings** fields: `updatedAtMs:int64`, `pinnedAgents`, `sidebarSections`, `hasSeenOnboarding:bool?`, `mainAgentId:string?`, `termsSeenAtMs:int64?`, `autoReviewInstructions`, `emailProvider` (message; its name UNKNOWN), `xToolAccess` (message; name UNKNOWN), `toolPermissions:{scopes:{tools, reads, writes}[]}?`, `jobRole:string?`. Search: P `GrokBotUserRuntimeSettings|5 updated_at_ms`.
- **GetSandBoxRunState**: request `{}`; reply `{state:SandBoxRunState, imageUpdateAvailable:bool?, egressTunnelOwnership:bool?, image:{registryTag:string?, staticSnapshotPath:string?}?}`. Enum SandBoxRunState: UNSPECIFIED, ABSENT, HIBERNATED, RUNNING, STARTING (P `SandBoxRunState` table). On RPC failure the desktop shows a connecting phase (M, `readConnectPhase`). Read-only.
- **RecreateSandBox**: request `{preserveData:bool, force:bool, acknowledgeTerminalUpgradeSchedule:bool}`; reply `{started:bool, reason:string, operationId:string}` (P `RecreateSandBoxResponse|1 started`). The update path sends `preserveData:true, force:false` (`protocol-m4b.md` section 10). **Changes state.** `preserveData:false` discards the sandbox data (INFERRED from the name; exact scope UNKNOWN). The acknowledge flag lets a recreate proceed past a terminal upgrade schedule (INFERRED). A rejected reply carries `reason`. Warning text: UNKNOWN.
- **ForceRecreateSandBox**: request `{}`; reply has the same descriptor type as RecreateSandBox (C service output `hr`, reused). **Changes state.** It has no keep-data argument, so the force path offers no keep-data choice (VERIFIED from the request shape). What it destroys: UNKNOWN. The renderer calls it from a recovery branch (R, `forceRecreateComputer`); the confirmation step, if any, is UNKNOWN.
- **GetSandBoxUpgradeSchedule**: request `{}`; reply `{schedule?:SandBoxUpgradeSchedule}`. Read-only. The desktop maps an absent schedule to null.
- **ScheduleSandBoxUpgrade**: request `{timezone:string, localTime:string, recurring:bool}`; reply `{schedule}`. The time zone is checked with the runtime's Intl time zone API (R, `function Kv(`). The local time must match a 24-hour `HH:MM` pattern (R, regex near `aAe`). The "window" is one local time, not a range, and `recurring` says whether it repeats (INFERRED). **Changes state.**
- **RescheduleSandBoxUpgrade**: same request as schedule; reply `{schedule}` (P `RescheduleSandBoxUpgradeResponse|1 schedule`). **Changes state.**
- **CancelSandBoxUpgrade**: request `{dismissTerminalOutcome:bool}`; reply `{schedule}`. **Changes state.**
- **SandBoxUpgradeSchedule** (P `SandBoxUpgradeSchedule|1 timezone`): `timezone:string`, `localTime:string`, `recurring:bool`, `targetImageTag:string?`, `nextFireAtMs:int64?`, `state:SandBoxUpgradeScheduleState` (UNSPECIFIED, SCHEDULED, CLAIMED, RUNNING, WAITING_FOR_IMAGE, COMPLETED, MISSED, FAILED, CANCELLED), `lastCompletedImageTag:string?`, `failureReason:string?`, `targetArtifactRef:string?`, `lastCompletedArtifactRef:string?`.
- **Migration stream:** `WatchSandBoxMigration` is a server stream on the same service (C service table). Its phases are in `protocol-m4b.md` section 10.

## 7. Egress policy and agent analytics

**VERIFIED routing:** backend. Gateway: none.

- **GetGrokBotEgressPolicy**: request `{}`; reply `{restricted:bool, allowedDomains:string[], allowedTcpDestinations:{cidr:string, port:int32}[]}` (P `GetGrokBotEgressPolicyResponse|1 restricted`). Read-only. The mode is the `restricted` flag: restricted or open (INFERRED; there is no enum). The desktop handles a FailedPrecondition specially (M, `C5e`). No set RPC for egress was found in the names searched. Applies to the sandbox (INFERRED, from the name and the sandbox field `egressTunnelOwnership`).
- **GetGrokBotAgentAnalytics**: request `{agentId}`; reply `{weeklyActiveUsers:int32, totalMinutesSaved:double, days:{day:string, activeUsers:int32, trailingSevenDayActiveUsers:int32, userTurns:int32, minutesSaved:double}[], minutesSavedBeforeWindow:double, topUsers:{userId:int32 **Personal**, displayName:string **Personal**, userTurns:int32, minutesSaved:double, isExternal:bool, activeDays:int32}[], minutesSavedMeasured:bool, topUsersByWindow:{windowDays:int32, topUsers[]}[]}` (P `GetGrokBotAgentAnalyticsResponse|1 weekly_active_users`). Read-only.
- **Time ranges and grouping:** no range argument is sent. The reply gives daily buckets (`days`), a weekly active count, and top users grouped by window length (`windowDays`). Which window lengths the backend returns: UNKNOWN. The `day` string format: UNKNOWN.

## 8. Teach recording

**VERIFIED routing:** gateway commands only (C command table, policy `person`; M validators). No GrokBotService RPC with a teach name exists. Parity status in `parity.json`: handoff for start and stop.

- **getTeachRecordingStatus**: no arguments; reply is a record (shape UNKNOWN). Read-only.
- **startTeachRecording**: arguments `{agentId:string, entryPoint:TeachEntryPoint}`. Enum TeachEntryPoint: screen_hover, composer_menu, fullscreen_title_bar (C, `une=be("teach entry point"`). Reply is a record (UNKNOWN). **Changes state.**
- **stopTeachRecording**: arguments `{agentId:string, save:bool}`; reply record (UNKNOWN). **Changes state.**
- **What it records:** UNKNOWN in content. VERIFIED that the result feeds the transcript: `teach_recording` is one of the user-message sources (C source list), and `teach-recording` is an event name (C event map). INFERRED: a screen demonstration captured by the desktop, which the parity note describes as requiring the app.
- **Where it runs:** INFERRED, on the desktop. No backend RPC was found.
- **Terminal support:** a terminal cannot start or stop it (desktop capture). Showing status would need a reply from the desktop gateway; the reply shape is UNKNOWN.

## 9. Billing and account

**VERIFIED routing:** backend for every RPC in this section. The card-photo and vault-card paths are reached from the renderer through main (R and M validators).

- **GetGrokBotDefaultPaymentMethod**: request `{}`; reply `{method?:GrokBotPaymentMethodRef}`. Read-only.
- **GrokBotPaymentMethodRef** (P `GrokBotPaymentMethodRef|1 vault_card_id`): one-of `method`: `vaultCardId:string` **Secret** (opaque reference to a vault card) or `wallet:GrokBotPaymentWallet` (UNSPECIFIED, X_MONEY, STRIPE_LINK). Brand and last four digits are not in this reply (UNKNOWN which RPC supplies them; `protocol-m4b.md` section 7 gives brand and last4 on vault cards and Stripe Link entries).
- **SetGrokBotDefaultPaymentMethod**: request `{method?:GrokBotPaymentMethodRef}`; reply `{method?}`. **Changes state.** Parity marks selection as handoff (browser or app UI).
- **ExtractGrokBotCardFromPhoto**: request `{photos:{image:bytes **Personal**, mimeType:string}[]}`; reply `{outcome:GrokBotCardPhotoOutcome, number:string **Secret**, expMonth:int32, expYear:int32, cardholderName:string **Personal**, securityCode:string **Secret**}`. Enum GrokBotCardPhotoOutcome: UNSPECIFIED, READ, NOT_FOUND, UNAVAILABLE (P `GrokBotCardPhotoOutcome`). **The reply carries the full card number and security code.** `protocol-m4b.md` section 7 notes that vault replies declare no PAN or CVC; this one does. The photo read has a timeout and can be cancelled from the renderer (R, `cancelGrokBotCardPhotoRead`). The call itself does not save a card (INFERRED); saving goes through CreateGrokBotVaultCard, which is handoff (`protocol-m4b.md` section 7). Provider or page the entry opens: UNKNOWN (none found in this pass). Completion is the save call returning (INFERRED).
- **MarkGrokBotTermsSeen**: request `{}` (no arguments, so the terms are not named in the call); reply `{termsSeenAtMs:int64}`. **Changes state.** Which terms: UNKNOWN. The desktop reads the seen time from `termsSeenAtMs` in GetGrokBotUserRuntimeSettings (M, `lpn` and `dpn`), not from GetGrokBotTermsSeen, which exists as a name but has no desktop call site (matching parity "declined").
- **ResolveGrokBotAddress**: request `{id:string, sessionToken:string **Secret**}`; reply `{parts?:GrokBotAddressParts}`. `GrokBotAddressParts` fields, all **Personal**: `street`, `city`, `state`, `postalCode`, `country`, `countryCode`, `formatted`. Read-only (lookup). Timeout 10 seconds (M, `oFn`). No parts gives an "unresolved" outcome.
- **SuggestGrokBotAddresses**: request `{query:string **Personal**, sessionToken:string **Secret**}`; reply `{outcome:GrokBotAddressLookupOutcome, suggestions?:{id:string, title:string **Personal**, subtitle:string **Personal**}[]}`. Enum GrokBotAddressLookupOutcome: UNSPECIFIED, SUGGESTED, UNAVAILABLE (P). Purpose: address autocomplete for billing or contact forms (INFERRED). Timeout 5 seconds; any failure reads as unavailable (M, `rFn`). Read-only.

## 10. Events

**VERIFIED gateway event names** (C event map, `Jz`): `forever-box`, `teach-recording`, `host-settings`, `computer-action`, `box-disk-pressure`, `server-roster-changed`, `agents-library-docs` (client name `library-docs`), `agent-activity`, `transcript`, `agent-upserted`. Events outside this milestone (`agents-bot-secrets`, `mcp-servers-updated`) are not needed here.

- `server-roster-changed` with kind `user-settings` and field names including `libraryPins`, `pinnedAgents`, `sidebarSections`, `autoReview`, `hasSeenOnboarding`, `mainAgent`, `timeZone` (`protocol-m4b.md` section 12). Use it to refresh pins, runtime settings and sidebar state.
- `forever-box`: sandbox or computer state changes. Whether it fires on run-state or upgrade-schedule changes: UNKNOWN.
- `teach-recording`: teach state changes (section 8).
- `host-settings`: host settings changes (section 5).
- `library-docs`: library document changes (section 2).

**Backend streams:** `WatchSandBoxMigration` (migration phases; `protocol-m4b.md` section 10) is the only server stream here that matches the sandbox or recreate work.

**No event found for:** a file upload finishing (the desktop re-reads after its own call), agent or user-store file deletion, memory changes, and an upgrade being scheduled (UNKNOWN; no event name in the map names upgrades). For the TUI: refresh after each mutating call, and subscribe to the events above.
