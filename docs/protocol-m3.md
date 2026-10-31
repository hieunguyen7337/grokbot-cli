# M3 bot management: Grok Bot 0.77.0

Offline research of the supplied `_bundle-077`, read-only; no live service, credentials or private configuration accessed.
Only this document was written. **VERIFIED** means client code/schema evidence, **INFERRED** means interpretation,
and **UNKNOWN** means the supplied client does not settle it. A schema is a declared contract, not a deployed-server probe.
Identifiers and enum values below are facts; descriptions are in our own words.

Notation: `?` optional, `null` explicitly nullable, `[]` array; IDs/text are strings, gateway counts/times are numbers.
Backend `int64` is bigint in generated JS and a decimal string in protobuf JSON; backend bytes use base64 in JSON.
Backend nested messages may be absent. `Agent` and `Entry` refer to protocol-tui sections 5 and 2; paging/opening is section 3.
Backend `ServerAgent` means `GrokBotAgent`, distinct from the gateway row (see section 9).

Every citation is a bundle-relative path plus a short search string. Abbreviations:

- **C**: `dist/node-agent-coordinator/main.cjs`.
- **M**: `dist/electron-main/main-app.cjs`.
- **P**: `dist/electron-main/proto.cjs`.
- **R**: `dist/renderer/assets/index.eager-app-BtIHj2If.js`.
- **A/name**: `dist/renderer/assets/name`.
- **S**: C, search `async function are()`, decode the adjacent `wz` base64/raw-DEFLATE value in memory.
  `methods.<command>` and `$defs.<name>` below are exact keys in that decoded schema, not plaintext bundle hits.

## 1. Blank creation, kickstart and naming

**VERIFIED — gateway contracts:** **S `methods.createAgent`, `$defs.SandCreateAgentArgs`, `$defs.SandCreateAgentResult`**.

| Command | Arguments → reply |
|---|---|
| createAgent | name/description:string; title/avatarShape/avatarColor/avatarPngBase64/clientNonce/language/templateId?:string; creationRoute?:`{kind:box}\|{kind:temporal,scope:string}\|null`; origin?:`dev\|user\|null`; purpose?:`disk-saver\|plugin-auth\|null`; harness?:`box\|temporal\|null`; isAutomatic/isIntroductionSuppressed/isKickstartRequested/supportsTemporalHarness?:boolean\|null → `{agent:Agent,transcript:Entry[]}` |
| kickstartAgent | `{id:string}` → `{isIntroductionInFlight:boolean}\|null` |
| seedConversationName | `{id:string,prompt:string}` → `{agent:Agent\|null,outcome:kept\|seeded}` |

The last two contracts are **VERIFIED: S `methods.kickstartAgent`, `$defs.SandKickstartAgentResult`,
`methods.seedConversationName`, `$defs.SandConversationNameSeedOutcome`, `$defs.SandConversationNameSeedResult`**.
`title` is optional free text, separate from name and description; the UI displays a nonempty title as secondary identity text
unless it repeats the name. No title enum is declared. Shape/color are strings, not gateway enums; UI choices are in section 5.
`origin:user` is used by normal creation; `dev` and helper-purpose creation require the host/box path. A temporal route's scope
binds creation to the account/backend that resolved it; it is not a user-entered bot category. Sources: **R `function am(`,
`var Zp=`, `function Kp(`; C `if(Q.method==="createAgent")`; M `function lot(`**.

**VERIFIED — new-bot dialog:** asks for a name and character shape/color, with a preview; nonblank trimmed name required,
input max length 255. Its creator sends trimmed name (also sliced to 255), description defaulting to empty, `origin:user`,
`isKickstartRequested:true`, a launch `clientNonce`, selected avatar fields and optional templateId. The roster layer adds language.
It does not ask for instructions, title, route or PNG in this dialog. It then requests kickstart through the launcher for box bots;
temporal bots skip that request. Sources: **R `function N$t(`, `async function P$t(`, `kickstartAwaitingFirstMessage:async`,
`e.source.createAgent({...t,language:e.language()})`**.

**VERIFIED — effect visible to client:** kickstart is the introduction/first-message phase; temporal creation already requests
that phase and the coordinator returns `isIntroductionInFlight:false` for a temporal kickstart. Naming is separate: after a prompt
send without taskId the renderer requests naming from `conversationNamePrompt ?? prompt`; its roster implementation only forwards
this for an unnamed temporal one-member group with at most one person. It optimistically collapses whitespace and truncates to
72 characters, reconciling on `seeded` versus `kept`. It is not an unconditional second step of the new-bot dialog.
Sources: **C `if(O==="kickstartAgent"&&Ae==="temporal")`; R `async function Rfe(`, `async function FWn(`,
`function vme(`, `function mme(`**. **UNKNOWN:** actual box introduction generation and server naming eligibility need host/server
implementation or a capture of those commands; the client response does not prove a message was produced.

