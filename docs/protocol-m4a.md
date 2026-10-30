# M4a protocol research: desktop 0.77.0

Offline bundle inspection; no service, private configuration or credential file was accessed. UNKNOWN means the inspected material did not establish a detail, not that a feature is absent. VERIFIED means client code/declarations establish the claim; live shapes are explicitly attributed to L below. It does not prove deployed server behavior. INFERRED marks interpretation beyond those observations. `?` denotes optional, `[]` repeated; protobuf JSON int64s are decimal strings. **Secret** marks credentials and containers that can hold them. See protocol-m2 section 10, protocol-temporal sections 1–2 and protocol-m3 section 10 for routing/envelopes.

Bundle citation keys: **C** = `dist/node-agent-coordinator/main.cjs`; **M** = `dist/electron-main/main-app.cjs`; **P** = `dist/electron-main/proto.cjs`. Each citation includes a searchable string. These paths are relative to the bundle root.

Renderer citation keys: **R** = `dist/renderer/assets/index.eager-app-BtIHj2If.js`;
**A** = `dist/renderer/assets/chunk-automation-detail-panel-9qvnSTj3.js`;
**B** = `dist/renderer/assets/chunk-team-bot-plugins-dialog-list-BlKsSPQE.js`;
**V** = `dist/renderer/assets/chunk-view-nVmZzLNj.js`.
**D** = `dist/renderer/assets/chunk-plugin-detail-view-AZNiTswy.js`;
**N** = `dist/renderer/assets/chunk-native-plugin-detail-D89mZ9ek.js`.
**L** = supplied sibling `tui/docs/protocol-m4-live.md`, read-only captures dated 2026-10-31, authoritative for current
server serialization. Those observations are not claims that this research called the service.

## 1. Connector catalog and state

**VERIFIED:** `getMcpCatalog()` returns an array; `getMcpPluginLogo({url:string})` returns a record or null; `getMcpState()` returns a record; `listMcpServerTools({serverId:string})` returns an array. `refreshMcp({completion?:{serverId:string,serverName:string,accountKey:string,serverIdentifier?:string,serverUrl?:string,requestingAgentId:string|null,outcome?:"connected"|"cancelled",failureDetail?:string}})` accepts an optional completion record. Its reply shape remains UNKNOWN. **C `getMcpCatalog:I().noArgs`, `getMcpCatalog:{args:"none"`, `lne=b({serverId`**.

**VERIFIED:** `GetGrokBotUserMcpSettings({}) → {settings?:GrokBotUserMcpSettings}`. Settings contain `servers: {serverId:string,customInstructions?:string,disabledTools:string[]}[]`, `customInstructionsByName:map<string,string>`, `userTimeZone?:string`, `userTimeZoneOverride?:string`, `updatedAtMs:int64`, and `autoReviewInstructions?:message`. **P `GrokBotUserMcpSettings|`, `GrokBotUserMcpServerSettings|`, `GetGrokBotUserMcpSettingsResponse|`**.

**VERIFIED routing:** gateway catalog/state/logo/tool-list commands stay on gateway for temporal bots; none has a backend
action case. Connector screens instead use desktop MCP IPC through `EHn`, then main's MCP manager: catalog → `getCatalog`,
state → `listServersForDisplay`, tools → `listServerTools`. Identically named desktop and gateway methods are distinct.
Desktop logo resolution/downscaling returns an image data URL or null; gateway logo-record fields remain **UNKNOWN**.
Read-only getMcpPluginLogo would settle its wire fields; refreshMcp's reply requires its host handler or a separately
authorized refresh capture, since refresh is not passive.
Sources: **C `function Hx(`, `function n3(`; R `function EHn(`; M `function tbt(`, `function K_t(`**.

**VERIFIED catalog projection:** `id,name,pluginName,displayName,description,category,repositoryUrl,websiteUrl,iconUrl,
connectors,skills`, optional `categoryKey,categoryKeys,fields,unsupportedFieldKeys,marketplace,isPublicListed,publisher,
popularityRank`, plus private-marketplace/policy metadata. L saw about 490 entries; publisher has
`name,displayName,isUserOwned`; connector summaries have `name,description`; setup fields have
`key,label,hint,placeholder,type,isRequired,isSecret,options?` with option `label,rawValue`.
Values entered for isSecret=true are **secret**; configuration/option values can also hold credentials.
Sources: **M `function f4n(`; B `function Q(`; V `e.isSecret===`**; **L, Connectors**.

**VERIFIED current state (L):** `{servers[]}`; rows have `id,name,serverIdentifier,rowServerIdentifier,pluginId,
pluginDisplayName,pluginTeam,isTeamServer,accountKey,credentialIsCursorAccount,cursorScmProvider,customInstructions,
command,url,transport,servedBy,toolCount,status,statusDetail`. Account keys are identifiers/labels, not token values;
command/URL/configuration strings may embed **secrets**. L saw 14 servers, status=connected, and
statusDetail.kind=authentication_required; retain both fields rather than deriving one from the other.
Sources: **M `function The(`, `function pnr(`, `summarizeServers(t,n){`**; **L, Connectors**.

