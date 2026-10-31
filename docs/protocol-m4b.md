# M4b channels, inboxes, vault and computer: desktop 0.77.0

Offline research of `_bundle-077`; no live service, private configuration or credential file was accessed.
VERIFIED means client code/schema, not deployed server behaviour; INFERRED means interpretation; UNKNOWN means unresolved.
Only this file was written. Existing transport framing: protocol-tui sections 1 and 9; temporal routing background:
protocol-m2 section 10, protocol-m3 section 10 and protocol-temporal section 1. Existing credential/payment cards:
protocol-m2 section 8. `docs/tui/routing.md` and `gbot/service/routing.py` implement a narrower route set than the desktop.

Bundle citation key (paths relative to bundle root):

- C = `dist/node-agent-coordinator/main.cjs`.
- M = `dist/electron-main/main-app.cjs`; P = `dist/electron-main/proto.cjs`.
- R = `dist/renderer/assets/index.eager-app-BtIHj2If.js`.
- S = C, search `async function are()`: the adjacent `wz` value decodes with base64/raw DEFLATE to the gateway contract.
  An S citation gives the decoded unique key, e.g. `methods.ensureForeverBox` or `$defs.SandForeverBoxStatus`.
- V = `dist/renderer/assets/chunk-view-Cuc26j-t.js`.
- N = `dist/renderer/assets/chunk-native-plugin-detail-D89mZ9ek.js`.

Notation: `s` string, `b` boolean, `n` number, `i64` protobuf int64 (decimal string in protobuf JSON, bigint in JS),
`E(Name)` protobuf enum, `[]` array, `?` optional, `{}` empty message. Names below use protobuf JSON camelCase.
`!` marks sensitive material, including credential identifiers/records, tokens, phone numbers and email addresses;
the mark applies to all occurrences and nested copies of that field/type. `URL!` is a string that can carry authorization
state or credentials. Treat arbitrary notes, values maps, message bodies and credential metadata as sensitive too.
Protobuf defaults/empty arrays may be omitted in JSON; a declared message field can be absent. RPC tables describe raw
protobuf replies; desktop transformations are separate. Every RPC table row is VERIFIED by P searches
`<RPC>Request|` and `<RPC>Response|`, except the explicitly named shared response messages in section 8.
Unless stated otherwise, named RPCs use backend `aiserver.v1.GrokBotService`, directly from the desktop, including temporal bots.

## 1. Slack

**VERIFIED — route and scope:** direct backend calls, not gateway channel commands. Installation targets logical `agentId`
(per bot); workspace manager authorization can be reused from the account's workspaces. UI supports the flow for temporal
harness and represents creator-connection use separately. Sources: M `function cut(`; R `function PFn(`; P request descriptors below.

| RPC | Arguments | Reply |
|---|---|---|
| GetGrokBotSlackInstallState | agentId:s | status:E(GrokBotSlackInstallStatus), slackTeamId?/workspaceName?:s, workspaces:Workspace[], needsManifestUpdate/pendingReinstallApproval/appUnreachable/removedInSlack:b, oauthAuthorizeUrl?:URL!, approvalRequestFiled?:b, cursorApprovalRequired?:{slackTeamId:s}, connectFailure?:{kind:E(GrokBotSlackConnectFailureKind),slackTeamId?:s}, approvalDenied?:{slackTeamId:s,workspaceName?:s,deniedAtMs:i64}, installDeferred?:{retryAfterSeconds?:n,retrying:b}, approvalRequestFiledAtMs?:i64 |
| StartGrokBotSlackConnect | agentId:s, returnToMobileApp:b | url:URL!, outcome:E(GrokBotSlackConnectOutcome) |
| InstallGrokBotSlackApp | agentId:s, slackTeamId?:s, replaceExistingApp/approvalRequestResubmitted:b | outcome:E(GrokBotSlackInstallOutcome), slackTeamId?/workspaceName?/slackError?/previousWorkspaceName?:s, oauthAuthorizeUrl?:URL!, workspaces:Workspace[], retryAfterSeconds?:n, approvalRequestFiled?/appRemoved?/previousAppForgotten?/retrying?:b, approvalRequestFiledAtMs?:i64 |
| ReinstallGrokBotSlackApp | agentId:s, automatic:b | outcome:E(GrokBotSlackReinstallOutcome), slackTeamId?/workspaceName?/slackError?:s, retryAfterSeconds?:n, oauthAuthorizeUrl?:URL!, approvalRequestFiled?:b |
| UninstallGrokBotSlackApp | agentId:s, forgetIfUnreachable:b | outcome:E(GrokBotSlackUninstallOutcome), slackTeamId?/slackError?/workspaceName?:s, retryAfterSeconds?:n, forgotten?:b |

**VERIFIED — nested/enums:** Workspace={slackTeamId:s,slackTeamName?:s,managerAuthUpdatedAtMs:i64}, P `GrokBotSlackWorkspace|`.
Status: UNSPECIFIED/NOT_CONNECTED/APP_CREATED/CONNECTED/UNSUPPORTED_HARNESS. Start: UNSPECIFIED/STARTED/UNSUPPORTED_HARNESS/NOT_PUBLISHED.
Install: UNSPECIFIED/INSTALLED/PENDING_ADMIN_APPROVAL/NOT_CONNECTED/WORKSPACE_REQUIRED/MANAGER_REAUTH_REQUIRED/INSUFFICIENT_SCOPES/
INSTALL_CONFLICT/RATELIMITED/SLACK_REJECTED/UNSUPPORTED_HARNESS/NOT_PUBLISHED/WORKSPACE_NOT_ALLOWED.
Reinstall: UNSPECIFIED/UPDATED/UP_TO_DATE/RECREATE_REQUIRED/PENDING_ADMIN_APPROVAL/NOT_CONNECTED/MANAGER_REAUTH_REQUIRED/
INSUFFICIENT_SCOPES/RATELIMITED/SLACK_REJECTED/UNSUPPORTED_HARNESS/THROTTLED.
Uninstall: UNSPECIFIED/REMOVED/NOT_CONNECTED/MANAGER_REAUTH_REQUIRED/RATELIMITED/SLACK_REJECTED/UNSUPPORTED_HARNESS.
Connect failure: UNSPECIFIED/CANCELLED/ORG_INSTALL/WRONG_CURSOR_ACCOUNT/INCOMPLETE. P searches are the enum names above.