**VERIFIED — Temporal RPC:** `CreateGrokBotTemporalAgent` shares the request/response classes of `CreateGrokBotAgent`, rather
than having separate Temporal-named messages. Request: legacyAgentId/name/description/title/avatarShape/avatarColor/agentId:string,
avatarDataUrl?:string, harness:HarnessKind enum, kickstartRequested/introductionSuppressed/createdAutomatically?:boolean,
purpose/origin/language?:string, createIntent:enum, createCaller:enum. Reply `{agent?:ServerAgent,harness:HarnessKind}`.
Sources: **P `createGrokBotTemporalAgent:{`, `CreateGrokBotAgentRequest|`, `CreateGrokBotAgentResponse|`**.
Declared HarnessKind values: UNSPECIFIED, BOX, TEMPORAL; createIntent: UNSPECIFIED, FRESH, REGISTER_EXISTING_LOCAL;
createCaller: UNSPECIFIED, ROOM_MEMBERS, ENSURE_SERVER_BACKED, MINT, BACKFILL, PRODUCT_CREATE. Sources: **P
`"GrokBotAgentHarnessKind",[[`, `"GrokBotAgentCreateIntent",[[`, `"GrokBotAgentCreateCaller",[[`**.
The desktop uses it when server-owned temporal creation is enabled and a scoped route plus clientNonce exist. It uses the nonce
as agentId, forces TEMPORAL, converts optional PNG to a data URL, and rejects a different returned identity/harness. Its normalized
reply has an empty transcript. With a box route C strips creationRoute and avatarPngBase64 before forwarding createAgent.
Sources: **M `function lot(`; C `let{avatarPngBase64:F,creationRoute:ue,...ae}=Q.args`**.
**UNKNOWN:** server acceptance/meaning of every createIntent/createCaller value is not demonstrated by this caller, which omits them.

## 2. Templates and duplication

**VERIFIED — browsing:** desktop marketplace browsing calls `ListPublicGrokBotMarketplaceListings`, paging with pageSize=100
and nextPageToken until empty. Request `{category?:string,pageSize:number,pageToken:string}`; reply
`{featuredListings:PublicListing[],listings:PublicListing[],nextPageToken:string,allCategoriesOrder:string[]}`.
PublicListing has slug/name/description/category/shareId:string, createdAtMs/updatedAtMs:int64, categories:string[],
creator?:Creator and an avatar oneof imageUrl:string or defaultAvatar:{shape:string,color:string}.
Public Creator has name/profilePhotoUrl:string, handles:map<string,string>; it has no id or timestamps.
Public listings contain no numeric listing id, template id or version id; do not substitute the internal marketplace message.
The renderer-facing adapter keeps slug/name/description/category/categories/shareId/avatar/creator and drops listing timestamps.
Sources: **M `listMarketplace:async`, `function iXe(`; P `ListPublicGrokBotMarketplaceListingsRequest|`,
`ListPublicGrokBotMarketplaceListingsResponse|`, `PublicGrokBotMarketplaceListing|`, `PublicGrokBotMarketplaceCreator|`**.