**VERIFIED per-bot source:** desktop `getGrokBotAgentMcpServers({agentId})` calls DashboardService
`GetAvailableMcpServers({grokBotAgentId:agentId})`, keeps enabled rows, then creates credential-presence summaries.
Account listing uses GetAvailableMcpServers with extra MCP-config reads for stdio rows. These differ from per-bot plugin
selection (section 5). Sources: **M `async function ynr(`, `async function gnr(`, `async listGrokBotAgentServers(`**.
L's user MCP settings contained only autoReviewInstructions:{isEnabled},updatedAtMs,userTimeZone, without per-server rows;
the declaration above must not be mistaken for populated account settings. **M `function pq(`; L, Connectors**.

## 2. Connector authentication

**VERIFIED validator:** authenticateMcpServer requires serverId:string; all remaining fields are optional:
accountKey:string, trigger:connector_card, entryPoint:chat_card|marketplace|plugin_detail|yours_tab|settings|deep_link|other,
forceReauth:boolean, requestingAgentId:string, oauthRedirectUri:string, dataCenter:string,
shareWithBot:{agentId,pluginId,acknowledgedWarningVersion:number}. Reply is a record. **C `ga=b({serverId`**.

**VERIFIED temporal mapping:** known temporal requestingAgentId plus valid oauthRedirectUri selects DashboardService
CheckHttpMcpStatus. Numeric row IDs → serverIds:[number]; grok:-prefixed IDs → stripped serverIdentifiers:[identifier];
other bot identifiers → serverIdentifiers plus grokBotAgentId. It copies redirect URI, uses trimmed accountKey or default,
forceReauth true only, userInitiated=true, optional nonempty dataCenter, and maps sharing to
shareWithBotAgentId/shareWithBotPluginId/shareAcknowledgedWarningVersion. GetAvailableMcpServers({grokBotAgentId?})
supplies names/accounts. Without redirect URI authentication stays on gateway. Outcomes: started with authorizationUrl
(**secret**, OAuth state/query) and serverName; already-authenticated/not-configured/unreachable/not-supported, optional reason.
Sources: **M `function BKn(`, `function NKn(`, `function LKn(`, `function u_t(`; C `function n3(`**.

**VERIFIED:** `completeMcpOAuth({code:string,state:string}) → null` maps to DashboardService `CompleteMcpOAuth({authorizationCode:code,stateId:state})` for the temporal path. `code` and `state` are sensitive OAuth credentials; do not log them. **C `completeMcpOAuth:I().args`; M `function u_t(`**.

**VERIFIED desktop completion:** desktop MCP IPC registers the authorization URL with loopback before opening it.
Ordinary callback: HTTP loopback /callback, default localhost port 8787; alternatives 18787/28787/31787. Registration can
rewrite the opened URL for the listening port. Hosted callback https://www.cursor.com/agents/mcp/oauth/callback can relay
according to state suffix. Shared redirect constants also name grokbot://mcp/oauth/callback and legacy
cursor://anysphere.cursor-mcp/oauth/return; they do not prove current desktop waits on a custom-scheme handler.
The traced desktop path is loopback. **M `function IZn(`, `function Sme(`, `function tbt(`, `function fJ(`, `hFt=new Map`**.

**VERIFIED:** loopback receives state/code (**secret**) or error/error_description, exchanges through CompleteMcpOAuth,
then invokes noteAuthCallbackReceived({stateId,serverName?,accountKey?}). Watches match state, with unique account/name
fallback. They also poll ValidateMcpOAuthTokens for hasValidToken, or observe listing accounts[].hasToken /
hasDefaultSlotToken become true. Default cadence five seconds, lifetime 15 minutes; some watches complete only on callback.
Success reloads state and emits completion. Coordinator also remembers started OAuth states for 15 minutes to route completion
without a target ID. **M `function Sme(`, `async authWatchTokenLanded(`, `async readListingSignedIn(`,
`async pollPendingAuthWatch(`, `async finishPendingAuthWatch(`, `PSt=5e3`; C `function Vre(`, `$z=15*6e4`, `function n3(`**.

**VERIFIED failure/cancel:** provider error, missing code, rejected exchange and expired callback produce an error page
and rejection notification; transient exchange can leave a retryable page. Rejection/removal emits outcome=cancelled with
failureDetail?. Watch expiry reports timeout, without universally emitting cancellation. Port binding can return
port-unavailable, projected as unreachable. Browser closure is not success.
**M `function Sme(`, `notifyWatchCancelled(t,n){`, `noteAuthCallbackRejected(t){for`, `expirePendingAuthWatch(t){`, `function jEt(`**.

**VERIFIED completion:** {serverId,serverName,accountKey,requestingAgentId:string|null,serverIdentifier?,serverUrl?,
outcome?:connected|cancelled,failureDetail?}; success may omit outcome. Desktop IPC emits mcp-auth-completed,
calls refreshMcp({completion}), and emits mcp-servers-updated with {servers}. Gateway aliases are in section 10.
**C `lne=b({serverId`; M `async finishPendingAuthWatch(`, `notifyWatchCancelled(t,n){`, `setAuthCompletedEmitter:`, `async function O(V)`**.

**INFERRED terminal feasibility:** no deep-link handler is needed if a permitted loopback/hosted receiver delivers and
exchanges the code. Polling observes stored credentials; it cannot replace a required callback exchange. getMcpState alone
is weak evidence: existing connected accounts, stale summaries or grants can mislead. Compare exact account/identifier and
fresh baseline; desktop token/listing checks are stronger. **UNKNOWN:** provider-specific terminal redirects and gateway-only
refresh freshness. Settle with separately authorized user sign-in and sanitized callback metadata plus before/after read-only
ValidateMcpOAuthTokens, CheckHttpMcpStatus(statusOnly=true) and getMcpState; never retain actual codes/state/authorization URLs.

