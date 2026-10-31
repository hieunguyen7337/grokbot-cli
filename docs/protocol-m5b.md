# M5b protocol research: publishing (desktop 0.77.0)

Offline bundle inspection only. No live service, no gbot network command and no credential file was touched. VERIFIED means the bundle code or a generated descriptor establishes the claim. INFERRED is interpretation beyond that. UNKNOWN means this pass did not settle it, not that the feature is absent. Live reply shapes, where captured, belong in protocol-m4-live.md. Conventions follow protocol-m4a.md: `?` optional, `[]` repeated, int64 as decimal strings, and **Secret** for any field or object that holds or grants a credential. Routing follows protocol-m2 section 10 and protocol-temporal sections 1-2. Skills and plugins in general are covered by protocol-m4a section 5 and are not repeated here.

Citation keys (paths relative to the bundle root `_bundle-077`, each followed by a short search string):
- C = dist/node-agent-coordinator/main.cjs (the local gateway)
- M = dist/electron-main/main-app.cjs (desktop main process)
- P = dist/electron-main/proto.cjs (descriptors and Connect service tables)
- R = dist/renderer/assets/index.eager-app-BtIHj2If.js (main renderer)
- V = dist/renderer/assets/chunk-view-nVmZzLNj.js (skill and plugin dialogs)
- T = dist/renderer/assets/chunk-bot-template-details-dialog-DDgHxnGG.js (template details)
- D = dist/local-exec-daemon/main.cjs (desktop exec daemon; Connect client only)

"Temporal" means a backend-hosted bot, which is every bot the user has. "Gateway" means a camelCase `/api/<command>` handled by C.

## 0. Summary

| Area | Gateway commands (C) | Backend RPCs (service) | Changes state | Temporal bot route |
|---|---|---|---|---|
| Templates (1) | publishBotTemplate, deleteBotTemplate, setBotTemplateVisibility, listBotTemplates, getBotTemplateVersion, getBotTemplateExportPolicy | ActivateGrokBotTemplateVersion, DeleteGrokBotTemplate, SetGrokBotTemplateVisibility, ListGrokBotTemplates, GetGrokBotTemplateVersion, GetGrokBotTemplateExportPolicy (GrokBotService) | yes, except the reads | verified: backend action in M for every template command except listBotTemplates |
| Marketplace (2) | none found | PublishGrokBotAgent, UnpublishGrokBotAgent (GrokBotService) | yes | direct desktop-to-backend call from main |
| Skills (3) | getSkillPublishTargets, publishSkill, resyncPublishedSkill, unpublishSkill | none found | yes | no backend action case in M; route UNKNOWN |
| Plugin listings (4) | hasRestorablePluginListingCopy, unpublishPluginListing | none found | the unpublish one yes | no backend action case in M; route UNKNOWN |
| Cloud agents (5) | getCloudAgentInfo, getCloudAgentConversation, stopCloudAgent | background composer readers for info and conversation; no stop RPC found | stop yes | info and conversation go to backend; stop UNKNOWN |
| Cloud apps (6) | listCloudAgentPublishedApps, updateCloudAgentPublishApp, unpublishCloudAgentPublishApp, createCloudAgentAppsGateTicket, getCloudAgentAppSecrets, setCloudAgentAppSecrets, tellCloudAgentAppSecretsSet | none found | yes (except list, get, gate ticket) | no backend action case in M; route UNKNOWN |
| Proposals (7) | getCloudAgentPublishProposals, confirmCloudAgentPublishProposal, dismissCloudAgentPublishProposal | none found | confirm and dismiss yes | no backend action case in M; route UNKNOWN |

Key finding: a temporal bot sends every gateway command to the backend action first (C, search `for Temporal agents`). Only the commands with a case in the desktop adapter (section 13) reach a backend RPC. The others have no case there, so their reply and route are not established.

## 1. Bot templates

Gateway commands (class "person" unless noted):
- publishBotTemplate takes a shareId (string) and an optional version (uint32). VERIFIED: C, search `publishBotTemplate:I().args(aa)` and `aa=b({shareId:y(),version:oe()})`.
- deleteBotTemplate takes a shareId. VERIFIED: C, search `deleteBotTemplate:I().args(da)`.
- setBotTemplateVisibility takes a shareId and a visibility, which the gateway accepts only as "public" or "team". VERIFIED: C, search `visibility:be("bot template visibility",pK)` and `pK=["public"`.
- getBotTemplateVersion takes shareId and version. VERIFIED: C, search `getBotTemplateVersion:I().args(ua)` and the desktop reader in M, search `getVersion:async f=>`.
- getBotTemplateExportPolicy takes no arguments. VERIFIED: C, search `case"getBotTemplateExportPolicy"` (command list) and M, search `getExportPolicy:async()=>`.
- listBotTemplates takes no arguments and uses the "background" class. VERIFIED: C, search `listBotTemplates:I().noArgs`.

