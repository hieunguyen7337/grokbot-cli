# M4a protocol research: desktop 0.77.0

Offline bundle inspection; no service or private configuration was accessed. This is a partial research result: UNKNOWN means the cited declaration or inspected caller did not establish the requested detail, not that a feature is absent. VERIFIED means client code or a declaration establishes the stated fact; it does not prove server behavior. `?` denotes optional, `[]` repeated; protobuf int64 values are represented as decimal strings in protobuf JSON. Records whose fields are not listed have **UNKNOWN** contents. Secrets are identified explicitly. See protocol-m2 section 10 and protocol-temporal section 1 for the harness router and backend envelopes; protocol-m3 section 10 describes its routing caveats.

Bundle citation keys: **C** = `dist/node-agent-coordinator/main.cjs`; **M** = `dist/electron-main/main-app.cjs`; **P** = `dist/electron-main/proto.cjs`. Each citation includes a searchable string. These paths are relative to the bundle root.

## 1. Connector catalog and state

**VERIFIED:** `getMcpCatalog()` returns an array; `getMcpPluginLogo({url:string})` returns a record or null; `getMcpState()` returns a record; `listMcpServerTools({serverId:string})` returns an array. `refreshMcp({completion?:{serverId:string,serverName:string,accountKey:string,serverIdentifier?:string,serverUrl?:string,requestingAgentId:string|null,outcome?:"connected"|"cancelled",failureDetail?:string}})` accepts an optional completion record. Its reply shape remains UNKNOWN. **C `getMcpCatalog:I().noArgs`, `getMcpCatalog:{args:"none"`, `lne=b({serverId`**.

**VERIFIED:** `GetGrokBotUserMcpSettings({}) → {settings?:GrokBotUserMcpSettings}`. Settings contain `servers: {serverId:string,customInstructions?:string,disabledTools:string[]}[]`, `customInstructionsByName:map<string,string>`, `userTimeZone?:string`, `userTimeZoneOverride?:string`, `updatedAtMs:int64`, and `autoReviewInstructions?:message`. **P `GrokBotUserMcpSettings|`, `GrokBotUserMcpServerSettings|`, `GetGrokBotUserMcpSettingsResponse|`**.

**UNKNOWN:** catalog item fields, auth and install state, logo record fields, the authoritative per-bot accounts/tools source, and exact temporal routing for these catalog/state reads. Inspect the catalog producer and renderer or compare authorized read-only catalog, state and plugin responses. A roster field should not be assumed without that evidence.

## 2. Connector authentication

**VERIFIED:** `authenticateMcpServer` accepts `serverId:string`, optional `accountKey:string`, `trigger:"connector_card"`, `entryPoint:string` from the validator's listed UI origins, `forceReauth:boolean`, `requestingAgentId:string`, `oauthRedirectUri:string`, `dataCenter:string`, and `shareWithBot:{agentId:string,pluginId:string,acknowledgedWarningVersion:number}`. Its reply is a record. For a temporal bot the desktop adapter uses DashboardService `CheckHttpMcpStatus`, sometimes `GetAvailableMcpServers`, and returns `started` with `authorizationUrl` and `serverName`, or `already-authenticated`, `not-configured`, `unreachable`, or `not-supported`; see protocol-temporal section 1 for exact selection and request mapping. **C `ga=b({serverId`, `authenticateMcpServer:{args:"object"`; M `function u_t(`, `function BKn(`**.

**VERIFIED:** `completeMcpOAuth({code:string,state:string}) → null` maps to DashboardService `CompleteMcpOAuth({authorizationCode:code,stateId:state})` for the temporal path. `code` and `state` are sensitive OAuth credentials; do not log them. **C `completeMcpOAuth:I().args`; M `function u_t(`**.

**INFERRED:** a `started` authorization URL needs a browser for the user to authenticate. **UNKNOWN:** the exact desktop callback/deep-link, event or poll and failure completion flow; inspect its renderer and protocol handler before implementing a wait helper.

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

**UNKNOWN:** permission enum values, server message fields, whether each gateway mutation has a backend twin, and the temporal caller for each. Protobuf declarations alone do not establish those mappings; inspect the callers and capture authorized reads.

## 4. MCP apps

**VERIFIED:** `readMcpAppResource` accepts `serverIdentifier:string,resourceUri:string,agentId?:string,entryId?:string,sessionId?:string,documentSha256?:string`. Temporal routing calls `ReadGrokBotMcpAppDocument` with `agentId,sessionId,entryId`; normalized reply is `{document:{resourceUri:string,html:string,meta?:object}}`. `callMcpAppTool` accepts `serverIdentifier:string,toolName:string,argumentsJson:string,userActivated:boolean,agentId?:string,entryId?:string,sessionId?:string`; temporal routing calls `CallGrokBotMcpAppTool`, yielding `resultJson` or an error, optional `code` and `usedActivation`. See protocol-temporal section 1 for validation and failure details. **C `ma=b({serverIdentifier`, `fa=b({serverIdentifier`; M `function M_t(`, `function oYn(`**.