## 3. Connector accounts and permissions

**VERIFIED gateway validators/reply categories:** `removeMcpServer({serverId:string}) → record`; `removeMcpAccount({serverId:string,accountKey:string}) → record`; `renameMcpAccount({serverId:string,accountKey:string,newAccountKey:string}) → record`; `setMcpCustomInstructions({serverId:string,instructions:string}) → record`; `toggleMcpToolDisabled({serverId:string,toolName:string}) → array`. Record and array member fields are UNKNOWN. **C `JK={serverId`, `fne=b({serverId`, `removeMcpServer:{args:"object"`**.

**VERIFIED protobuf declarations:**

| RPC | Request → response |
|---|---|
| SetGrokBotMcpToolPermissions | `serverId:string,tools:map<string,enum>,reads?:enum,writes?:enum` → `server?:message` |
| SetGrokBotUserMcpSettings | `settings?:GrokBotUserMcpSettings,keepDisabledTools:boolean` → `settings?:GrokBotUserMcpSettings` |
| ClearGrokBotConnectorAlwaysAllow | `{}` → `clearedCount:uint32` |
| GetGrokBotConnectorSharedSpaceAllowlist | `{}` → `serverIds:string[]` |
| UpdateGrokBotConnectorSharedSpaceAllowlist | `addServerIds:string[],removeServerIds:string[]` → `serverIds:string[]` |

**P `SetGrokBotMcpToolPermissionsRequest|`, `SetGrokBotUserMcpSettingsRequest|`, `ClearGrokBotConnectorAlwaysAllowResponse|`, `GetGrokBotConnectorSharedSpaceAllowlistResponse|`, `UpdateGrokBotConnectorSharedSpaceAllowlistRequest|`**.

**VERIFIED gateway routes:** removeMcpServer/removeMcpAccount/renameMcpAccount/setMcpCustomInstructions/
toggleMcpToolDisabled all stay on gateway for temporal bots: no backend action cases. Their opaque reply members remain
**UNKNOWN**; host handlers or separately authorized mutation captures would settle them.
**C `function Hx(`, `function n3(`**.

**VERIFIED desktop alternative:** connector UI IPC uses its MCP manager independently of these gateway commands.
Rename → DashboardService RenameMcpOAuthAccount({serverId:number,accountKey,newAccountKey}); removal →
DeleteMcpOAuthAccount({serverId:number,accountKey,serverUrl?}). Grok-served sign-out instead uses DeleteMcpOAuthToken with
empty serverUrl, default accountKey, source=sand, serverIdentifier. Server removal can uninstall a user plugin or edit account
MCP configuration; team/required policy constrains removal. These are not temporal-specific remove RPCs.
**M `async signOutGrokRow(`, `async removeServer(`, `function AZn(`**.

**VERIFIED permissions:** desktop instructions save user MCP settings and synchronize host settings; UI uses
setMcpToolPermissions, not gateway binary toggle. UI auto_review/always_allow/needs_approval/blocked map to the common
GrokBotToolPermission enum: 0 UNSPECIFIED, 1 ALWAYS_ALLOW, 2 NEEDS_APPROVAL, 3 BLOCKED. The same enum applies to each tools-map
value and reads/writes. Unknown received enums normalize to needs approval; unspecified is omitted from normalized policy.
Returned server is {serverId,disabledTools:string[],policy:{tools:map<string,enum>,reads:enum,writes:enum}}.
**M `setMcpCustomInstructions(V)`, `function Kce(`, `function Yce(`, `function Mpt(`, `setToolPermissions:async`;
P `"GrokBotToolPermission"`, `GrokBotMcpServerToolPermissions|`, `GrokBotToolPermissionPolicy|`**.

**VERIFIED display statuses:** connected/needsAuth/initializing/error/disconnected/disabledByTeamAdminPolicy/needsGrant.
Backend discovery loading normalizes to initializing. statusDetail.kind branches found:
sign_in_pending/authentication_required/failed_to_load/not_reported_by_backend/bot_computer_unreachable/
not_reported_by_bot_computer/disabled_by_team_admin/grant_required/runs_on_bot_computer. Details can contain
message/reason/technicalDetail. **M `function Fy(`, `function yP(`, `function Qv(`, `function htr(`,
`disabled_by_team_admin`, `runs_on_bot_computer`**.
**VERIFIED distinction:** McpConnectorAuthState maps to signedIn/signedOut/unavailable, separately from display status.
L's listener read has {integrations:[{platform,state,isConnected,neededByCount}]}, six platforms, state=idle.
**UNKNOWN:** full listener-state enum; host validator would settle it. Read-only getListenerIntegrations during user-led
connection/failure reveals observed values, not the complete accepted set. Do not reuse connector statuses.
**M `function cZn(`; R `function VBn(`, `function YBn(`; L, Channels**.

## 4. MCP apps