Gateway reply shapes (section 13 has the full table):
- publishBotTemplate and setBotTemplateVisibility reply with one template record built by the desktop converter. VERIFIED: M, search `function Ype(e,t={})`. Fields: shareId (string), name (string), avatarShape (string), avatarColor (string), description (string), shareUrl (string, built from a fixed bot path and the shareId; VERIFIED M, search `function yR(e)`), published (bool), version (publish only, the requested number), activeVersion? (uint32), sourceAgentId? (string), createdAtMs? and updatedAtMs? (timestamps, encoding as produced by the converter), visibility? ("public" or "team").
- deleteBotTemplate replies with null. VERIFIED: M, search `delete:async f=>(await t().deleteGrokBotTemplate`. The C reply table says void. VERIFIED: C, search `deleteBotTemplate:{args:"object",reply:"void"`.
- getBotTemplateVersion replies with a template recipe view: shareId, name, avatarShape, avatarColor, description, shareUrl, memory, skills, routines, plugins, published, version, active, createdAtMs? and visibility?. VERIFIED: M, search `getVersion:async f=>`. The desktop downloads the template recipe from a short-lived URL, parses it, and copies the memory, skills, routines and plugins sections into the reply. The URL itself is **Secret** (see the GetGrokBotTemplateVersionResponse fields below).
- getBotTemplateExportPolicy replies with an object that has exportPolicy only when the value is valid: one of "all", "team_only" or "none"; otherwise an empty object. VERIFIED: M, search `Wqe(h)?{exportPolicy:h}:{}` and `function Wqe(e)`. The adapter does not forward has_team, so has_team is not in the gateway reply. VERIFIED from the same code.

Backend RPCs (all GrokBotService; P):
- ActivateGrokBotTemplateVersion: request has share_id (string) and version (uint32). Response has template (GrokBotTemplate). VERIFIED: P, search `ActivateGrokBotTemplateVersionRequest|1 share_id 9`.
- DeleteGrokBotTemplate: request has share_id (string). Response has no fields. VERIFIED: P, search `DeleteGrokBotTemplateRequest|1 share_id 9`; the response descriptor name is listed with no fields (INFERRED empty).
- SetGrokBotTemplateVisibility: request has share_id (string) and visibility (GrokBotTemplateVisibility). Response has template. VERIFIED: P, search `SetGrokBotTemplateVisibilityResponse|1 template`.
- ListGrokBotTemplates: request has no fields (INFERRED empty; the descriptor name is listed with no field entries). Response has templates (repeated GrokBotTemplate) and export_policy (string, optional). VERIFIED: P, search `ListGrokBotTemplatesResponse|1 templates`.
- GetGrokBotTemplateVersion: request has share_id (string) and version (uint32). Response has version (uint32), active (bool), created_at_ms (int64), blob_object_key (string), blob_get_url (string, **Secret**: a temporary read link to the recipe), visibility (enum). VERIFIED: P, search `GetGrokBotTemplateVersionResponse|1 version`.
- GetGrokBotTemplateExportPolicy: request has no fields (INFERRED empty). Response has export_policy (string, optional, one of the three values above) and has_team (bool, optional). VERIFIED: P, search `GetGrokBotTemplateExportPolicyResponse|1 export_policy`.
- GetGrokBotTemplateForSourceAgent: request has source_agent_id. Response has template (optional) and export_policy and has_team. VERIFIED: P, search `GetGrokBotTemplateForSourceAgentResponse|1 template`; request fields VERIFIED from the adapter, search `getForSourceAgent:async f=>`.
- CreateGrokBotTemplate: request has name, avatar_shape, avatar_color, source_agent_id, blob_content_type (optional), blob_byte_size (optional, int64), description and requested_visibility (optional enum). Response has template, blob_put_url (optional, **Secret**: a temporary upload link for the recipe) and version (uint32). VERIFIED: P, search `CreateGrokBotTemplateRequest|1 name 9`. This is where the recipe blob is uploaded.
- Also present with names only (fields not decoded): GetPublicGrokBotTemplate, GetGrokBotTemplateImportDetails, CreateGrokBotAgentFromTemplate. VERIFIED names in P.