**VERIFIED — browser/completion:** the app opens Start's returned url and install/reinstall consent/approval URLs;
the controller exposes openConsentUrl/openApprovalUrl/checkApproval and rereads GetGrokBotSlackInstallState.
State, workspaces, approval flags and manager-auth timestamp distinguish connection, approval and installation; no dedicated
Slack `/events` channel is declared. Sources: R `function PFn(`, `grok-bot-slack-connect-poll`; M `function cut(`;
`dist/renderer/assets/chunk-grok-bot-slack-dialog-live-DjH3_STT.js` search `openConsentUrl`.
**UNKNOWN:** actual returned hosts, tenant policy and server-side installation transaction require server source or authorized captures.

## 2. Microsoft Teams

**VERIFIED — separate concepts:** per-bot installation provisions/publishes a Teams app and installs it in personal/team scopes;
account linking associates the signed-in human with tenant/AAD identity (no agentId). Manager consent for provisioning is
also distinct from installing into a team. Disconnect returns other bots still installed; it is not equivalent to uninstall.
Sources: M `GetGrokBotTeamsInstallState`, `function Vht(`; R `function jIn(`; P descriptors below.

| RPC | Arguments | Reply |
|---|---|---|
| GetGrokBotTeamsInstallState | agentId:s, consentNonce?:s! | state:E(GrokBotTeamsInstallState), tenantId?/tenantDisplayName?/catalogAppId?/rejectionNote?/failureReason?:s, managerIsAdmin:b, installedTeams:InstalledTeam[], approvalRequestFiledAtMs?:i64, packageDownloadUrl?:URL!, teamAdminGrant?:{grantedByDisplayName:s,grantedAtMs:i64,tenantId:s}, tenants:Tenant[], consentResult:E(GrokBotTeamsConsentResult), terminal?:b, pollAfterMs?:n, connectedAccount?:{tenantId:s,username?:s!,adminConsent:b}, botStatus?:BotStatus, autoTeamInstall?/definitionUpdateNeeded?/definitionUpdateInReview?/definitionUpdateProfileChanged?:b |
| StartGrokBotTeamsConnect | agentId:s, requestAdminScopes/grantScopeTeam/forceAccountSelection:b | consentUrl:URL!, nonce:s!, adminConsentUrl:URL! |
| InstallGrokBotTeamsApp | agentId:s, tenantId?:s, teamIds:s[], installPersonal:b, consentNonce?:s! | state:E(GrokBotTeamsInstallState), failureReason?:s, tenants:Tenant[] |
| ReinstallGrokBotTeamsApp | agentId:s, tenantId?:s, consentNonce?:s! | state:E(GrokBotTeamsInstallState), failureReason?:s, tenants:Tenant[] |
| UninstallGrokBotTeamsApp | agentId:s | state:E(GrokBotTeamsInstallState), catalogRemovalPendingAdmin:b |
| ListGrokBotTeamsJoinedTeams | agentId:s, tenantId?:s | teams:{teamId:s,displayName:s}[], tenants:Tenant[] |
| AddGrokBotTeamsAppToTeam | agentId/teamId:s, teamIds:s[], installPersonal:b, consentNonce?:s! | team?:InstalledTeam, failureReason?:s, teams:InstalledTeam[], installedPersonal:b |
| DisconnectGrokBotTeamsAccount | agentId/tenantId:s | revoked:b, state:E(GrokBotTeamsInstallState), stillInstalledAgentIds:s[] |
| GetMicrosoftTeamsAccountLinkStatus | {} | links:{tenantId:s,aadObjectId:s,linkedAtMs:i64,teamsUserId?:s}[] |
| StartMicrosoftTeamsAccountLink | tenantHint?:s | authorizationUrl:URL! |
| UnlinkMicrosoftTeamsAccount | tenantId:s | unlinked:b |

**VERIFIED — nested:** Tenant={tenantId:s,tenantDisplayName?:s,adminConsent:b,managerAuthUpdatedAtMs:i64};
InstalledTeam={teamId:s,displayName:s,rscGranted:b,installedAtMs:i64}; BotStatus={connected:b,
reason:E(GrokBotTeamsBotStatusReason),adminConsentUrl?:URL!,teamsAppUrl?:URL!,suggestAddToTeam?:b}.
P `GrokBotTeamsTenant|`, `GrokBotTeamsInstalledTeam|`, `GrokBotTeamsBotStatus|`, `MicrosoftTeamsAccountLink|`.
State enum: UNSPECIFIED/NOT_CONNECTED/CONNECTED/APP_CREATED/PENDING_ADMIN_APPROVAL/INSTALLED/UPDATE_PENDING/REMOVED_IN_TEAMS/
REMOVED/UNSUPPORTED_HARNESS/NOT_PUBLISHED/UNAVAILABLE/PROVISIONING. Consent: UNSPECIFIED/CONSENT_REQUIRED/ACCESS_DENIED/OTHER/GRANT_CONFLICT.
BotStatusReason: UNSPECIFIED/SETTING_UP/ADMIN_APPROVAL/ADMIN_CONSENT/TEAM_OWNER/ADMIN_POLICY/REJECTED/REMOVED/NOT_SET_UP.
P searches: `GrokBotTeamsInstallState`, `GrokBotTeamsConsentResult`, `GrokBotTeamsBotStatusReason`.