**VERIFIED:** `readMcpAppResource` accepts `serverIdentifier:string,resourceUri:string,agentId?:string,entryId?:string,sessionId?:string,documentSha256?:string`. Temporal routing calls `ReadGrokBotMcpAppDocument` with `agentId,sessionId,entryId`; normalized reply is `{document:{resourceUri:string,html:string,meta?:object}}`. `callMcpAppTool` accepts `serverIdentifier:string,toolName:string,argumentsJson:string,userActivated:boolean,agentId?:string,entryId?:string,sessionId?:string`; temporal routing calls `CallGrokBotMcpAppTool`, yielding `resultJson` or an error, optional `code` and `usedActivation`. See protocol-temporal section 1 for validation and failure details. **C `ma=b({serverIdentifier`, `fa=b({serverIdentifier`; M `function M_t(`, `function oYn(`**.

**VERIFIED embedding:** renderer stages HTML and optional metadata CSP through desktop stageMcpAppDocument, receives
frameUrl/bridgeKey, and derives permissions/border preference from metadata. BridgeKey is a **secret capability**;
HTML/arguments/results can contain private content or **secrets**. Source: **R `function oVn(`**.
**INFERRED:** terminal text display/app handoff is feasible; rendered-tool parity requires document/activation protocol,
not simply opening arbitrary HTML. Coordinator attempts backend for saved-document hashes and agent/entry tool contexts,
with gateway fallback on unimplemented; **C `function n3(`**.

## 5. Plugins and skills

**VERIFIED:** `skillsCatalog()` and `syncPluginSkills()` return arrays; `getPluginSyncStatus()` returns a record. Catalog and status details follow below; sync-result item fields remain UNKNOWN. **C `skillsCatalog:I().noArgs`, `skillsCatalog:{args:"none"`**.

**VERIFIED protobuf declarations:** `GetGrokBotAgentPlugins({agentId:string,includeMcpConfig:boolean}) → {marketplace?:message,plugins:message[],serviceAccountsEnabled?:boolean,delegatedAuthAvailable?:boolean,shareablePluginIds:int64[]}`. `SetGrokBotAgentPlugins({agentId:string,plugins:message[]}) → {marketplace?:message,plugins:message[]}`; `SetGrokBotAgentPluginVariables({agentId:string,pluginId:int64,variables?:message,mergeWithStored:boolean})` returns the same response shape. Treat variable values as potentially secret. **P `GetGrokBotAgentPluginsRequest|`, `GetGrokBotAgentPluginsResponse|`, `SetGrokBotAgentPluginsRequest|`, `SetGrokBotAgentPluginVariablesRequest|`**.

**VERIFIED:** `ListGrokBotAgentSkills({agentId:string}) → {skills:{id:string,name:string,description:string,body:string,source:string}[]}`. `AddGrokBotAgentSkill({agentId:string,name?:string,description?:string,content:string})` and `UpdateGrokBotAgentSkill({agentId:string,name:string,description?:string,content:string})` return `{marketplace?:message,plugins:message[],skill?:message}`. `RemoveGrokBotAgentSkill({agentId:string,name:string})` returns `{marketplace?:message,plugins:message[]}`. **P `GrokBotAgentSkill|`, `AddGrokBotAgentSkillRequest|`, `UpdateGrokBotAgentSkillRequest|`, `RemoveGrokBotAgentSkillRequest|`**.

**VERIFIED:** `AttachGrokBotAgentDelegatedCredential({agentId:string,pluginId:int64,accountKey?:string,acknowledgedWarningVersion:int32})` and `RemoveGrokBotAgentDelegatedCredential({agentId:string,pluginId:int64})` return `{marketplace?:message,plugins:message[]}`. These calls manage credential access; account identifiers and returned plugin configuration may be sensitive. **P `AttachGrokBotAgentDelegatedCredentialRequest|`, `RemoveGrokBotAgentDelegatedCredentialRequest|`**.

**VERIFIED routes:** gateway skillsCatalog/syncPluginSkills/getPluginSyncStatus stay on gateway for temporal bots.
Renderer separately loads ListGrokBotAgentSkills via desktop getGrokBotAgentTemplateSkills for server-routed bots,
merges by ID and replaces matching managed gateway rows with server skill content.
**C `function Hx(`, `function n3(`; R `function QNn(`, `function J8(`; M `function Qct(`**.

**VERIFIED L catalog:** about 1,900 rows: id/name/description/publisher/iconUrl/source:marketplace/install:{kind,url};
kind=url observed. Renderer also accepts install:{kind:content,content,name}; content goes to importAgentWorkflowText,
URL to importAgentWorkflowUrl. It does not open that import URL as an OAuth ceremony. getPluginSyncStatus currently has
authBlocked[]; its element schema and syncPluginSkills array members remain **UNKNOWN**. Host implementation or a sanitized
read of getPluginSyncStatus with a blocked item would settle status members; sync-result capture requires separate authorization.
**R `function QNn(`; C `getPluginSyncStatus:{args:`; L, Plugins and skills**.

**VERIFIED bot-manage distinction:** plugins are selected packages that can contain MCP definitions and skills; skills are
named instruction documents with body/content and source metadata. Screens show package identity/install mode/configured
variables/plugin skills/MCP server names/credentials. Skill detail shows name/description/Markdown; managed/template entries
are read-only, editable entries require nonblank name, description and body.
**M `function RGn(`; P `GrokBotAgentPlugin|`, `GrokBotAgentPluginSkill|`; V `M=i.source===`**.