GrokBotTemplate message (P, search `GrokBotTemplate|1 share_id 9`), field numbers and types as the descriptor gives them:
- 1 share_id (string); 2 name (string); 3 avatar_shape (string); 4 avatar_color (string); 6 source_agent_id (string, optional); 7 created_at_ms (int64); 8 updated_at_ms (int64); 9 blob_object_key (string, optional); 10 published (bool); 11 active_version (uint32, optional); 12 description (string); 13 visibility (GrokBotTemplateVisibility); 14 owner_type (GrokBotTemplateOwnerType); 15 image_url (string, optional). Field 5 is not used in this descriptor.
- Enum GrokBotTemplateVisibility: UNSPECIFIED, PUBLIC, TEAM. VERIFIED: P, search `GrokBotTemplateVisibility`.
- Enum GrokBotTemplateOwnerType: values not decoded in this pass: UNKNOWN.

What publishing includes:
- VERIFIED: the publish request carries only a share id and an optional version. Publishing activates a version that already exists (section 13 row 1).
- VERIFIED: a version's recipe holds profile fields (name, avatar, description), memory, skills, routines and plugins. Source: the getBotTemplateVersion reader in M, search `getVersion:async f=>`.
- VERIFIED: the recipe is uploaded at template creation, through the upload link returned by CreateGrokBotTemplate. P, search `blob_put_url`.
- UNKNOWN: whether secrets, connector accounts or personal data are inside the recipe blob. The reply exposes only the four sections above, and the blob's full layout was not decoded.
- INFERRED: GetGrokBotTemplateExportPolicy tells the desktop which parts may be exported: "all", "team_only" or "none". The exact per-section rule is UNKNOWN.

Routing for a temporal bot:
- VERIFIED: C sends every temporal-bot command to the backend action first, and only falls back to its local handler for non-temporal bots. C, search `for Temporal agents`. If the backend action reports unimplemented for a temporal bot, C throws an error that the server does not support that command for temporal agents, unless the command is in a short exception list.
- VERIFIED: the desktop adapter maps publishBotTemplate, getBotTemplateVersion, getBotTemplateForSourceAgent, getBotTemplateExportPolicy, deleteBotTemplate and setBotTemplateVisibility to the matching template service calls. M, search `case"publishBotTemplate"`.
- VERIFIED: publishBotTemplate and getBotTemplateForSourceAgent also record the link from share id to source agent in C after the call. C, router function n3 (search `function n3`).
- UNKNOWN: which backend RPC listBotTemplates calls. The adapter has no visible case for it in this pass. INFERRED: ListGrokBotTemplates.

Confirmation and errors:
- VERIFIED: the template details view has publish error kinds for sharing disabled, public sharing disabled, template deleted and a generic failure. T, search `public-sharing-disabled`.
- UNKNOWN: whether the app shows a confirm step before delete or a visibility change. The generic confirm helper in R was not traced for these commands.
- INFERRED: "public" means listed to all users and "team" means visible to the team only, from the enum names alone.

## 2. Bot marketplace (publishing a bot)

- VERIFIED: publishing a bot is a separate operation from publishing a template. It takes the agent id of a live bot, not a template share id. P, search `PublishGrokBotAgentRequest|1 agent_id 9`.
- VERIFIED: there is no gateway command for it in this pass. The desktop main process calls the backend RPC directly with the agent id and then switches on the outcome. M, search `publishGrokBotAgent({agentId:y}`. The renderer reaches it through roster actions named publishAgent and unpublishAgent. R, search `Q().roster.publishAgent`.
- VERIFIED: so for a temporal bot this path does not go through the local gateway. It is a direct desktop-to-backend call.
- Arguments: agent_id (string). Nothing else.
- VERIFIED reply: PublishGrokBotAgentResponse has agent (GrokBotAgent) and outcome (PublishGrokBotAgentOutcome). P, search `PublishGrokBotAgentResponse|1 agent`.
- Outcome values: UNSPECIFIED, PUBLISHED, ALREADY_PUBLISHED, NOT_SHARED, UNSUPPORTED_HARNESS. VERIFIED: P, search `PublishGrokBotAgentOutcome`. The desktop maps each to a result kind (published, already published, not shared, and so on). M, search `publishGrokBotAgent({agentId:y}`. INFERRED: NOT_SHARED means the bot must be shared before it can be published.
- Listing id or URL: VERIFIED that the reply has no listing id or URL field. The listing is the agent record itself. GrokBotAgent carries a published-at timestamp (field 23) and a visibility field. P, search `GrokBotAgent|`. Any listing URL is built in the renderer and was not traced: UNKNOWN.
- Unpublish: UnpublishGrokBotAgent takes the same agent id. Outcome values are UNSPECIFIED, UNPUBLISHED, NOT_PUBLISHED, NOT_SHARED and UNSUPPORTED_HARNESS. VERIFIED: P, search `UnpublishGrokBotAgentOutcome`. The desktop maps them to kinds in the same way. M, search `unpublishGrokBotAgent({agentId:y}`.
- Review or approval: VERIFIED that neither publish reply has a review enum. GrokBotAgent has team_default_for_viewer and viewer_can_manage. Whether a team review gate applies before listing: UNKNOWN.
- Related internal RPCs exist: GetGrokBotMarketplaceListingTemplateInternal, UpdateGrokBotMarketplaceListingTemplateInternal and related names, all GrokBotService. VERIFIED names only. They are internal and not proposed for the TUI.
- Changes state: yes. Publishing and unpublishing change a live bot's listing.
- Confirm before publish: UNKNOWN in this pass.