**VERIFIED — desktop differences/completion:** UI add-to-team forwards one teamId; reinstall omits tenantId; account-link IPC
also requires accountSlot to pin the signed-in account, but that is not an RPC field. The app opens consentUrl, polls
GetGrokBotTeamsInstallState with consentNonce, checks consentResult/connectedAccount and install state; terminal/pollAfterMs
describe provisioning progress. Human linking opens authorizationUrl and polls link status for a new tuple
(tenantId,aadObjectId,linkedAtMs), with a two-minute observation window; focus also refreshes. No gateway Teams completion event.
Sources: M `function Qht(`, `function Vht(`; R `consentPollPolicy.start`, `microsoft-teams-account-link-poll`, `function jIn(`.
**UNKNOWN:** server/admin approval timing and exact policy limits need server implementation or captures.

## 3. Messaging link (SMS) and native Messages grants

| RPC | Arguments | Reply |
|---|---|---|
| GetGrokBotMessagingLinkStatus | {} | lineNumber?:s!, pendingCode?:LinkCode! |
| IssueGrokBotMessagingLinkCode | {} | LinkCode! |
| ListGrokBotMessagingLinkedPhones | {} | phones:{handleId:s,address:s!,linkedAtMs:i64,lastSeenAtMs:i64}[] |
| UnlinkGrokBotMessagingPhone | handleId:s | {} |

**VERIFIED:** LinkCode!={code:s!,expiresAtMs:i64,lineNumber:s!,linkMessage:s!,smsUri:URL!,arrivedAsSms:b}.
Account-level backend operations: no bot ID. The UI provides copyable linkMessage and a QR containing smsUri for the user
to send from a phone. It refreshes link status/phones and recognizes a newly linked phone within expiresAtMs.
The address is copied unchanged by main and rendered unchanged by V; there is no client mask. A server may still redact it.
Sources: P `IssueGrokBotMessagingLinkCodeResponse|`, `GrokBotMessagingLinkedPhone|`; M `function mut(`;
R `requestLinkCode:async`, `linkedAtMs<=e.expiresAtMs`; V `linkMessage`, `value:r.smsUri`, `text:n.address`.
**UNKNOWN:** fixed code lifetime and authoritative code/message syntax; expiresAtMs is authoritative, but issue time/TTL
are not declared. Server source or an authorized issuance capture with timestamp would settle this (issuance is a mutation).

**VERIFIED:** gateway resolveMessagesGrants({requestId:s}) returns null. It acknowledges the native permission helper,
including closing an unresolved helper; it does not link an SMS phone or itself grant OS access. Event is
messages-grants={requestId:s,grants:(automation|contacts|fullDiskAccess)[]}. Temporal routing has no corresponding backend
adapter case. Sources: S `methods.resolveMessagesGrants`, `$defs.SandMessagesGrantsRequest`; R `e.source.resolveMessagesGrants({requestId:t})`.
OS/helper details are protocol-m2 section 8. **INFERRED:** retain handoff because the OS permission step requires the app.

## 4. GitHub and listeners

**VERIFIED — gateway for temporal too:** these account-level source calls have no temporal backend-action twin in C's
adapter switch. A listener is an external event source for automation triggers; it is distinct from installing a Slack bot app.
The contract includes SCM, Slack and origin listener types. Sources: C `function HK(`; S `$defs.SandGithubListener`,
`$defs.SandSlackListener`, `$defs.SandOriginListener`; R `function YBn(`.

| Command | Arguments | Reply (VERIFIED, S methods and named definitions) |
|---|---|---|
| getListenerIntegrations | {} | {integrations:Integration[]} ($defs.SandListenerIntegrationsView) |
| getListenerConnectUrl | platform:s, forceOauth?:b or null, oauthRedirectUri?:s | {url:URL!,state?:s!} ($defs.SandListenerConnectLink) |
| completeGithubConnect | state:s!, code?:s!, installationId?/setupAction?/error?:s | {outcome:connected\|failed\|pending_approval\|stale} ($defs.SandGithubConnectCompletion) |

**VERIFIED:** Integration={platform:azure-devops|bitbucket|github|gitlab|origin|slack,isConnected:b,neededByCount:n,
state:connecting|error|idle|listening,detail?:s,grantedRepos?:s[],scopeIssues?:{kind:bot-not-in-channel|not-found,scope:s}[]}.
Sources: S `$defs.SandListenerIntegration`, `$defs.TriggerScopeIssue`.
The app opens the returned url; Slack's account listener instead obtains desktop getSlackLinkUrl and checks isSlackLinked.
SCM browser callbacks carry state/code!/installationId/setupAction/error through `/v1/github-connect-callback` (and analogous
GitLab/Bitbucket/Azure routes) to completeGithubConnect. UI checks outcome and polls integrations every five seconds while
watched, comparing isConnected; hidden views can skip ticks. Sources: R `function YBn(`, `function GBn(`, `github-connect-callback`.
**UNKNOWN:** internal gateway-to-provider/backend implementation is not supplied; no direct RPC mapping is established.

## 5. Email inboxes

| RPC | Arguments | Reply |
|---|---|---|
| ListGrokBotEmailInboxes | showsAssigned:b | {inboxes:Inbox![]} |
| CreateGrokBotEmailInbox | username:s!, displayName:s | {inbox?:Inbox!} |