**VERIFIED direct bot-management callers:** main Qct calls GetGrokBotAgentPlugins with logical/gateway agentId and
includeMcpConfig=true; PermissionDenied retries without that flag. L's empty-plugin bot returned customMcpPerUser and
serviceAccountsEnabled; this is not the normalized desktop listing. ListGrokBotAgentSkills maps to id/name/description/body,
with NotFound → []. SetGrokBotAgentPlugins maps entries selecting pluginId, configUpdate:{pluginId,mcpConfigJson}, or
inline:{name,displayName,description,mcpConfigJson}. Plugin IDs are validated positive integers then converted to bigint.
SetGrokBotAgentPluginVariables sends variables as a protobuf Struct and mergeWithStored true only. Add/update/remove skill
and attach/remove delegated-credential calls use the RPCs declared above; this is the desktop backend path alongside gateway
workflow commands. Sources: **M `function Qct(`, `function wGn(`, `function TM(`, `function MGn(`; L, Plugins and skills**.

**VERIFIED plugin message:** pluginId/name/displayName/description/logoUrl?/ownedByMarketplace/installMode/variableNames[]/
isDeprecated/mcpConfigJson?/skills[]/mcpServerNames[]/isBotSkills/connectorType/variablesJson?/hasConfiguredVariables/
credentialSource/delegatedCredential?/credentialAllowedActions[]/supportsServiceAccount.
Plugin skill: name/description/sourcePath/sourceUrl?/content?/environments[].
**P `GrokBotAgentPlugin|`, `GrokBotAgentPluginSkill|`; M `function RGn(`**.

**VERIFIED masking:** setup chooses variablesJson schema, then catalog fields, then variable-name fallback. Secret flags
come from writeOnly/password format/isSecret or credential/key/passphrase/password/secret/token name components. Secret
string inputs use password type; stored configuration is a fixed bullet placeholder, not its old value. Inputs begin blank
(booleans false), and save clears entered values. hasConfiguredVariables signals presence, not a secret value.
**B `function K(`, `function Y(`, `function re(`, `function pe(`, `fe={`**.
Entered variables, mcpConfigJson and returned configuration containers can hold **secrets**; variablesJson here describes
the input schema, not necessarily stored values. UI masking does not prove every backend response is redacted.

## 6. Automations

**VERIFIED:** `getAgentAutomations({id:string}) → array`; `listAllAutomations() → array`; `createAgentAutomation({id:string,spec}) → array`; `updateAgentAutomation({id:string,automationId:string,spec}) → array`; `deleteAgentAutomation({id:string,automationId:string}) → array`; `setAgentAutomationEnabled({id:string,automationId:string,isEnabled:boolean}) → array`; `runAgentAutomationNow({id:string,automationId:string,sessionId?:string}) → null`. `spec` has `name:string,prompt:string,trigger:object,isEnabled?:boolean`. A group trigger has `type:"group",listeners:object[]` and requires at least two listeners. **C `createAgentAutomation:I().args`, `LK=b({name`, `getAgentWorkflows:{args:"object"`, `createAgentAutomation:{args:"object"`, `one=ln("at least two triggers"`**.

**VERIFIED temporal routes:** getAgentAutomations → ListGrokBotAgentAutomations({agentId:id,timeZone?});
delete → DeleteGrokBotAgentAutomation({agentId:id,automationId,timeZone?});
toggle → SetGrokBotAgentAutomationEnabled({agentId:id,automationId,isEnabled,timeZone?}). Each returns automations[] normalized
into parsed records. Delete clears the cached webhook credential first. Create/update/runNow all stay on gateway: no backend
action cases. All agent IDs here are logical/gateway IDs; L confirms backend IDs fail the list RPCs.
**C `function Hx(`, `function n3(`; M `function F_t(`, `function vpt(`;
P `ListGrokBotAgentAutomationsRequest|`, `DeleteGrokBotAgentAutomationRequest|`, `SetGrokBotAgentAutomationEnabledRequest|`;
L, Ids**.

**VERIFIED account aggregation:** listAllAutomations in the desktop coordinator uses
ListGrokBotAccountAutomations({agentIds,timeZone?}) in batches ≤200 for known temporal IDs. A globally unimplemented batch
route or readIndividually rows invoke per-bot reads. Successful server rows replace gateway rows for that bot; unavailable
reads retain gateway rows. Returned rows are {agentId,automation}. No remembered temporal IDs means gateway only.
Thus L's direct gateway empty getAgentAutomations/listAllAutomations responses do not describe desktop coordinator results;
backend lists contain one or two automations per bot. Sources: **C `listAllAutomations serves the server rows alone`,
`function n3(`; M `function vpt(`; P `ListGrokBotAccountAutomationsRequest|`; L, Automations**.

**VERIFIED complete structural trigger union:** below. Validators do not supply cron semantics, nonblank checks or form defaults.
Sources: **C `LK=b({name`, `FK=Ye(`, `Kte=Ye(`, `one=ln(`**.