## 3. Skills

Gateway commands (class "person"):
- getSkillPublishTargets takes no arguments. VERIFIED: C, search `getSkillPublishTargets:I().noArgs`. Reply: record, field names UNKNOWN. VERIFIED: C, search `getSkillPublishTargets:{args:"none",reply:"record"`.
- publishSkill takes workflowId (string) and an optional teamId (string). VERIFIED: C, search `publishSkill:I().args({workflowId:y(),teamId:oe()})`. Reply: record, fields UNKNOWN.
- resyncPublishedSkill takes workflowId. VERIFIED: C, search `resyncPublishedSkill:I().args({workflowId:y()})`. Reply: record, fields UNKNOWN.
- unpublishSkill takes workflowId. VERIFIED: C, search `unpublishSkill:I().args({workflowId:y()})`. Reply: record, fields UNKNOWN.

Publish dialog (V):
- VERIFIED: the publish dialog reads a list of targets, a list of teams, a promoted workflow id and a flag for a missing description. V, search `isDescriptionMissing`.
- VERIFIED: the renderer bridge for publishSkill drops the agent id before calling the gateway. R, search `publishSkill`.

What publish sends and changes:
- Publish sends the workflow id and optionally a team id. It changes state: a published skill becomes visible to the chosen targets.
- Resync re-sends the workflow id. What resync overwrites on the listing is UNKNOWN (INFERRED: it refreshes the listing from the current workflow).
- Unpublish removes the listing by workflow id. Whether a private copy remains: UNKNOWN for skills (see section 4 for plugins).

Backend path and routing:
- VERIFIED: none of the four names has a case in the desktop adapter. M, search `case"publishSkill"` finds nothing. C has no named handler for them either; the names appear only in the validator and reply tables. So the handler body is not located in this pass.
- VERIFIED: for a temporal bot C calls the backend action first. If that action reports unimplemented, C throws the temporal-agent error (section 1, routing). INFERRED: these four commands therefore fail for a temporal bot. UNKNOWN until the desktop default branch is traced (section 13).
- VERIFIED: no RPC whose name combines Skill and Publish was found in P.
- Relation to protocol-m4a section 5: that section covers the consumer side (listing and installing skills). The matching GrokBotService RPCs are ListGrokBotAgentSkills, AddGrokBotAgentSkill, UpdateGrokBotAgentSkill and RemoveGrokBotAgentSkill. VERIFIED names in P. Publishing a skill is the producer side, which is separate. PublishGrokBotUserSkillsSnapshot is a separate GrokBotService RPC and is declined in parity.

## 4. Plugin listings

- hasRestorablePluginListingCopy takes pluginId (string). VERIFIED: C, search `hasRestorablePluginListingCopy:I().args({pluginId:y()})`. Reply: boolean. VERIFIED: C, search `hasRestorablePluginListingCopy:{args:"object",reply:"boolean"`.
- unpublishPluginListing takes pluginId and an optional teamId. VERIFIED: C, search `unpublishPluginListing:I().args({pluginId:y(),teamId:oe()})`. Reply: record, fields UNKNOWN. VERIFIED: C, search `unpublishPluginListing:{args:"object",reply:"record"`.
- Confirm dialog: VERIFIED that the unpublish flow has a flag named keepsPrivateCopy and a confirm message that depends on it. V, search `keepsPrivateCopy`.
- What a restorable copy is: INFERRED. It is a private copy of the plugin that remains after the listing is removed and can be put back on the listing. The exact storage is UNKNOWN.
- No RPC with Plugin and Publish or Unpublish in its name was found in P. The DashboardService plugin RPCs are install, update, uninstall and list (for example ListMarketplacePlugins, InstallUserPlugin). VERIFIED names. So the listing pair is gateway-only by name. No case in the desktop adapter. Backend route UNKNOWN.
- Changes state: unpublish yes. The restorable check is read-only.