**VERIFIED:** Inbox!={email:s!,domain:s,createdAtMs:i64,assigned:b}; P `GrokBotEmailInbox|`.
Backend account collection, no agent ID; desktop list sets showsAssigned=true and maps int64 to number. UI trims/lowercases
username, previews username@domain, lists assigned addresses and offers activation/claim; create sends displayName empty.
Sources: M `function Pct(`; N `function Te(`, `function Ae(`, `function Me(`, `displayName:`.
**VERIFIED client defaults/limits:** production address preview uses mail.grokbot.com, nonproduction dev.grokbot.com.
The creation affordance permits claimed count below 1, or below 10 with grok_bot_agent_mail_multiple_inboxes enabled.
These are client limits, not a verified server guarantee. Sources: R `SSe=`, `function ESe(`; N `function Pe(`.
**INFERRED:** inbox allocation is account-level and later bot use/assignment is a separate concern; absence of agentId alone
does not prove all server ownership rules. **UNKNOWN:** authoritative domain, allowed username grammar, server maximum inbox count and
server uniqueness/retention policy. The client consumes domain and server errors; server source or read-only list plus
policy documentation would settle these. Do not infer a numeric limit from the array.

**VERIFIED schema / UNKNOWN desktop thread UI:** P declares ListGrokBotEmailThreads({inboxEmail?:s!,unreadOnly?:b,
afterMs?:i64,limit:n,pageToken?:s!})→{threads:ThreadSummary![],nextPageToken?:s!}; summaries include threadId/subject:s!,
messageCount/unreadCount:n,lastMessageAtMs:i64,participants:{name:s,email:s!}[],matchingMessages with messageId/from/
occurredAtMs/direction/snippet?/unread. P `ListGrokBotEmailThreadsRequest|`, `GrokBotEmailThreadSummary|`, `GrokBotEmailMatchingMessage|`.
ReadGrokBotEmailThread, SearchGrokBotEmailThreads and ReadGrokBotEmailAttachment also exist in P, but no desktop invocation
was located in M/R; parity marks them declined. The observed inbox UI is address management, not proof of a thread browser.
Actual thread browsing and its call path require a missing view/call site or authorized app trace. Existing email drafts
are conversation cards (protocol-m2 section 8), not this inbox-list reply. ReadGrokBotEmailThread returns
markedReadMessageIds:s[]: it must not be assumed side-effect-free (P `ReadGrokBotEmailThreadResponse|`).

## 6. Secrets

| Operation | Arguments | Reply |
|---|---|---|
| ListGrokBotSecrets RPC | id:s (backend serverId) | {secrets:SecretMetadata[]} |
| PutGrokBotSecret RPC | id/name/description:s, value:s! | {secret?:SecretMetadata} |
| DeleteGrokBotSecret RPC | id/name:s | {} |
| setBoxSecrets gateway | secrets:map<s,s!>! | BoxSecretsStatus |
| carryBoxSecretsToBot gateway | serverId:s,names:s[] | {name:s,outcome:box-unreachable\|copied\|failed\|invalid-name\|invalid-value\|missing}[] |

**VERIFIED:** SecretMetadata={name/description:s,createdAtMs/updatedAtMs:i64}; the list cannot carry a value in this schema.
Desktop metadata projection keeps name/description/updatedAtMs, not createdAtMs. Bot secrets use backend serverId→RPC id,
not logical agentId; box secrets are account-scoped computer environment material and remain gateway operations even when
all bots are temporal. BoxSecretsStatus={keys:s[],cardKeys?:s[],isApplied:b,lastAppliedAtMs:n|null}; no values.
Sources: P `GrokBotSecret|`; M `function Kct(`, `function jct(`, `setBoxSecrets`; S `methods.setBoxSecrets`,
`methods.carryBoxSecretsToBot`, `$defs.SandBoxSecretsStatus`, `$defs.GrokBotSecretCarryOverResult`; C `function HK(`.

**VERIFIED — carry/name validation:** desktop carry combines gateway carry with a personal-secret fallback, de-duplicates
names, and writes to the bot with PutGrokBotSecret. Client name validator requires 1–128 characters, uppercase letter first,
then uppercase letters/digits/underscore. It rejects PATH/HOME/USER/SHELL/TERM/PWD/DISPLAY/HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/NO_PROXY,
prefixes LD_/CURSOR_/CLOUD_AGENT_/SAND_, and CURSOR_SANDBOX (case-insensitive). Personal carry validates trimmed value length
at least 8 and UTF-8 bytes at most 4096. This is client validation, not proof of server rules. Sources: M `function Xce(`,
`function Szn(`, `function Ypt(`, `function Wpt(`.
**VERIFIED:** list displays can only show metadata; no old value can be revealed through ListGrokBotSecrets. New-secret
dialog trims/uppercases names, rejects taken names, trims values, and uses an HTML password input with autocomplete off.
Secret-request and carry-over inputs also use password type. Sources: `dist/renderer/assets/chunk-team-setup-new-secret-dialog-CmhisEoU.js`
searches `password`, `toUpperCase`, `takenNames`; `dist/renderer/assets/chunk-view-BGnSiZcx.js` search `password`;
`dist/renderer/assets/chunk-view-DugoNXfA.js` search `password`. These mask typed values, not metadata.
**UNKNOWN:** server validation beyond these client paths requires server source or controlled validation captures.

## 7. Vault and payment methods

**VERIFIED — account backend vault:** operations have no agent ID, unlike per-bot named environment secrets. Vault credentials
are structured login/card/contact records with sites and descriptive metadata; reusable passwords are write-only here.
The enum has LOGIN/CARD/CONTACT and UNSPECIFIED, no NOTE kind; notes are a field. Sources: P `GrokBotVaultItemKind`,
`GrokBotVaultCredential|`; M `listGrokBotVaultCredentials(`, `putGrokBotVaultItem(`.