| trigger.type | Fields beyond type |
|---|---|
| cron | schedule:string,firesAt?:string,window?:{earlyMinutes:number,lateMinutes:number},timing?:exact\|flexible |
| slack | channel:string,match:{kind:mention} or {kind:keyword,keyword:string} or {kind:message} or {kind:reaction,emoji?:string[],bySelf?:boolean} |
| github | repo:string,events:enum[],pr?:number,userAllowlist?:string[],ciBranch?:string |
| origin | repo:string,events:enum[],pr?:number,userAllowlist?:string[] |
| microsoftTeams | tenantId:string,teamIds:string[],channelIds:string[],messageContains:string,messageContainsIsRegex:boolean,blockUnauthenticatedTeamsUsers:boolean |
| linear | event:{case:issueCreated} or {case:statusChanged,statusIds:string[]} or {case:endOfCycle,cycleIds:string[]}; projectIds:string[],teamIds:string[] |
| sentry | event:{case:enum},projectIds:string[] |
| pagerduty | event:{case:enum},serviceIds:string[] |
| email | inbox:string,from?:string[],requireAuthPass?:boolean |
| webhook | no additional fields |
| group | listeners:non-group-trigger[]; at least two; nested groups excluded |

**VERIFIED event enums:** GitHub pr-opened/pr-pushed/pr-merged/pr-closed/review-requested/review-approved/
review-changes-requested/review-commented/pr-comment/inline-review-comment/review-thread-resolved/review-thread-unresolved/
issue-assigned/ci-passed/ci-failed. Origin accepts that set except pr-closed and issue-assigned.
Sentry issueCreated/issueResolved/issueAssigned/issueArchived/issueUnresolved/issueAny;
PagerDuty incidentTriggered/incidentAcknowledged/incidentResolved/incidentEscalated/incidentAny.
**C `var sK=`, `var iK=`, `var aK=`, `uK=[`**.

**VERIFIED client schedule grammar:** five fields: minute 0–59, hour 0–23, day-of-month 1–31, month 1–12, weekday 0–7
(7 maps to Sunday). Numeric lists, inclusive ranges, wildcard and positive steps; six fields and month/weekday names are not
parsed. Restricted day-of-month/weekday combine with OR. Macros: @hourly/@daily/@midnight/@weekly/@monthly/@yearly/@annually.
Leading CRON_TZ= or TZ= selects a validated timezone; otherwise next-run calculation uses supplied timezone or local calendar
fallback. **R `function l8e(`, `function vj(`, `function yj(`, `function _j(`, `function Cj(`, `function w8e(`, `o8e={`**.

**VERIFIED intervals:** cron-type schedule also accepts @every plus positive duration, optional slash and phase shorter than
interval. Duration parser supports combined/decimal ms/s/m/h/d units; simplified UI recognition is narrower (integer amounts).
There is no separate interval trigger type. Optional minimum-spacing checks do not establish a universal automation
minimum/default. **R `function v8e(`, `function y8e(`, `function S8e(`, `function n5e(`; C `FK=Ye(`**.

**VERIFIED record mapping:** backend rows are {automationId,recordJson,viewerPermissions:{allowedActions[]}}. Main parses
recordJson, checks types of id/name/prompt/schedule/triggerDescription/isEnabled/createdAt/filePath/runs, drops invalid records
and embedded viewerCapabilities, derives canOpen/canEdit/canToggle/canDelete from server permissions, then sorts by nextRunAt
(missing last), then createdAt. Outer automationId does not replace JSON id; webhook key creation uses that outer server ID.
**P `GrokBotAgentAutomation|`; M `function MVn(`, `function NM(`, `function uq(`, `function vpt(`**.

**VERIFIED L JSON fields:** id/name/prompt/isEnabled/createdAt/lastRunAt/nextRunAt/runs[]/provenance/filePath/schedule/
triggerDescription/trigger:{type,schedule}/triggerPresentation:{version,trigger}; cron observed. Allowed actions use
GROK_BOT_AUTOMATION_ACTION_OPEN/EDIT/TOGGLE/DELETE. Main preserves extra JSON fields. UI watches a new manual run ID and
run status after Run now, rather than treating its null reply as completion.
**M `function NM(`; R `function WNn(`; A `i.runs[0]?.status`; L, Automations**.

**INFERRED meaning:** provenance is trust/origin metadata, not run status: template setup distinguishes
automationWriteProvenance=untrusted/template_import. FilePath identifies a backing artifact; adapter treats it as opaque,
not a Windows path to read. **UNKNOWN:** exact backend storage semantics/full provenance enum. Host record producer or source
metadata in read-only automation records would settle these. Supporting context:
**R `automationWriteProvenance:e.setup`, `keep its provenance untrusted`; M `function MVn(`**.

**VERIFIED UI:** row Edit seeds a localized chat request naming the automation. Detail shows prompt, triggers, run history,
enabled toggle, Run now and webhook fields. No structured create/edit form caller was located; resource create/update methods
do not prove a form exists. **R `function C7e(`, `function WNn(`; A `function me(`**.
**UNKNOWN:** separate create/edit form fields/defaults/validation messages and server schedule grammar. Inspect a New/Edit
interaction read-only in this version or the missing form/host implementation; do not borrow defaults from the skill editor.

## 7. Webhooks

**VERIFIED:** `getAutomationWebhookCredential({id:string,automationId:string}) → {url:string,key:string}` on the temporal path; `key` is a secret bearer credential and the URL may be sensitive. The adapter lists automations, matches a webhook record and creates/caches a DashboardService automation webhook API key. `runAutomationWebhook({id:string,automationId:string,context:string}) → {runId:string|null}` posts JSON context with bearer authentication. Both can have side effects, including key creation; do not include the credential call in a read-only capture list. See protocol-temporal section 1. **C `getAutomationWebhookCredential:I().args`; M `function vpt(`, `function OVn(`**.