**VERIFIED — import preparation:** `GetGrokBotTemplateImportDetails({shareId:string})` returns
`{template?:Template,blobGetUrl:string,expectedActiveVersion:number,creatorDisplayName:string}`.
Template fields: shareId/name/avatarShape/avatarColor/description:string; sourceAgentId/blobObjectKey/imageUrl?:string;
createdAtMs/updatedAtMs:int64; published:boolean; activeVersion?:number; visibility:enum; ownerType:enum.
Visibility is UNSPECIFIED/PUBLIC/TEAM; ownerType is UNSPECIFIED/USER/TEAM. Sources: **P
`"GrokBotTemplateVisibility",[[`, `"GrokBotTemplateOwnerType",[[`**.
The desktop downloads/decodes the recipe from blobGetUrl and requires a template, URL and activeVersion >=1; the display summary
and the recipe instructions are separate (`mat` places instructions into the imported preview's description).
Sources: **P `GetGrokBotTemplateImportDetailsRequest|`, `GetGrokBotTemplateImportDetailsResponse|`, `GrokBotTemplate|`;
M `getPublicTemplate:async`; R `function mat(`**.

**VERIFIED — gateway contracts:** **S `methods.createAgentFromTemplate`, `$defs.SandCreateAgentFromTemplateArgs`,
`$defs.SandCreateAgentFromTemplateResult`, `methods.listBotTemplates`, `methods.getBotTemplateVersion`,
`methods.getBotTemplateForSourceAgent`, `methods.getBotTemplateExportPolicy`**.

| Command | Arguments → reply |
|---|---|
| createAgentFromTemplate | shareId/agentId/name/avatarShape/avatarColor:string, expectedActiveVersion:number; creatorContext/language?:string; isAutomatic/isAutoOpen?:boolean\|null; importEntry?:`chat_link` → `{agent:Agent,transcript:Entry[],setup:Setup}` |
| listBotTemplates | no arguments → TemplateView[] (declared; no desktop invocation found) |
| getBotTemplateVersion | `{shareId:string,version:number}` → TemplateView |
| getBotTemplateForSourceAgent | `{sourceAgentId:string}` → TemplateView\|null |
| getBotTemplateExportPolicy | no arguments → `{exportPolicy?:all\|none\|team_only\|null}` |
| duplicateAgent | `{id:string}` → `{agent:Agent,transcript:Entry[]}` (declared; no desktop invocation found) |

Setup is `{kind:unavailable}` or `{kind:recipe,automations:Routine[],memories:Memory[],plugins:Plugin[],skills:Skill[],
gettingStartedSkill?:string,isConversationalSetup?:boolean|null,isSetupSendSuppressed?:boolean|null,
isTrustedSource?:boolean|null,splitStateTools?:boolean|null}`. Routine={content,description,name,slug:string};
Memory={content:string,createdAt?:string,kind?:log|profile|null}; Plugin={name,pluginId:string,description?:string};
Skill={content,description,name:string}. Sources: **S `$defs.SandCreateAgentFromTemplateResult`**.

TemplateView has required shareId/shareUrl/name/avatarShape/avatarColor:string and either body:string or description:string
(two historical wire variants). Optional: sourceAgentId/title/creatorName:string; activeVersion/version/createdAtMs/updatedAtMs:number;
active/published:boolean|null; visibility:public|team|null; memory:Memory[], plugins:Plugin[], routines:Routine[], skills:Skill[].
There is no separate id field; use shareId and optional sourceAgentId for their respective identities.
Sources: **S `$defs.SandBotTemplateGatewayView`, `$defs.SandBotTemplateWireView`, `$defs.RegressionEraBotTemplateWireView`**.

**VERIFIED — backend twins:** GetGrokBotTemplateVersion request shareId:string/version:number returns
`{version:number,active:boolean,createdAtMs:int64,blobObjectKey:string,blobGetUrl:string,visibility:enum}`; the adapter downloads
the recipe and builds the richer TemplateView. GetGrokBotTemplateForSourceAgent request sourceAgentId:string returns
`{template?:Template,exportPolicy?:string,hasTeam?:boolean}`. GetGrokBotTemplateExportPolicy has empty request and
`{exportPolicy?:string,hasTeam?:boolean}`. CreateGrokBotAgentFromTemplate takes shareId/agentId:string,
expectedActiveVersion?:number, firstPartyTemplate?:enum, creatorContext/language?:string, setupDelegationSupported?:boolean,
importEntry?:enum; returns `{agent?:ServerAgent,blobGetUrl?:string,setupHandledByServer:boolean,
conversationalSetupEnabled:boolean,gettingStartedTrusted:boolean,updateStateSplit:boolean}`.
Sources: **P search each named RPC plus `Request` / `Response`; M `getVersion:async`, `getForSourceAgent:async`,
`setupDelegationSupported:!0`**. The desktop sends a reserved new agentId, the reviewed expectedActiveVersion and current language;
creatorContext is optional extra setup context (also used by onboarding), not the source agent ID.
Sources: **R `expectedActiveVersion:y.expectedActiveVersion`, `creatorContext:l`; M `createGrokBotAgentFromTemplate({`**.

**UNKNOWN — duplicate workflow:** no desktop invocation of duplicateAgent or DuplicateGrokBotAgent was found, nor a proven
source-agent-template-to-import duplicate action. Declared `DuplicateGrokBotAgent({sourceAgentId:string,agentId:string})`
returns `{agent?:ServerAgent}` (**P `DuplicateGrokBotAgentRequest|`, `DuplicateGrokBotAgentResponse|`**).
Template export/import and team cloning exist but do not prove a general duplicate button. Settle with a capture while invoking
the desktop's duplicate/copy action, including its menu entry and request, or an identified renderer handler.

## 3. Editing and instructions

**VERIFIED:** `updateAgent({id:string,profile:Profile,editedFields?:string[]}) → Agent|null`.
Profile requires name/description:string and permits title/avatarShape/avatarColor?:string. There is no instructions,
systemPrompt, avatarDataUrl or PNG field in this profile. `editedFields` is unrestricted string[] at the gateway boundary;
the renderer derives it from exactly name, description, title, avatarShape, avatarColor.
Sources: **S `methods.updateAgent`, `$defs.SandAgentProfile`; R `var Up=`, `function Wp(`**.

**VERIFIED:** `UpdateGrokBotAgent` takes id:string, name/description/title/avatarShape/avatarColor?:string,
partialUpdate?:boolean and an avatar-change oneof clearAvatar:empty message or avatarDataUrl:string; reply `{agent?:ServerAgent}`.
The direct identity adapter sets partialUpdate=true, rather than sending profile/editedFields. Nonowner managed rows with serverId
use this direct identity writer, including avatar changes. Sources: **P `UpdateGrokBotAgentRequest|`, `UpdateGrokBotAgentResponse|`;
M `updateIdentity:async`; R `function NGn(`**.

**VERIFIED — editor reads:** the classic editable description is the selected roster row's description through `hO`;
name changes preserve it, description changes preserve name, and title has a separate handler. No extra instructions-read command
is needed for that form. Template recipe instructions are also mapped into description for preview/import (section 2).
Sources: **R `function v7e(`, `function hO(`, `function wDn(`, `function mat(`**.
**INFERRED:** description is the editable bot-level instruction text in this profile surface, rather than a second systemPrompt field.
**UNKNOWN:** the host's full assembled system prompt and physical storage of instructions are not in these client contracts;
knowledge/skills are additional surfaces, not proof that profile has an instructions array. Settle with host producer source or
a capture comparing roster/profile and the edit form before/after editing instructions.

## 4. Deletion

**VERIFIED:** `deleteAgents({ids:string[]}) → {transcript:Entry[],refusedAgentIds?:string[],failedAgentIds?:string[]}`;
the reply is not a success boolean or deleted-agent list. `DeleteGrokBotAgent({id:string})` returns an empty protobuf response.
Sources: **S `methods.deleteAgents`, `$defs.SandDeleteAgentResult`; P `DeleteGrokBotAgentRequest|`, `"DeleteGrokBotAgentResponse"`**.
The coordinator separates box and temporal IDs, deletes temporal agents individually via backend and combines failures/refusals;
successful temporal deletes also get a background box mirror cleanup. Sources: **C `U=async(O,$)=>`,
`sand.coordinator.box_delete_mirror_deferred`; M `function vSt(`**.

**VERIFIED — confirmation:** the dialog shows selected name/count and Delete/Cancel buttons; there is no typed-name input in this
confirmation request. Groups are supported. Its warning says group chat history is removed but member bots survive; ordinary bot
warning says its conversation history is removed; shared-team warning includes teammates' chats/routines. These are the app's
stated effects, not verification of physical server erasure. Sources: **R `function Bit(`, `function Rit(`, `function zit(`,
`SH6elt`, `LtJGSk`, `SeNRHj`**. Current main agent is excluded from delete targets; replace-main is offered instead (section 8).
**UNKNOWN:** server transcript retention/backups, cross-session cleanup and direct deletion of a current main agent require server
source or controlled before/after evidence; an empty backend reply does not establish those details.

## 5. Avatars

**VERIFIED — gateway:** `getAgentAvatar({id:string}) → {dataUrl:string|null,version:string|null}`;
`setAgentAvatarBytes({id:string,pngBase64:string|null}) → Agent|null`;
`generateAgentAvatarImage({description:string}) → {imageBase64:string,mimeType:string}`.
No size/dimension constraint is declared by these argument validators/schema. Generation has no agentId and is not a save.
Sources: **S `methods.getAgentAvatar`, `$defs.SandAgentAvatarResult`, `methods.setAgentAvatarBytes`,
`methods.generateAgentAvatarImage`, `$defs.SandGeneratedAvatarImage`; C `setAgentAvatarBytes:I().args`**.

**VERIFIED — desktop editor:** file/paste input rejects above 25 MiB; decoded candidate is downscaled to a maximum 1024-pixel
edge, then cropped/resampled to a 256×256 PNG and submitted as PNG base64. Generation uses the desktop image service returning
a data URL (not the gateway result object), stages a crop candidate and then saves; a finished result after closing the editor can
also be cropped/saved automatically. Null clears the image in the renderer identity representation.
Sources: **A/chunk-agent-avatar-editor-DOI3ZpiE.js `function le(`, `de=1024`, `async function he(`,
`async function ve(`, `commitDismissedResult:async`; R `NQn=26214400`, `function PQn(`, `function qde(`, `function xWn(`;
M `generateAgentAvatarImage:({description:d})`, `generateImage:async`**.
**UNKNOWN:** host-enforced PNG byte/dimension limits require host source or documented rejection captures; UI export size is not
a gateway limit. The desktop generation path should not be assumed to return `{imageBase64,mimeType}`.

**VERIFIED — UI identifiers:** shapes: blob, pebble, bean, egg, squircle, tablet, capsule, cylinder, hex, gem, crystal, wedge,
shield, dome, arch, cloud, teardrop, leaf, square, sparkle, clover, flower, heart, house, star, pumpkin.
Colors: black, brown, red, orange, yellow, green, cyan, blue, violet, magenta, gray. Availability can be feature-gated/limited;
these are UI identifiers, not an exhaustive server allowlist. Sources: **R `ED={blob:`, `DD={black:`, `function kD(`**.
Roster carries avatarDataUrl:string|null and optional avatarShape/avatarColor/avatarVersion:string|null,
avatarPhoto?:{kind:file|protocol,key:string,retry?:number}|null. Sources: **S `$defs.SandAgentSummary`,
`$defs.RosterPhotoReference`, `$defs.RosterPhotoKind`**; see protocol-tui section 5 for the rest of the row.

## 6. Voice

**VERIFIED:** `setAgentVoice({id:string,voiceId?:string|null,voiceSpeed?:number,voiceLanguage?:string}) → null`.
`SetGrokBotAgentVoice` request is id:string, voiceId?:string, voiceSpeed?:float, voiceLanguage?:string; reply `{agent?:ServerAgent}`.
The direct adapter maps null voiceId to an empty string. Neither wire schema declares an ID allowlist or numeric range.
Sources: **S `methods.setAgentVoice`; P `SetGrokBotAgentVoiceRequest|`, `SetGrokBotAgentVoiceResponse|`; M `setVoice:async`**.

**VERIFIED — constant UI catalog:** IDs and labels (label is capitalized as shown): altair/Altair, ara/Ara, atlas/Atlas,
aurora/Aurora, carina/Carina, castor/Castor, celeste/Celeste, cosmo/Cosmo, eve/Eve, helios/Helios, helix/Helix, iris/Iris,
kepler/Kepler, leo/Leo, liora/Liora, lumen/Lumen, luna/Luna, lux/Lux, naksh/Naksh, orion/Orion, perseus/Perseus, rex/Rex,
rigel/Rigel, sal/Sal, sirius/Sirius, ursa/Ursa, zagan/Zagan, zenith/Zenith. No list-voices RPC is used by this picker.
Speed options are 0.5, 0.75, 1, 1.25, 1.5, 2 (labels append x); invalid input defaults to 1, other numbers snap to nearest option.
Language options: auto, en, ar-EG, ar-SA, ar-AE, bn, ca, zh, da, nl, fi, fr, de, hi, hu, id, it, ja, ko, pl, pt-BR, pt-PT,
ru, es-MX, es-ES, sv, th, tr, vi. Unknown/empty language normalizes to auto; locale matching can collapse to a unique base language.
Sources: **R `var B7e=`, `var wM=`, `function CM(`, `function OM(`, `function kM(`**.

**VERIFIED — preview:** play/pause buttons in the picker select a greetingId and call
`previewVoice({voiceId:string,greetingId:string}) → {audioBase64:string,mimeType:string}`. Clips cache by voice/greeting, playback
stops when picker closes or another voice starts. The preview request has no speed/language field. Sources: **S
`methods.previewVoice`, `$defs.SandVoicePreviewAudio`; R `function t9e(`, `n.previewVoice({voiceId:s,greetingId:l}`, `function n9e(`**.
Current voice fields are roster voiceId?:string|null, voiceSpeed?:number, voiceLanguage?:string; picker/settings panel uses them.
Sources: **S `$defs.SandAgentSummary`; R `function PM(`**. **UNKNOWN:** actual server supported IDs/speeds/languages beyond
the picker need service implementation or a read-only capability response; do not mistake UI normalization for server validation.

## 7. Sidebar, notify, drafting and collaborator toggles

**VERIFIED — contracts and state:** **S `methods.setAgentHiddenFromSidebar`, `methods.setAgentNotifyOnUpdates`,
`methods.setAgentDraftingDisabled`, `$defs.SandAgentSummary`; P `SetGrokBotAgentDraftingDisabledRequest|`,
`"SetGrokBotAgentDraftingDisabledResponse"`, `SetGrokBotAgentAllowCollaboratorAutomationCreationRequest|`,
`SetGrokBotAgentAllowCollaboratorAutomationCreationResponse|`, `GrokBotAgentRoutinePolicy|`**.

| Action | Request → reply; current state |
|---|---|
| setAgentHiddenFromSidebar | id:string,isHidden:boolean → null in S; row isHiddenFromSidebar?:boolean\|null (also isRemovedFromSidebar?:boolean\|null) |
| setAgentNotifyOnUpdates | id:string,isEnabled:boolean → null; row notifyOnUpdatesEnabled:boolean, distinct from notificationsEnabled:boolean |
| setAgentDraftingDisabled | id:string,isDisabled:boolean → null; row draftingDisabled?:boolean\|null |
| SetGrokBotAgentDraftingDisabled | id:string,disabled:boolean → empty response |
| SetGrokBotAgentAllowCollaboratorAutomationCreation | id:string,allow:boolean → `{routinePolicy?:{allowCollaboratorCreation:boolean,viewerAllowedActions:enum[]}}` |

Routine policy action values are UNSPECIFIED, CREATE, CHANGE_POLICY (**P `"GrokBotAutomationPolicyAction",[[`**).

**VERIFIED — reply caveat:** desktop's hidden-state adapter may return `{stateUpdatedAt:number}` or null, using the backend
client state's update timestamp, although S declares null. Handle that distinction as described by protocol-tui section 6's
client-state acknowledgements. Sources: **M `case"setAgentHiddenFromSidebar"`, `stateUpdatedAt:Number(a)`;
C `setAgentHiddenFromSidebar:{args:"object",reply:"client-state-write"}`**.

**VERIFIED — placement:** sidebar context menu offers hide/show; special nonowner team-default rows cannot be hidden by that menu.
Notify-on-updates is a switch in bot details/settings. Drafting choice is needs-approval versus disable-drafts and is offered only
for owned/non-group rows. Collaborator routine creation is in bot-manage Settings and the team setup flow; permissions can hold
the switch disabled. Its state comes from routine policy, including list-routines policy, not a gateway Agent field.
Sources: **R `function w0e(`, `function rQe(`, `function gm(`, `function FM(`, `function I5t(`, `function L5t(`;
A/chunk-bot-manage-screen-Tc2GjCk7.js `bot-manage-section-settings`;
A/chunk-team-bot-setup-flow-dialog-CwRrESLd.js `collaborator-automation-creation`;
M `function Cpt(`, `setCollaboratorCreation:"setGrokBotAgentAllowCollaboratorAutomationCreation"`**.
**UNKNOWN:** exact host behavior when drafting is disabled (beyond the UI choice), and authorization for arbitrary bots,
require producer code or captures. No mutation was performed.

## 8. Main agent

**VERIFIED:** main agent is a user-settings pointer to an existing bot, with a default-provisioning path and automatic pinning.
The UI loads it behind `sand_grok_main_agent`, compares the pointer to row IDs, and renders a main marker/accessibility label.
There is no isMainAgent/mainAgentId field on SandAgentSummary; isTeamDefault is a different concept.
Sources: **P `GrokBotUserRuntimeSettings|`; M `function k_t(`, `function T_t(`;
R `function cd(`, `function uUn(`, `isMain:a`, `function LVe(`; S `$defs.SandAgentSummary`**.

**VERIFIED — contracts:** `readMainAgentContext({id:string}) → {agentId:string,isWorking:boolean}`; despite its name it is not
instruction text or a transcript. `SetGrokBotMainAgent({agentId:string}) → {settings?:GrokBotUserRuntimeSettings}`;
`EnsureGrokBotDefaultMainAgent({}) → {agentId:string,outcome:enum}`. Outcomes are UNSPECIFIED=0, CREATED=1, PRESENT=2,
HAS_MAIN_AGENT=3, TOMBSTONED=4, PINNED_FULL=5, BUSY=6. The desktop normalizes settings to
`{agentId:string|null,ownerJobRole?:string}` and accepts created/present/hasMainAgent as successful ensure results.
Sources: **S `methods.readMainAgentContext`, `$defs.SandMainAgentContext`; P `SetGrokBotMainAgentRequest|`,
`SetGrokBotMainAgentResponse|`, `"EnsureGrokBotDefaultMainAgentRequest"`, `EnsureGrokBotDefaultMainAgentResponse|`;
M `function T_t(`; R `function Ake(`**.

Settings response field inventory: updatedAtMs:int64; pinnedAgents/sidebarSections/autoReviewInstructions/toolPermissions?:messages;
hasSeenOnboarding?:boolean; mainAgentId/jobRole?:string; termsSeenAtMs?:int64; emailProvider/xToolAccess:enums.
These are settings, not an Agent reply. Source: **P `GrokBotUserRuntimeSettings|`**.

**VERIFIED — UI restrictions:** delete-target filtering excludes the known current main ID; while pointer is unknown deletion
is disabled. For the current main row a replacement action can appear instead. Rename/edit has no main-agent exclusion in the
profile handlers. Hide-target filtering excludes team-default nonowner rows, not the main pointer, so this context menu can hide
an owned main row. Sources: **R `function Mke(`, `function E0e(`, `function rQe(`, `function wDn(`**.
**INFERRED:** owned main agents can be renamed/hidden through these ordinary UI actions; server acceptance is not established.
**UNKNOWN:** direct API deletion/hidden-main repair policy and the default bot's server-side purpose/persona require backend
source or a controlled capture; the UI protection alone does not establish a server prohibition.

## 9. Roster and opening

**VERIFIED:** `countAgents()` takes no args and returns number; `openAgent({id:string})` returns Entry[] (not an Agent wrapper).
Count is used by first-run gating to decide whether an account already has bots; the renderer prefers a ready server roster count
plus boxAgentCount and falls back to countAgents. Selection opens a bot and applies optimistic read acknowledgement; modern
transcript tail/window behavior is already in protocol-tui sections 3 and 6.
Sources: **S `methods.countAgents`, `methods.openAgent`; R `async function EPn(`, `function BPn(`,
`e.noteAgentOpenBegin?.(t`, `e.openAgent(t).then`**.

**VERIFIED — ListGrokBotAgents:** request `{role?:string,includeTeamAgents?:boolean,addedTeamAgentsOnly?:boolean}`;
reply `{agents:ServerAgent[],slackConnections:SlackConnection[],truncated:boolean,teamsConnections:TeamsConnection[]}`.
The ordinary server-roster adapter calls with empty args, keeps temporal agents and reports remaining count as boxAgentCount.
Team browsing's fallback calls with includeTeamAgents=true (a dedicated ListGrokBotTeamAgents path also exists).
Sources: **P `ListGrokBotAgentsRequest|`, `ListGrokBotAgentsResponse|`; M `let n=await t.listGrokBotAgents({}`,
`listGrokBotAgents({includeTeamAgents:!0}`**.
**UNKNOWN:** role accepted values and precise includeTeamAgents/addedTeamAgentsOnly interaction are not declared as enums or
demonstrated by these callers; no addedTeamAgentsOnly desktop call was identified. Settle with backend source or paired roster reads.

ServerAgent fields (VERIFIED, **P `GrokBotAgent|`**): id/legacyAgentId/name/description/title/avatarShape/avatarColor/agentId/harness/
role/viewerSessionId:string; createdAtMs/updatedAtMs:int64; memberAgentIds:string[]; teamDefaultForViewer:boolean; kind:enum;
avatarVersion/avatarUrl/ownerDisplayName/voiceId/voiceLanguage?:string; teamId?:number; voiceSpeed?:float;
viewerIsOwner/viewerCanManage/draftingDisabled/accessGrantsOnly/accessOwnerOnly?:boolean; visibility/viewerAccess?:enums;
people:RoomPerson[], publishedAt?:timestamp message, routinePolicy?:RoutinePolicy, viewerAllowedActions:enum[], suggestions:Suggestion[].
It lacks the gateway's run/unread/client overlay fields; normalization/merging is necessary, not `Bot.from_row` on protobuf JSON.
Repo `Bot` retains unknown row fields in raw but has no typed main-agent pointer, voice or drafting attributes; conversation.roster
currently reads listAgents. These repository observations are context, not bundle claims (see protocol-tui section 5).

SlackConnection: agentId:string,connected:boolean; workspaceName/installUrl/unavailableReason/reinstallUrl?:string;
pendingAdminApproval/needsManifestUpdate/approvalDenied/appUnreachable/removedInSlack/approvalRequestUnsent?:boolean.
TeamsConnection: agentId:string,installState:enum,tenantId/tenantDisplayName?:string,installedTeamCount:number,
installedTeams:installed-team message[]. Sources: **P `GrokBotSlackConnection|`, `GrokBotTeamsConnection|`**.

## 10. Gateway commands versus backend twins

Use protocol-m2 section 10 for the ordinary harness router. **VERIFIED exceptions matter for M3:** template import tries the
backend adapter first even before an agent exists; create resolves an account-scoped route; deletion splits IDs by harness.
An adapter declaration is not evidence that an ordinary owned box bot uses that adapter. Sources: **C `function n3(`,
`if(O==="createAgentFromTemplate")`, `if(Q.method==="createAgent")`, `if(O==="deleteAgents"&&"ids"in se)`**.

| Gateway command ↔ parity twin | Desktop choice for gateway-hosted/box bot; verdict and evidence |
|---|---|
| createAgent ↔ CreateGrokBotAgent / CreateGrokBotTemporalAgent | VERIFIED: box route dispatches gateway createAgent; temporal route invokes CreateGrokBotTemporalAgent. No direct CreateGrokBotAgent call found. C `let{avatarPngBase64:F,creationRoute:ue,...ae}=Q.args`; M `function lot(` |
| createAgentFromTemplate ↔ CreateGrokBotAgentFromTemplate | VERIFIED: backend-first; gateway only on unimplemented. Backend importer requires temporal result, not a box-targeted mutation. C `if(O==="createAgentFromTemplate")`; M `setupDelegationSupported:!0` |
| updateAgent ↔ UpdateGrokBotAgent | VERIFIED: ordinary owner uses gateway; nonowner managed serverId rows use direct backend identity update. R `function MWn(`, `function NGn(`; M `updateIdentity:async` |
| deleteAgents ↔ DeleteGrokBotAgent | VERIFIED: box IDs gateway; temporal IDs backend plus background gateway mirror cleanup. C `U=async(O,$)=>`; M `function vSt(` |
| setAgentVoice ↔ SetGrokBotAgentVoice | VERIFIED: box gateway, temporal direct backend (nonowner temporal writes suppressed). R `function dWn(`; M `setVoice:async` |
| setAgentDraftingDisabled ↔ SetGrokBotAgentDraftingDisabled | VERIFIED: ordinary box gateway; temporal backend action. C `function n3(`; M `case"setAgentDraftingDisabled"` |
| setAgentHiddenFromSidebar / setAgentNotifyOnUpdates ↔ SetGrokBotAgentClientState | VERIFIED: owned box gateway; temporal adapter writes hiddenFromSidebar/notifyOnUpdatesEnabled. Nonowner hiding uses desktop sidebar adapter. C `function n3(`; M `case"setAgentHiddenFromSidebar"`, `case"setAgentNotifyOnUpdates"`; R `setAgentHiddenFromSidebar:(t,r)=>` |
| getBotTemplateForSourceAgent ↔ GetGrokBotTemplateForSourceAgent | VERIFIED: source harness routes it; ordinary box source gateway, temporal source backend. C `case"getBotTemplateForSourceAgent":return n.args.sourceAgentId`; M `getForSourceAgent:async` |
| getBotTemplateVersion ↔ GetGrokBotTemplateVersion | VERIFIED: mapped shareId belonging to temporal source uses backend; otherwise gateway. C `c=O=>{switch(O.method)`, `l.set($,j)`; M `getVersion:async` |
| getBotTemplateExportPolicy ↔ GetGrokBotTemplateExportPolicy | VERIFIED: backend when coordinator knows any temporal IDs, otherwise gateway. C `case"getBotTemplateExportPolicy":return(n.temporalAgentIds`; M `getExportPolicy:async` |
| duplicateAgent ↔ DuplicateGrokBotAgent; listBotTemplates ↔ ListGrokBotTemplates | UNKNOWN desktop choice: declarations only; no invocation found. S `methods.duplicateAgent`, `methods.listBotTemplates`; P named RPC requests/responses |

No direct parity backend twin was identified for kickstartAgent, seedConversationName, getAgentAvatar, setAgentAvatarBytes,
generateAgentAvatarImage, previewVoice, readMainAgentContext, countAgents or openAgent. Avatar editing can instead use direct
UpdateGrokBotAgent for managed nonowner rows, and desktop generation is a separate image service (sections 3/5).
Main-agent set/ensure and collaborator policy are backend operations in their own right, not evidence for a missing gateway twin.

Remaining gaps are explicitly marked UNKNOWN in their numbered sections, with the producer source/capture that would settle
them. No read-only live call could by itself prove deletion or creation side effects; those require authorized controlled captures.