## 5. Cloud agents

- What it is: VERIFIED that the cloud-agent calls take a bcId. The matching backend service is BackgroundComposerService, whose RPCs use the names GetBackgroundComposerInfo, GetBackgroundComposerConversation, StreamBackgroundComposerUpdates, ListBackgroundComposerArtifacts, GetBackgroundComposerArtifact and GetBackgroundComposerUserSettings. P, search `GetBackgroundComposerInfoRequest|1 bc_id 9`.
- INFERRED: a cloud agent is a background composer run attached to a bot's agent. The name matches the Cursor background agent family, which the bundle builds on. This is an interpretation, not a field-level proof. The link between a bot and its cloud agent is by bcId (and agentId in some calls).
- getCloudAgentInfo takes bcId, includeFiles (bool) and includeArtifacts (bool). VERIFIED: C, search `getCloudAgentInfo:I().args({bcId:y(),includeFiles`. Reply: record-or-null. VERIFIED: C, search `getCloudAgentInfo:{args:"object",reply:"record-or-null"`.
- getCloudAgentConversation takes bcId. VERIFIED: C, search `getCloudAgentConversation:I().args({bcId:y()})`. Reply: record-or-null. VERIFIED: C, search `getCloudAgentConversation:{args:"object",reply:"record-or-null"`.
- stopCloudAgent takes bcId. VERIFIED: C, search `stopCloudAgent:I().args({bcId:y()})`. Reply: void. VERIFIED: C, search `stopCloudAgent:{args:"object",reply:"void"`. It changes state (stops a run). No stop RPC was found in P, and the desktop adapter has no case for it, so its backend route is UNKNOWN.
- ensureCloudAgentArtifacts takes agentId and bcId and is declined in parity. VERIFIED from the parity file and C search `ensureCloudAgentArtifacts:I().args`.
- Routing of info and conversation: VERIFIED that the desktop adapter maps getCloudAgentInfo to a reader's read call and getCloudAgentConversation to a second reader's read call. M, search `case"getCloudAgentInfo":return qn`. The readers are built on the BackgroundComposerService client (first pass). Their output shapes were not decoded in this pass: UNKNOWN.
- Artifact downloads: GetBackgroundComposerArtifact takes bc_id and absolute_path and returns url (string) and expires_at (string). VERIFIED: P, search `GetBackgroundComposerArtifactRequest|1 bc_id 9`. The returned url is a temporary access link. Mark it **Secret**.
- Whether any of this exists for the desktop only: UNKNOWN. The background composer RPCs apply to backend-hosted runs. Whether the desktop also keeps local cloud-agent state was not established.

## 6. Cloud-agent apps

Gateway commands (class "person" unless noted):
- listCloudAgentPublishedApps takes no arguments. VERIFIED: C, search `listCloudAgentPublishedApps:I().noArgs`. Reply: record, fields UNKNOWN. VERIFIED: C, search `listCloudAgentPublishedApps:{args:"none",reply:"record"`.
- updateCloudAgentPublishApp takes bcId, slug, apex, visibility (enum, see below), muteRedeployPrompts and requireConfirmationForUpdates. VERIFIED from the parity row (search `updateCloudAgentPublishApp` in tui/docs/parity.json) and C, search `updateCloudAgentPublishApp:I().args({bcId:y(),slug:y(),apex:y(),visibility:R(BK)`. Reply: record, fields UNKNOWN.
- unpublishCloudAgentPublishApp takes bcId, slug and apex. VERIFIED: C, search `unpublishCloudAgentPublishApp:I().args({bcId:y(),slug:y(),apex:y()})`. Reply: record, fields UNKNOWN.
- createCloudAgentAppsGateTicket takes slug and apex. VERIFIED: C, search `createCloudAgentAppsGateTicket:I().args({slug:y(),apex:y()})`. Reply: record, fields UNKNOWN.
- getCloudAgentAppSecrets takes bcId and projectDir. VERIFIED: C, search `getCloudAgentAppSecrets:I().args({bcId:y(),projectDir:y()})`. Reply: record, fields UNKNOWN.
- setCloudAgentAppSecrets takes bcId, projectDir and secrets, a list of name and value pairs. VERIFIED: C, search `setCloudAgentAppSecrets:I().args({bcId:y(),projectDir:y(),secrets:le(b({name:y(),value:y()}))`. Reply: record, fields UNKNOWN.
- tellCloudAgentAppSecretsSet takes bcId, projectDir, names (list of strings), refused (list of refusal records) and applyNeeded. VERIFIED: C, search `tellCloudAgentAppSecretsSet:I().args({bcId:y(),projectDir:y(),names`. Reply: record, fields UNKNOWN.
- Refusal record: name (string), kind (enum), message (string) and permanent (bool). The kind enum has not_owned, not_sensitive, host_error and value_not_saved. VERIFIED: C, search `Tte=b({name:y(),kind:be("app secret refusal kind",rK)`.