**VERIFIED UI:** URL is read-only/copyable; key and derived Authorization header use password fields with reveal/copy controls.
Pending/null key uses a placeholder with controls disabled. Renderer accepts null key while waiting and retries retrieval;
the temporal adapter's successful credential path returns a string.
**A `function z(`, `function V(`, `function de(`; R `function WNn(`**.

## 8. Workflows and routines

**VERIFIED:** `getAgentWorkflows({id:string}) → array`; `createAgentWorkflow({id:string,spec}) → array`; `updateAgentWorkflow({id:string,workflowId:string,spec}) → array`; `deleteAgentWorkflow({id:string,workflowId:string}) → array`; `runAgentWorkflowNow({id:string,workflowId:string}) → null`; `importAgentWorkflowText({id:string,markdown:string,name?:string})` and `importAgentWorkflowUrl({id:string,url:string,name?:string})` return an import-result record. The workflow text input is Markdown. `spec` is `{name:string,description:string,body:string,trigger:{schedule:string,isEnabled:boolean}|null,sourceRef?:string|null}`. **C `getAgentWorkflows:I().args`, `MK=b({name`, `getAgentWorkflows:{args:"object"`**.

**VERIFIED:** `ListGrokBotAgentRoutines({agentId:string,timeZone?:string}) → {routines:message[],routinePolicy?:message}`. Routine fields are `automationId,routineId,name,triggerDescription,triggerPresentationJson,schedule:string`, `isEnabled:boolean`, `nextRunAtMs?:int64`, `createdAtMs:int64`, `runAsUserId:int32`, `runAsDisplayName:string`, `runAsIsViewer:boolean`, `recordJson?:string`, `viewerPermissions?:message`. `SetGrokBotAgentRoutineEnabled({agentId:string,automationId:string,isEnabled:boolean,timeZone?:string}) → {routine?:message}`. **P `ListGrokBotAgentRoutinesRequest|`, `GrokBotAgentRoutine|`, `SetGrokBotAgentRoutineEnabledRequest|`**.

**VERIFIED temporal routes:** get/create/update/delete/runAgentWorkflowNow and importAgentWorkflowText/Url all stay on
gateway: no backend workflow action case. Desktop separately combines workflow rows with backend skills (section 5).
**C `function Hx(`, `function n3(`; M `function F_t(`; R `function QNn(`**.

**VERIFIED L rows:** id/name/description/body (Markdown)/filePath/source/sourceRef/pluginId/trigger/scheduleDescription/
lastRunAt/nextRunAt/runs[]/helperScripts[]/createdAt/publishedByCurrentUser. L saw about 140 source=managed rows for a temporal
bot. UI treats managed/template entries as read-only, replaces matching managed IDs with server skills, and exposes
unscheduled skills as referenceable instructions.
**R `function J8(`, `function JNn(`, `function Tvn(`; V `M=i.source===`; L, Workflows**.

**INFERRED distinction:** workflow is the gateway Markdown instruction/skill artifact, optionally scheduled; automation is
prompt plus typed trigger and execution history. UI calls automations routines and projects them into workflow-like views
with source=automation; that does not convert storage/API. Managed rows belong to the managed skill surface; their count
does not establish 140 user-created timers. Supporting sources: **R `function bot(`, `function J8(`; V `M=i.source===`;
C `LK=b({name`, `MK=b({name`**. App routine terminology also differs from groken's separate local routine store.
**UNKNOWN:** producer/ownership of each managed file. Compare read-only getAgentWorkflows source metadata with
ListGrokBotAgentSkills/GetGrokBotAgentPlugins; host producer settles remaining origin. L's ListGrokBotAgentRoutines returned
NotFound, so the declarations above establish neither account support nor equivalence with the working automation list.

**VERIFIED import handling:** reply is {workflows:Workflow[],result}; validation requires workflows[], resource replaces
that bot's list and returns result to caller. **UNKNOWN:** inner result fields/conflict/partial-import semantics; host
implementation or separately authorized import capture (a mutation) would settle them. **R `JQn=`, `function QNn(`**.

## 9. Browser handoff

Format follows protocol-m4b section 11. Rows are **VERIFIED client paths**; ! denotes a **secret/sensitive** URL, code/state
or document capability. Completion is a state transition, not the fact a URL opened.