| RPC | Arguments | Reply |
|---|---|---|
| ListGrokBotVaultCredentials | includeKinds:E(GrokBotVaultItemKind)[], includeManaged:b | {credentials:Credential![]} |
| PutGrokBotVaultCredential | id:s!,title:s,username:s!,notes:s!,sites:s[],password:s! | {credential?:Credential!} |
| BatchCreateGrokBotVaultCredentials | logins:{title:s,username:s!,notes:s!,sites:s[],password:s!}[]! | {results:{result oneof credential:Credential! or error:s,refusal:E(GrokBotVaultCreateRefusal)}[]} |
| PutGrokBotVaultItem | item?:Credential!,secretFields:map<s,s!>!,notes?:s! | {item?:Credential!} |
| DeleteGrokBotVaultCredential | id:s! | {} |
| CreateGrokBotVaultCard (handoff) | values:map<s,s!>! | {credential?:Credential!} |
| UpdateGrokBotVaultCard (handoff) | id:s!,holderName/expiry:s!,billingAddress?:Address!,billingAddressId?:s!,nickname?:s,notes?:s! | {credential?:Credential!} |
| ListGrokBotStripeLinkPaymentMethods | {} | {outcome:E(GrokBotStripeLinkPaymentMethodsOutcome),paymentMethods:PaymentMethod![],unavailableCount:n} |

**VERIFIED — complete nested shapes:** Credential!={id:s!,title:s,username:s!,notes:s!,sites:s[],createdAtMs/updatedAtMs:i64,
card?:Card!,kind:E(GrokBotVaultItemKind),contact?:Contact!,managedBy:E(GrokBotVaultItemManager)}.
Card!={brand:s,last4:s!,expMonth/expYear:n,holderName:s!,billingAddress?:Address!,billingAddressId:s!,nickname:s}.
Address!={line1/line2/city/region/postalCode/country/name:s!,phone:s!}.
Contact!={address?:Address!,defaultShipping:b,email:s!,more?:{emails:s![],phones:s![]}}.
PaymentMethod!={id:s!,name:s,isDefault:b,kind:E(GrokBotStripeLinkPaymentMethodKind),brand?:s,last4?:s!,expMonth?/expYear?:n,ineligibleReason?:s}.
No password/PAN/CVC is declared in Credential/Card replies. SecretFields and card values are arbitrary sensitive maps;
their accepted key vocabulary is UNKNOWN here. Sources: P `GrokBotVaultCredential|`, `GrokBotVaultCard|`,
`GrokBotVaultCardBillingAddress|`, `GrokBotVaultContact|`, `GrokBotVaultContactMoreValues|`, `GrokBotStripeLinkPaymentMethod|`.

**VERIFIED:** desktop list requests all three kinds and includeManaged=true; maps int64s to numbers, omits raw kind from its
FM projection, and maps managedBy=GROK_BOT_EMAIL to grok-bot-email. PutGrokBotVaultItem is used for CONTACT, not evidence of a
note editor. Batch results distinguish imported/vault_full/refused; refusal enum is UNSPECIFIED/VAULT_FULL, with no numeric
limit. Stripe outcome is UNSPECIFIED/OK/NEEDS_AUTH/UNAVAILABLE/ACCOUNT_CLOSED; kinds UNSPECIFIED/CARD/BANK_ACCOUNT.
Temporal listVirtualCardPaymentMethods uses the backend RPC and maps to ok/paymentMethods/unavailableCount or needs_auth/
account_closed/unavailable. Sources: M `function FM(`, `function izn(`, `function hQn(`; P enum names above.
**INFERRED:** card entry remains handoff because it carries payment credentials; the RPC itself is not a browser ceremony.
**UNKNOWN:** encryption/storage enforcement, all accepted secretFields keys and actual capacity require server source.

## 8. 1Password

All rows are **VERIFIED backend RPCs**, including temporal credential decisions. P's shared `OnePasswordState|` is the
response of Get/CompleteConnection/CompleteOAuth/Sync/Delete; `OnePasswordCredentialDecisionResponse|` is Approve/Deny's reply.
Sources for desktop mappings: M `function cOt(`, `function Xx(`, `function sOt(`.

| RPC | Arguments | Reply |
|---|---|---|
| GetOnePasswordState | {} | State! |
| BeginOnePasswordConnection | connectionId:s!,vaultId:s!,serviceAccountToken:s! | mintTicket:s!,connectionId:s!,expectedGeneration:n,expirationMode:E(CredentialExpirationMode),providerExpiresInSeconds/credentialExpiresAtMs/ticketExpiresAtMs:i64,policyVersion:n,vaultId/vaultName:s! |
| CompleteOnePasswordConnection | mintTicket/serviceAccountToken/accountUuid/accountEmail/accountUrl:s! | State! |
| StartOnePasswordOAuth | connectionId:s!,connectLink:b,locale:s | authorizeUrl:URL!,state:s!,expiresAtMs:i64,redirectUri:s,connectUrl?:URL! |
| CompleteOnePasswordOAuth | state/code:s!,error:s | State! |
| StoreOnePasswordIntegrationKey | state/integrationKey:s! | connectionId:s! |
| SyncOnePasswordConnections | trigger:E(OnePasswordSyncTrigger) | State! |
| DeleteOnePasswordConnection | connectionId:s! | State! |
| NudgeOnePasswordAccessRequest | accessRequestId/agentId/entryId:s | nudged:b |
| ApproveOnePasswordCredentialRequest (handoff) | entryId/agentId:s,credentialId/connectionId/catalogRevision/targetSite:s!,harness:E(SandCredentialDecisionHarness) | ok:b,detail:s |
| DenyOnePasswordCredentialRequest (handoff) | entryId/agentId:s,harness:E(SandCredentialDecisionHarness) | ok:b,detail:s |