**INFERRED:** the returned HTML is intended for a rendered interactive document. A terminal can show the resource URI and a text representation, and offer a handoff; it must not silently execute the HTML. **UNKNOWN:** the precise desktop embedding and a safe equivalent for app interactions require renderer inspection.

## 5. Plugins and skills

**VERIFIED:** `skillsCatalog()` and `syncPluginSkills()` return arrays; `getPluginSyncStatus()` returns a record. Item fields are UNKNOWN. **C `skillsCatalog:I().noArgs`, `skillsCatalog:{args:"none"`**.

**VERIFIED protobuf declarations:** `GetGrokBotAgentPlugins({agentId:string,includeMcpConfig:boolean}) → {marketplace?:message,plugins:message[],serviceAccountsEnabled?:boolean,delegatedAuthAvailable?:boolean,shareablePluginIds:int64[]}`. `SetGrokBotAgentPlugins({agentId:string,plugins:message[]}) → {marketplace?:message,plugins:message[]}`; `SetGrokBotAgentPluginVariables({agentId:string,pluginId:int64,variables?:message,mergeWithStored:boolean})` returns the same response shape. Treat variable values as potentially secret. **P `GetGrokBotAgentPluginsRequest|`, `GetGrokBotAgentPluginsResponse|`, `SetGrokBotAgentPluginsRequest|`, `SetGrokBotAgentPluginVariablesRequest|`**.

**VERIFIED:** `ListGrokBotAgentSkills({agentId:string}) → {skills:{id:string,name:string,description:string,body:string,source:string}[]}`. `AddGrokBotAgentSkill({agentId:string,name?:string,description?:string,content:string})` and `UpdateGrokBotAgentSkill({agentId:string,name:string,description?:string,content:string})` return `{marketplace?:message,plugins:message[],skill?:message}`. `RemoveGrokBotAgentSkill({agentId:string,name:string})` returns `{marketplace?:message,plugins:message[]}`. **P `GrokBotAgentSkill|`, `AddGrokBotAgentSkillRequest|`, `UpdateGrokBotAgentSkillRequest|`, `RemoveGrokBotAgentSkillRequest|`**.

**VERIFIED:** `AttachGrokBotAgentDelegatedCredential({agentId:string,pluginId:int64,accountKey?:string,acknowledgedWarningVersion:int32})` and `RemoveGrokBotAgentDelegatedCredential({agentId:string,pluginId:int64})` return `{marketplace?:message,plugins:message[]}`. These calls manage credential access; account identifiers and returned plugin configuration may be sensitive. **P `AttachGrokBotAgentDelegatedCredentialRequest|`, `RemoveGrokBotAgentDelegatedCredentialRequest|`**.

**UNKNOWN:** catalog item schema, nested plugin/variable messages, whether and how values are masked in the UI, the exact conceptual plugin/skill distinction, and which desktop callers are used for temporal bots. Inspect bot-manage renderer and its main-process adapters; do not assume the declaration implies invocation.

## 6. Automations

**VERIFIED:** `getAgentAutomations({id:string}) → array`; `listAllAutomations() → array`; `createAgentAutomation({id:string,spec}) → array`; `updateAgentAutomation({id:string,automationId:string,spec}) → array`; `deleteAgentAutomation({id:string,automationId:string}) → array`; `setAgentAutomationEnabled({id:string,automationId:string,isEnabled:boolean}) → array`; `runAgentAutomationNow({id:string,automationId:string,sessionId?:string}) → null`. `spec` has `name:string,prompt:string,trigger:object,isEnabled?:boolean`. A group trigger has `type:"group",listeners:object[]` and requires at least two listeners. **C `createAgentAutomation:I().args`, `LK=b({name`, `getAgentWorkflows:{args:"object"`, `createAgentAutomation:{args:"object"`, `one=ln("at least two triggers"`**.

**VERIFIED temporal routes:** `getAgentAutomations` uses `ListGrokBotAgentAutomations({agentId,timeZone?})`; delete uses `DeleteGrokBotAgentAutomation({agentId,automationId,timeZone?})`; toggle uses `SetGrokBotAgentAutomationEnabled({agentId,automationId,isEnabled,timeZone?})`; each RPC returns `{automations:message[]}`, normalized into parsed records. Account-wide adapter `listAccountAutomations` uses `ListGrokBotAccountAutomations({agentIds:string[],timeZone?:string}) → {agents:message[]}`. This is a distinct command from `listAllAutomations`; their relationship is UNKNOWN. See protocol-temporal section 1 for normalization and account-level flags. **M `function F_t(`, `function vpt(`; P `ListGrokBotAgentAutomationsRequest|`, `ListGrokBotAccountAutomationsRequest|`, `DeleteGrokBotAgentAutomationRequest|`, `SetGrokBotAgentAutomationEnabledRequest|`**.