No cloud-app command has a case in the desktop adapter (M, searches for each name find only the reply tables). So for a temporal bot these commands hit the temporal-agent path in C (section 1), and their replies are not established.

Visibility enum:
- The apps visibility uses the same values as the general visibility enum: private, team and public. VERIFIED: C, search `"publish visibility",nK` and `nK=["private"`.

Gate ticket (**Secret**):
- A gate ticket is a short-lived credential that lets the viewer pass the app's gate page. It is marked **Secret** because it grants access. INFERRED that the app holds it only for the webview step.
- The renderer flow has three outcomes: a ticket is issued, the gate is off, or the request is refused. VERIFIED: R, search `appsGateTicket`.
- The app opens the gate in an in-app webview and checks the page origin before using the ticket. VERIFIED: R, search `appsGateTicket`.
- Lifetime and reply field names: UNKNOWN.

Secrets (values are **Secret**):
- getCloudAgentAppSecrets: INFERRED that the reply returns names only, since tellCloudAgentAppSecretsSet and the approval card work from names. Whether the reply ever includes values, and how it masks them: UNKNOWN. Read only names when capturing.
- setCloudAgentAppSecrets: the values are written here. VERIFIED from the argument shape. Values are **Secret**.
- The approval card for app secrets lists the names. VERIFIED: C, search `case"app_secrets_request"`.
- Masking and entry in the app: the secrets store is in R (search `CloudAgentAppSecrets`). Masking detail was not traced: UNKNOWN.
- Changes state: yes for update, unpublish, set and tell. The get and list calls and the gate-ticket call are read or grant-only.

## 7. Publish proposals

- getCloudAgentPublishProposals takes bcId. VERIFIED: C, search `getCloudAgentPublishProposals:I().args({bcId:y()})`. Reply: record. VERIFIED: C, search `getCloudAgentPublishProposals:{args:"object",reply:"record"`. Reply fields UNKNOWN.
- confirmCloudAgentPublishProposal takes agentId, bcId, proposalId, slug, visibility and requireConfirmationForUpdates. VERIFIED from the parity row and the C argument list (search `confirmCloudAgentPublishProposal:I().args`). Reply: record, fields UNKNOWN.
- dismissCloudAgentPublishProposal takes agentId (optional), bcId and proposalId. VERIFIED: C, search `dismissCloudAgentPublishProposal:I().args({agentId:W(),bcId:y(),proposalId:y()})`. Reply: record, fields UNKNOWN.
- Proposal object: UNKNOWN in full. No field list was found in C's reply tables (they say only record), and the proposals store in R was not traced in this pass. The args suggest it carries a slug and a proposed visibility. INFERRED.
- How a proposal arises: UNKNOWN. INFERRED that it is created on the server after the agent builds an app and the user then confirms a publish.
- Confirming: changes state. It publishes or updates the app as the proposal describes. Dismissing changes the proposal state only.
- Card: VERIFIED that the card kind publish_approval exists in the same switch as the other approval-style card kinds (local tool permission, virtual card approval, app secrets). Its card title shows the slug. C, search `case"publish_approval"`. INFERRED that proposals feed these cards.
- Name clash to avoid: server_proposal in the renderer and main is an auto-review text source, not a publish proposal. VERIFIED: M, search `case"server_proposal"`.
- The renderer polls the proposals with a backoff store. VERIFIED: R, search `CloudAgentPublishProposals`.

## 8. Browser handoff and URLs