**VERIFIED — State!**={connections:Connection![],items:Item![],previousVaults:PreviousVault![]}.
Connection!={connectionId/accountUuid/accountEmail/accountUrl/vaultId/vaultName/catalogRevision:s!,itemCount:n,
lastSuccessfulSyncAtMs:i64,lastSyncErrorCode:s,credentialGeneration:n,issuedAtMs/expiresAtMs/renewByAtMs/reminderAtMs:i64,
lifecycleState:E(CredentialLifecycleState),expirationMode:E(CredentialExpirationMode),providerExpiryRequested:b,
connectionKind:E(OnePasswordConnectionKind),brokerState:E(OnePasswordBrokerConnectionState)}.
Item!={credentialId/title/category:s!,sites:s[],targetRules:{kind:E(CredentialTargetRuleKind),scheme/host/registrableDomain:s,port:n}[],
vaultName/connectionId/catalogRevision:s!,hasOneTimeCode:b}. PreviousVault!={connectionId/accountUuid/vaultId/vaultName:s!,itemCount:n}.
No password/token/OTP value is in State. Sources: P `OnePasswordState|`, `OnePasswordConnection|`, `OnePasswordCredentialItem|`,
`OnePasswordPreviousVault|`, `CredentialTargetRule|`.
Enums: lifecycle UNSPECIFIED/ACTIVE/EXPIRING/GRACE/EXPIRED/PROVIDER_REJECTED; expiration UNSPECIFIED/DISABLED/WARN/ENFORCE;
kind UNSPECIFIED/SERVICE_ACCOUNT/OAUTH_BROKER; broker UNSPECIFIED/PAIRING/CONNECTED/RECONNECT_REQUIRED;
sync UNSPECIFIED/MANUAL/APP_FOCUS; harness UNSPECIFIED/BOX/TEMPORAL; target rule UNSPECIFIED/EXACT_HOST_PORT/REGISTRABLE_DOMAIN.
Sources: P searches are the exact enum names above. M's State projection renames connections→accounts and items→directory.items,
uses directory=null with no connections, and converts positive optional timestamps; it is not raw protobuf JSON (`function Xx(`).

**VERIFIED — OAuth steps:** (1) StartOnePasswordOAuth (desktop forwards only connectionId); (2) open authorizeUrl in a dedicated
Electron BrowserWindow; (3) observe navigation matching redirect origin/path or an app deep link, with state!, code!, error,
optional fragment integration_key!; (4) store integration key when present, then CompleteOnePasswordOAuth; (5) install returned
state and notify credentials-changed. A callback with code but no fragment has a short grace period. Browser consent timeout
is ten minutes, not the server ticket lifetime. Sources: M `function EOt(`, `function Msr(`, `function OAe(`, `async function bOt(`,
`function xOt(`, `Y.emit("credentials-changed",{})`.

**VERIFIED — service-account alternative:** UI offers native mint, pasted service-account token (password input), developer
settings app link and service-account documentation. Begin obtains policy/ticket, Complete submits mintTicket plus token and
account metadata; sync refreshes catalog and delete disconnects. Sources: N `credential-token-form`, `sand-1password-service-account-token`,
`onepassword://settings/developers`, `service-accounts/get-started`; M `function cOt(`.
**UNKNOWN:** full native mint subprocess sequence: M `function MOt(` imports `./onepassword-connection-service.cjs`, absent
from this extraction. That module would settle which user prompts/browser steps mint/renew require. Do not invent that flow.

**VERIFIED — request approval:** browser-login uses Approve/Deny with TEMPORAL harness; brokered requests can open 1Password
or the configured website `/bot/1password/approve`, with access_request_reference! and access_request_id in the fragment.
App callback `/v1/onepassword-approval-callback` carries accessRequestId/status/error and settles the matching pending request;
Nudge requests notification, not approval. Sources: M `function vsr(`, `function fOt(`, `onepassword-approval-callback`;
protocol-m2 section 8 for card fields. **INFERRED:** retain handoff because the credential provider/user performs access/fill.

## 9. Passkeys and spend approval

| RPC | Arguments | Reply |
|---|---|---|
| ListPasskeys | {} | {passkeys:{credentialId:s!,name:s,createdAtMs:i64,lastUsedAtMs?:i64,deviceType:s,backedUp:b}[]} |
| RevokePasskey | credentialId:s! | {} |
| StartPasskeyEnrollment | {} | {} |
| VerifyPasskeyEnrollmentCode | code:s! | enrollmentTicket:s! |
| BeginPasskeyRegistration | enrollmentTicket:s! | ceremonyId:s,creationOptionsJson:s!,ceremonyPath:s,ceremonyToken:s! |
| GetPasskeyCeremonyStatus | ceremonyId:s | status:E(PasskeyCeremonyStatus) |
| BeginGrokBotSpendApproval | agentId/requestId:s,paymentMethodId?:s!,mode:E(SpendApprovalCeremonyMode),enrollmentTicket?:s! | ceremonyId/challengeId:s,requestOptionsJson/creationOptionsJson:s!,ceremonyPath:s,ceremonyToken:s! |