| Area / URL opened | Completion observation | Bundle citation |
|---|---|---|
| Connector sign-in/re-auth authorizationUrl! | loopback code/state! exchange; token validation or account token presence; mcp-auth-completed/state refresh | M `function tbt(`, `function Sme(`, `async authWatchTokenLanded(` |
| Hosted OAuth callback → loopback /callback; shared grokbot/cursor callback constants | matched pending state, CompleteMcpOAuth; constants do not prove desktop deep-link wait | M `function IZn(`, `function fJ(`, `hFt=new Map`, `function Sme(` |
| Microsoft connector admin-approval help adminConsentUrl! | browser help/error page; retry ordinary sign-in; no separate consent-finished SSE proven | M `function Sme(`, `adminApprovalHelpArm` |
| Team tailnet signInUrl! | DiscoverTeamTailnetSuffix starts with start=true, then start=false every two seconds until kind=found/failed; superseded/unmounted attempt is cancelled | D `async function Ht(`, `team-tailnet-sign-in-poll`; R `function $Le(`; M `function lSt(` |
| Listener integrations used by event triggers: connect URL!; Slack desktop link | SCM callback → completeGithubConnect; integrations.isConnected refresh/poll; Slack isSlackLinked | R `function YBn(`, `function GBn(` |
| MCP app staged frameUrl!/bridgeKey! | document/frame/tool protocol, not external OAuth completion | R `function oVn(` |
| Skill URL import | gateway importAgentWorkflowUrl reply {workflows,result}; no external browser open in this install path | R `function QNn(` |
| Native 1Password plugin's developer-settings app link, service-account docs/blog | informational/manual setup links have no browser-finished acknowledgement; OAuth/credential ceremonies are detailed in protocol-m4b sections 8/11 | N `onepassword://settings/developers`, `service-accounts/get-started/` |

**VERIFIED:** webhook copy/reveal/run, variable saves, workflow CRUD and automation toggle/delete complete through
commands/state, not a browser-finished callback. **A `function V(`; B `function pe(`; R `function QNn(`, `function WNn(`**.
**UNKNOWN:** informational external links/additional redirects inside provider-hosted pages are not exhaustively established
by these callers; read-only inspection of the specific UI navigation/hosted page settles extra handoffs.

## 10. Events

**VERIFIED mapping:** gateway aliases automations/agent-automations-changed/workflows/mcp-servers/mcp-auth map to the names
below. Coordinator also synthesizes automation/workflow refreshes after server notifications; that does not prove raw gateway
SSE carries temporal backend changes. **C `var Nre=`, `function Gz(`, `function Vz(`, `let F=Gz(T.channel)`**.

| Desktop/coordinator name (gateway alias) | Payload / behavior | Citation |
|---|---|---|
| agents-automation (automations) | {agentId,automations:Record[]} full replacement; section 6 records | C `function Vz(`; R `ingestAutomationsEvent:` |
| agents-automations-changed (agent-automations-changed) | {agentId}; invalidation/refetch | C `function Vz(`; R `St.noteAutomationsChanged` |
| agents-workflow (workflows) | {agentId,workflows:Workflow[]} full replacement | C `function Vz(`; R `ingestSkillsEvent:` |
| mcp-servers-updated (mcp-servers) | {servers:display-summary[]}; desktop IPC also emits it | C `var Nre=`; M `setServersUpdatedEmitter:`; R `ingestServersUpdated:` |
| mcp-auth-completed (mcp-auth) | section 2 completion; success may omit outcome, cancellation has failureDetail? | C `lne=b({serverId`, `var Nre=`; M `async finishPendingAuthWatch(`, `notifyWatchCancelled(t,n){` |
| agents-bot-skills (bot-skills) | {agentId}; botSkills/botPlugins changes refresh plugin/skill resources | C `function Vz(`; R `yt.refresh(e.agentId)` |

**VERIFIED roster:** server-roster-changed is {kind:agent,agentId}, {kind:resync}, or
{kind:user-settings,explicit:boolean,fields:string[]}. Known fields:
autoReview/hasSeenOnboarding/jobRole/libraryPins/mainAgent/mcpServers/pinnedAgents/sidebarSections/timeZone.
Unknown/empty backend field sets become all known fields with explicit=false; recognized fields give explicit=true.
Renderer adopts server tool permissions on mcpServers or autoReview. Payload contains invalidation names, not tokens.
**C `function s0(`, `O6=`, `pb=`; R `server-roster-changed`**.

**VERIFIED:** manual-run resource waits for changed runs/new manual run ID and re-reads after command; this inspected event
map has no dedicated automation-start/finish channel. Connector completion also exists as desktop IPC independently of SSE.
**INFERRED:** subscribe before actions and refetch on invalidation; raw gateway SSE alone cannot cover every temporal/account
change. **R `function WNn(`; C `var Nre=`, `function Vz(`; M `setAuthCompletedEmitter:`**.

## Read-only capture candidates

Gateway: getMcpCatalog/getMcpPluginLogo/getMcpState/listMcpServerTools/skillsCatalog/getPluginSyncStatus/
getAgentAutomations/listAllAutomations/getAgentWorkflows. Backend: GetGrokBotUserMcpSettings/
GetGrokBotConnectorSharedSpaceAllowlist/GetGrokBotAgentPlugins/ListGrokBotAgentSkills/ListGrokBotAgentAutomations/
ListGrokBotAccountAutomations/ListGrokBotAgentRoutines/GetAvailableMcpServers/ValidateMcpOAuthTokens, and
CheckHttpMcpStatus with statusOnly=true,userInitiated=false. ReadGrokBotMcpAppDocument exposes private HTML.
**VERIFIED request intent:** **C corresponding validators; M `function Qct(`, `function vpt(`, `function AZn(`;
P corresponding Request descriptors**. Actual authorization/availability is account-dependent (L includes NotFound cases).
Exclude refreshMcp/syncPluginSkills, OAuth starts/completion, imports, tool calls and webhook credential retrieval:
they can mutate state or issue credentials. DiscoverTeamTailnetSuffix with start=true is also a sign-in start, not a passive
capture. Remaining **UNKNOWN** items and settling evidence are identified above.