- Gate ticket: the app opens the gate page in an in-app webview, not the system browser. VERIFIED: R, search `appsGateTicket`. The TUI would need a browser handoff for this step.
- Template share URL: VERIFIED that every template reply carries a shareUrl built from a fixed bot path and the share id. M, search `function yR(e)` and `shareUrl:yR(`. The host is fixed in the bundle; the TUI can build the same link from a share id without a call.
- Published app URL: INFERRED that the app address is formed from slug and apex. Exact format UNKNOWN.
- Bot marketplace listing page: no URL field in the publish reply. The page address and how the renderer opens it: UNKNOWN.
- Template public page: GetPublicGrokBotTemplate exists as an RPC name. Whether the desktop opens a page for it: UNKNOWN.
- How the step finishes: for the gate, the webview yields one of the three gate outcomes (ticket, gate off, refused). VERIFIED: R, search `appsGateTicket`. For the other handoffs, the desktop re-reads state by polling or on return. INFERRED.
- Template publish errors are shown as states (see section 1), not as URLs. VERIFIED: T, search `public-sharing-disabled`.

## 9. Events

- Event names for these areas on the local event stream: UNKNOWN in this pass. The /events names were not traced.
- VERIFIED: approval-style cards are emitted for publish_approval and app_secrets_request. C, search `case"app_secrets_request"`.
- VERIFIED: the backend has a BackgroundComposer update stream (StreamBackgroundComposerUpdates) with an update-kind enum. P, search `StreamBackgroundComposerUpdates`. It could drive refresh of cloud-agent state for a temporal bot without polling. Its request and kind values are UNKNOWN in this pass.
- VERIFIED: publish, unpublish and dismiss RPCs return their outcome synchronously (see section 2 outcome enums). The TUI can refresh by re-reading after the call returns.
- The proposals and apps stores poll. VERIFIED: R, search `CloudAgentPublishedApps`.
- No event for "publish finished" was found in this pass: UNKNOWN.

## 10. Desktop-only entries and parity proposals

No entry in this unit is confirmed desktop-only. The following are the proposed parity statuses:

- createCloudAgentAppsGateTicket: handoff. The gate runs in an in-app webview, and the ticket is **Secret**. The TUI should open the browser step instead of holding a ticket.
- setCloudAgentAppSecrets: handoff for value entry. Secret values should not be typed into chat. The names-only tell path can stay planned.
- getCloudAgentAppSecrets: keep planned for names only. Declined for any value reveal.
- stopCloudAgent: keep planned. If routing shows it only affects local state, change to declined.
- Skill publish family (getSkillPublishTargets, publishSkill, resyncPublishedSkill, unpublishSkill): keep planned. Change to declined only if routing shows local-only effects.
- Plugin listing pair (hasRestorablePluginListingCopy, unpublishPluginListing): keep planned pending routing.
- Cloud app commands (list, update, unpublish) and proposal commands (get, confirm, dismiss): keep planned pending routing.
- ensureCloudAgentArtifacts and setBotTemplateVisibility are already declined in parity. This unit did not re-decide them. setBotTemplateVisibility is backend-routed, so its decline reason should be revisited by the owner.

## 11. Read-only captures (no side effects, smallest arguments)

- listBotTemplates: no arguments. Gateway, read-only.
- getBotTemplateExportPolicy: no arguments. Gateway, read-only. Settles the export-policy question.
- getBotTemplateVersion: shareId and version of one template you own. Gateway, read-only; the reply includes recipe sections, so capture keys only.
- getSkillPublishTargets: no arguments. Gateway, read-only.
- listCloudAgentPublishedApps: no arguments. Gateway, read-only.
- hasRestorablePluginListingCopy: pluginId of one listed plugin.
- getCloudAgentInfo: bcId of one cloud agent, includeFiles false, includeArtifacts false.
- getCloudAgentConversation: bcId of one cloud agent.
- getCloudAgentPublishProposals: bcId of one cloud agent.
- getCloudAgentAppSecrets: bcId and projectDir. Capture names only. The reply may hold values, so mark it **Secret** and do not store the raw reply.
- Backend ListGrokBotTemplates (no request fields), GetGrokBotTemplateExportPolicy (no request fields) and GetGrokBotTemplateVersion (shareId and version): read-only RPCs.
- Backend GetBackgroundComposerInfo: bc_id of one cloud agent.
- Backend GetBackgroundComposerArtifact: capture only the presence of url and expires_at. The url is a temporary access link and is **Secret**.