**VERIFIED:** account-level enrollment starts an email-code flow, verifies a six-digit code, then begins hosted registration;
spend begins assertion or registration for a bot request. Status is UNSPECIFIED/PENDING/COMPLETED/FAILED/EXPIRED, mode
UNSPECIFIED/ASSERT/REGISTER. The app opens the configured website plus validated `/grok-bot/passkey/` ceremonyPath, with
token! and optional challenge_id in the fragment, then polls GetPasskeyCeremonyStatus each second until terminal (five-minute
deadline and final status read). WebAuthn user authentication belongs in browser/app; list/revoke are ordinary backend calls.
Sources: M `function Upt(`, `function Fyt(`, `function Ght(`, `function BOt(`; P `Passkey|`, enum names above.
Desktop List converts timestamps and normalizes deviceType singleDevice/multiDevice→single_device/multi_device (else unknown).
Temporal beginSpendApproval adapter forwards agentId/requestId/paymentMethodId and returns challenge metadata or not_required;
it does not expose the raw options JSON. Sources: M `function qVn(`, `function fQn(`; protocol-temporal section 1.
**UNKNOWN:** registered key policy/capacity and server email-code lifetime require server source; no secret keys are listed.

## 10. Desktop computer / forever box

**VERIFIED:** the forever box is the remote persistent computer surface, independent of whether the bot runs temporally.
getForeverBoxStatus/ensureForeverBox are gateway commands with {id:s}; ensure returns Status|null, read returns Status|null;
updateForeverBox({id:s}) returns Status; handBackForeverBox({id:s,requestId?:s,trigger?:button|dismissed|viewer-closed|null})
returns null. The temporal hand-back parser requires a nonempty requestId, calls EndGrokBotBoxHandoff({agentId:id,requestId,
trigger:E(GrokBotBoxHandBackTrigger)}), discards {dispatched:b,workflowId?:s}. Trigger absent defaults VIEWER_CLOSED; other
values map to BUTTON/DISMISSED. Ensure/update have no temporal action adapter twin. Sources: S methods of those names;
C `foreverBoxStatusCommand`, `case"handBackForeverBox"`, `function HK(`; M `case"handBackForeverBox"`, `function XGn(`;
P `EndGrokBotBoxHandoffRequest|`, `EndGrokBotBoxHandoffResponse|`.

**VERIFIED — Status:** {agentId:s,state:absent|hibernated|running,vncUrl:s!|null,windows?:{windowIndex:n,vncUrl:s!}[],
handoff?:{requestId:s,instruction:s!}|null,pull?:{percent:n}|null,hostVersion?:s|null,
hostUpdateAvailable?/imageUpdateAvailable?:b|null,diskPressure?:{level:hard|soft}}.
Sources: S `$defs.SandForeverBoxStatus`, `$defs.SandForeverBoxWindow`, `$defs.SandBoxHandoffInfo`, `$defs.SandBoxPullStatus`.
These are not five wire states: asleep is hibernated; waking is pending ensure; ready is running with nonempty vncUrl;
updating is pull/progress or the desktop rebuild state; handoff is an overlay, not another run-state enum.
UI phase mapping: pulling when pull exists; otherwise running/local for running with/without VNC, starting for pending wake,
sleeping for hibernated, off otherwise. Live view uses vncUrl/windows; C rewrites primary/window VNC URLs through its proxy.
Sources: R `function RQ(`, `function zQ(`, `function YWt(`; C `function DB(`; protocol-tui section 10.

**VERIFIED — update exception:** desktop updateComputer invokes RecreateSandBox with preserveData=true,force=false and optional
acknowledgeTerminalUpgradeSchedule; only dev-fallback invokes gateway updateForeverBox. Accepted recreation returns
started/operationId or started-untrackable; rejected carries reason. Migration progress is watched separately through
WatchSandBoxMigration (backing-up/creating/moving/cleaning-up/wiping/done/failed), not a new forever-box state.
Sources: M `updateComputer:async`, `async recreate({preserveData`, `async function*Nbn(`, `function Bbn(`.
**UNKNOWN:** server persistence guarantees and full wake/update internals; gateway contract plus UI does not prove them.

## 11. Browser/app handoff inventory and completion

All observed rows below are **VERIFIED client paths**; URL values can vary by backend/account. Completion is not inferred
from merely opening a URL. This consolidates sections 1–10 rather than introducing new gateway events.

| Area / URL opened | Completion observation | Bundle citation |
|---|---|---|
| Slack manager connect: Start.url!; Slack install/reinstall/approval: oauthAuthorizeUrl! | GetGrokBotSlackInstallState status/workspaces/managerAuthUpdatedAtMs, approval flags and manifest-update state; explicit check/focus/poll | M `function cut(`; R `function PFn(`, `grok-bot-slack-connect-poll` |
| Teams connect/admin consent: consentUrl!/adminConsentUrl!; bot links teamsAppUrl!, packageDownloadUrl! | GetGrokBotTeamsInstallState with consentNonce!: consentResult, connectedAccount, state, terminal/pollAfterMs; package download itself has no completion acknowledgement | R `consentPollPolicy.start`; M `function Qht(`, `function TVn(`; P `GrokBotTeamsBotStatus\|` |
| Human Teams account: authorizationUrl! | poll GetMicrosoftTeamsAccountLinkStatus; new tenantId/aadObjectId/linkedAtMs tuple, focus refresh | R `function jIn(` |
| Listener/SCM connect: returned url!; Slack account listener desktop link URL! | SCM deep-link callback→completeGithubConnect outcome; integrations.isConnected polling; Slack isSlackLinked | R `function YBn(`, `github-connect-callback`, `function GBn(` |
| SMS smsUri! | QR/copy handoff to phone, then list/status refresh and new phone linkedAtMs; no desktop external-browser open proven | V `value:r.smsUri`; R `requestLinkCode:async` |
| 1Password authorizeUrl! | embedded browser navigation or OAuth app callback state/code!/error/integrationKey!→store key/complete OAuth→State | M `function EOt(`, `function OAe(`, `async function bOt(` |
| 1Password developer settings app link; service-account docs/blog | manual native mint/token submission; no browser-finished event for informational links | N `onepassword://settings/developers`, `service-accounts/get-started` |
| 1Password request appLink! or website /bot/1password/approve with fragment references! | matching approval app callback accessRequestId/status/error; provider decisions/nudge, not gateway OAuth event | M `function vsr(`, `function fOt(`, `onepassword-approval-callback` |
| Passkey registration/spend hosted ceremony URL! | GetPasskeyCeremonyStatus.status becomes completed/failed/expired | M `function Fyt(`, `function Ght(` |
| Payment approvalUrl! returned by virtual-card resolution | transcript approval/card state; not a dedicated URL-finished SSE event | M `function mQn(`; protocol-m2 section 8 |