**UNKNOWN:** temporal routes for create/update/run, complete trigger alternatives, cron/interval grammar and time zone, record fields including last/next run, and UI form validation. Inspect `FK` and its member validators and automation form; compare read-only response records. Do not assume event triggers or create mutations route through a particular backend RPC.

## 7. Webhooks

**VERIFIED:** `getAutomationWebhookCredential({id:string,automationId:string}) → {url:string,key:string}` on the temporal path; `key` is a secret bearer credential and the URL may be sensitive. The adapter lists automations, matches a webhook record and creates/caches a DashboardService automation webhook API key. `runAutomationWebhook({id:string,automationId:string,context:string}) → {runId:string|null}` posts JSON context with bearer authentication. Both can have side effects, including key creation; do not include the credential call in a read-only capture list. See protocol-temporal section 1. **C `getAutomationWebhookCredential:I().args`; M `function vpt(`, `function OVn(`**.

**UNKNOWN:** exact UI masking/reveal behavior. Inspect the webhook settings component without displaying a real key.

## 8. Workflows and routines

**VERIFIED:** `getAgentWorkflows({id:string}) → array`; `createAgentWorkflow({id:string,spec}) → array`; `updateAgentWorkflow({id:string,workflowId:string,spec}) → array`; `deleteAgentWorkflow({id:string,workflowId:string}) → array`; `runAgentWorkflowNow({id:string,workflowId:string}) → null`; `importAgentWorkflowText({id:string,markdown:string,name?:string})` and `importAgentWorkflowUrl({id:string,url:string,name?:string})` return an import-result record. The workflow text input is Markdown. `spec` is `{name:string,description:string,body:string,trigger:{schedule:string,isEnabled:boolean}|null,sourceRef?:string|null}`. **C `getAgentWorkflows:I().args`, `MK=b({name`, `getAgentWorkflows:{args:"object"`**.

**VERIFIED:** `ListGrokBotAgentRoutines({agentId:string,timeZone?:string}) → {routines:message[],routinePolicy?:message}`. Routine fields are `automationId,routineId,name,triggerDescription,triggerPresentationJson,schedule:string`, `isEnabled:boolean`, `nextRunAtMs?:int64`, `createdAtMs:int64`, `runAsUserId:int32`, `runAsDisplayName:string`, `runAsIsViewer:boolean`, `recordJson?:string`, `viewerPermissions?:message`. `SetGrokBotAgentRoutineEnabled({agentId:string,automationId:string,isEnabled:boolean,timeZone?:string}) → {routine?:message}`. **P `ListGrokBotAgentRoutinesRequest|`, `GrokBotAgentRoutine|`, `SetGrokBotAgentRoutineEnabledRequest|`**.

**UNKNOWN:** full persisted workflow and import-result fields, precise distinction between automation and routine, and temporal workflow routing. The distinct declarations are insufficient to establish semantic equivalence; inspect producer and callers.

## 9. Browser handoff

**VERIFIED:** temporal connector authentication can return an `authorizationUrl` (section 2). OAuth completion accepts `code` and `state`, and refresh accepts a completion record (sections 1–2). **UNKNOWN:** whether this is the complete list of external handoffs in these areas, the exact event/poll that terminates each wait, and how cancellation and failure are observed. Trace renderer `openExternal` call sites and the OAuth callback before treating a shared wait helper as specified.

## 10. Events

**VERIFIED:** the coordinator posts event names `agents-automation`, `agents-automations-changed`, and `agents-workflow` through its event emitter. **C `emitAutomations:T=>Ce.postEvent`, `emitSkills:T=>Ce.postEvent`**.

**UNKNOWN:** their payload fields, connector change events, automation start/finish events, and whether the event stream exposes all state changes. Trace the emitters and event schema or capture an authorized test event. Do not substitute guessed event names or polling behavior.

## Read-only capture candidates

Declared non-mutating gateway reads: `getMcpCatalog`, `getMcpPluginLogo`, `getMcpState`, `listMcpServerTools`, `skillsCatalog`, `getPluginSyncStatus`, `getAgentAutomations`, `listAllAutomations`, `getAgentWorkflows`. Declared non-mutating RPC reads: `GetGrokBotUserMcpSettings`, `GetGrokBotConnectorSharedSpaceAllowlist`, `GetGrokBotAgentPlugins`, `ListGrokBotAgentSkills`, `ListGrokBotAgentAutomations`, `ListGrokBotAccountAutomations`, `ListGrokBotAgentRoutines`, and `ReadGrokBotMcpAppDocument`. Their actual availability and authorization are UNKNOWN. MCP document HTML and plugin configuration may contain sensitive data. `refreshMcp`, `syncPluginSkills`, MCP tool calls, OAuth and webhook credential retrieval are excluded because they can change state or issue credentials.