Do not call any of: publishBotTemplate, deleteBotTemplate, setBotTemplateVisibility, PublishGrokBotAgent, UnpublishGrokBotAgent, publishSkill, resyncPublishedSkill, unpublishSkill, unpublishPluginListing, stopCloudAgent, updateCloudAgentPublishApp, unpublishCloudAgentPublishApp, createCloudAgentAppsGateTicket, setCloudAgentAppSecrets, confirmCloudAgentPublishProposal or dismissCloudAgentPublishProposal. Each changes state or grants access.

## 12. Open items

- The GrokBotTemplateOwnerType values and the full recipe layout (whether secrets or connector accounts sit inside the blob).
- Gateway reply field names for the skill, plugin, cloud-app and proposal commands. The C reply table says record only, and no handler was found by name.
- The desktop default branch in the adapter (section 13 note): whether it returns unimplemented or handles the command locally. This decides whether those commands fail for temporal bots.
- Output shapes of the two cloud-agent readers (info and conversation).
- Gate ticket lifetime and its reply field names.
- Secret reply content and masking for getCloudAgentAppSecrets.
- Proposal object fields and origin (the proposals store in R, search `CloudAgentPublishProposals`).
- /events names for publish and proposal changes.
- Listing URL format for bots and apps. The template share URL format is VERIFIED (section 8).
- Confirm steps for delete, visibility, unpublish and publish.

## 13. Gateway reply and routing table (second pass)

Each row: gateway command, reply type from C's reply table, reply fields, desktop adapter case in M, and backend RPC it reaches. "none" means no case in M for that name.

| Command | Reply type (C) | Reply fields | Adapter case (M) | Backend RPC (service) |
|---|---|---|---|---|
| publishBotTemplate | record | template converter fields (section 1), with version | N.publish | ActivateGrokBotTemplateVersion (GrokBotService) |
| deleteBotTemplate | void | none (null) | N.delete | DeleteGrokBotTemplate (GrokBotService) |
| setBotTemplateVisibility | record | template converter fields (section 1) | N.setVisibility | SetGrokBotTemplateVisibility (GrokBotService) |
| listBotTemplates | record | UNKNOWN | not traced | ListGrokBotTemplates (INFERRED) |
| getBotTemplateVersion | record | recipe view (section 1) | N.getVersion | GetGrokBotTemplateVersion, then the recipe link (GrokBotService) |
| getBotTemplateExportPolicy | record | exportPolicy (all, team_only or none) when valid, else empty | N.getExportPolicy | GetGrokBotTemplateExportPolicy (GrokBotService), cached |
| getSkillPublishTargets | record | UNKNOWN | none | none found |
| publishSkill | record | UNKNOWN | none | none found |
| resyncPublishedSkill | record | UNKNOWN | none | none found |
| unpublishSkill | record | UNKNOWN | none | none found |
| hasRestorablePluginListingCopy | boolean | the boolean only | none | none found |
| unpublishPluginListing | record | UNKNOWN | none | none found |
| getCloudAgentInfo | record-or-null | UNKNOWN | reader R (read) | background composer reader (BackgroundComposerService, first pass) |
| getCloudAgentConversation | record-or-null | UNKNOWN | reader M (read) | background composer reader (BackgroundComposerService, first pass) |
| stopCloudAgent | void | none | none | none found |
| listCloudAgentPublishedApps | record | UNKNOWN | none | none found |
| updateCloudAgentPublishApp | record | UNKNOWN | none | none found |
| unpublishCloudAgentPublishApp | record | UNKNOWN | none | none found |
| createCloudAgentAppsGateTicket | record | UNKNOWN (ticket, gate outcome) | none | none found |
| getCloudAgentAppSecrets | record | UNKNOWN (names expected) | none | none found |
| setCloudAgentAppSecrets | record | UNKNOWN | none | none found |
| tellCloudAgentAppSecretsSet | record | UNKNOWN | none | none found |
| getCloudAgentPublishProposals | record | UNKNOWN | none | none found |
| confirmCloudAgentPublishProposal | record | UNKNOWN | none | none found |
| dismissCloudAgentPublishProposal | record | UNKNOWN | none | none found |

Routing note: for a temporal bot, C calls the backend action for every command (C, search `for Temporal agents`). The rows marked none have no case in M, so the answer depends on M's default branch for unknown names, which calls a generic helper. That helper was not traced in this pass, so for those rows the route is UNKNOWN rather than local-only. If the default returns unimplemented, C throws the temporal-agent error for that command.

Field-level shapes for the record rows are not in C's tables and no handler body was located. The next capture step is a read-only call to the list and read commands in section 11, recording the reply keys only.