**UNKNOWN:** an exhaustive inventory inside the absent native 1Password module and server-hosted pages; retrieve that module
and those page handlers to settle their additional redirects/completion steps. No external browser finish is established for
plain inbox creation, secret/vault CRUD or VNC viewing; those operations complete through replies/events described here.

## 12. Events and read-only capture shortlist

**VERIFIED — gateway `/events`:** events are framed as channel/payload (protocol-tui section 1). Relevant exact contracts:

| Channel | Payload | Citation |
|---|---|---|
| forever-box | Status from section 10, including handoff/pull/window changes | S `events.forever-box`, `$defs.SandForeverBoxStatus`; R `ingestForeverBox:` |
| computer-action | {agentId:s,type:click\|drag\|move\|scroll,x:n,y:n,button?:s,count?:n} | S `$defs.SandComputerActionEvent`; R `ingestComputerAction:` |
| messages-grants | {requestId:s,grants:(automation\|contacts\|fullDiskAccess)[]} | S `$defs.SandMessagesGrantsRequest` |
| box-disk-pressure | {level:hard\|soft} or null | S `events.box-disk-pressure`, `$defs.SandBoxDiskPressure` |
| server-roster-changed | {kind:agent,agentId:s} or {kind:resync} or {kind:user-settings,explicit:b,fields:(autoReview\|hasSeenOnboarding\|jobRole\|libraryPins\|mainAgent\|mcpServers\|pinnedAgents\|sidebarSections\|timeZone)[]} | S `$defs.SandServerRosterChange` |
| host-settings | {fields:SandHostSettingsField[]} (includes messagesEnabled, webauthnProxyEnabled, mcpBoxServers and permission settings; no secret values) | S `$defs.SandHostSettingsChangedEvent`, `$defs.SandHostSettingsField` |

**VERIFIED:** no dedicated Slack/Teams/SMS/inbox/secrets/vault/passkey completion channel is declared in S.events.
R uses status polling for channel connect flows and refreshes secret/inbox resources after mutations/reconnect.
credentials-changed={} is desktop IPC, not gateway SSE; OAuth/approval callbacks are app deep links/browser navigation,
not `/events` channels. Sources: S `events`; M `Y.emit("credentials-changed",{})`; R `function AFn(`, `function jIn(`,
`function YBn(`, `requestLinkCode:async`. Transcript/agent events can update handoff/payment cards (protocol-m2 section 8),
but roster changes do not promise every account-level integration update. **INFERRED:** subscribe before actions, refresh
from declared events, and retain the app's bounded polling where no completion event exists.

Read-only capture candidates (**VERIFIED request intent**, no live calls made):

- Gateway: getListenerIntegrations({}); getBoxSecretsStatus({}); getForeverBoxStatus({id}).
- Backend Slack/Teams: GetGrokBotSlackInstallState, GetGrokBotTeamsInstallState, ListGrokBotTeamsJoinedTeams,
  GetMicrosoftTeamsAccountLinkStatus. Use logical agentId for install reads.
- Backend account lists: GetGrokBotMessagingLinkStatus, ListGrokBotMessagingLinkedPhones, ListGrokBotEmailInboxes,
  ListGrokBotSecrets (backend serverId), ListGrokBotVaultCredentials, ListGrokBotStripeLinkPaymentMethods,
  GetOnePasswordState, ListPasskeys. GetPasskeyCeremonyStatus is a read only for an already-issued ceremonyId.
- Declared email observation candidates without located desktop callers: ListGrokBotEmailThreads, SearchGrokBotEmailThreads,
  ReadGrokBotEmailAttachment. Their presence is not proof of account capability or desktop parity; attachment reads expose content!.
  Exclude ReadGrokBotEmailThread: its markedReadMessageIds reply indicates a possible read-state mutation.
- SSE subscription is observational. Get/list reads may have server audit/cache activity; no business mutation is requested.
  Sources for shortlist: S methods above; P corresponding Request/Response descriptors; M `function cut(`, `function Kct(`,
  `function Pct(`, `function cOt(`, `function BOt(`; desktop read/write Teams classification at `Zut("read"`.

Do not include getListenerConnectUrl in a no-side-effect capture: despite its name it can mint OAuth state. Start/connect,
issue code, ensure/wake, sync, nudge, carry, put, delete, revoke, install/uninstall, hand-back and all approval/enrollment
operations are mutations or user handoffs. **UNKNOWN remaining:** actual default/empty/nonempty server replies, authorization
rules, installation side effects, server account limits, code TTLs and missing native 1Password internals.
Authorized read-only captures settle reply serialization; server/policy source or separately authorized controlled
mutations are needed for limits, expiry and side effects. No mutation is needed merely to capture the listed account reads.
