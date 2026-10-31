# M5 read-only live captures (2026-10-31)

Read-only calls against the owner's account: a personal account with no team, every bot backend-hosted. Only reply
*shapes* were recorded: key names, types, list lengths and enum-like values. No names, ids, prompts, addresses or
credentials were kept. These replies complement `protocol-m5a.md`, `protocol-m5b.md` and `protocol-m5c.md`; where a
live reply and a bundle reading disagree, the live reply describes what the server sends today. INFERRED marks an
interpretation of a shape, not an observation.

## Ids and empty replies

- `GetGrokBotAgentAccess` and `ListGrokBotAgentManagers` accept both the gateway agent id and the backend id in
  `agentId` and return the same shape. Send the gateway id, as for the other backend reads in `protocol-m4-live.md`.
- An empty repeated field is omitted, so an empty list arrives as `{}`.
- Refusals arrive as Connect errors with a code (`permission_denied`, `failed_precondition`, `not_found`,
  `invalid_argument`); some carry a readable message meant for the user. Show that message as a plain notice.

## This account

- No team: `ListGrokBotTeamAgents {}` → `{}`, and `getSkillPublishTargets` → `{teams: [], unavailableReason: string,
  unavailableReasonKind: string}`. Show `unavailableReason` instead of an empty target list.
- Team-only reads refuse with `permission_denied` and a readable message: `GetGrokBotTeamContextSummary` (only a bot
  shared with a team has a summary) and `ListGrokBotUserBotMemories` (only the owner or a manager of a team bot can
  share memories with the team). So the memory list in M5 is the team-sharing list, not a general memory browser.
- `ListGrokBotAgentAccessInvites {agentId}` → `failed_precondition` (INFERRED: invites need a team).

## Sharing and access

- `GetGrokBotAgentAccess {agentId, listsCrossTierPrincipals: true}` → `{creatorUserId: int, viewerUserId: int,
  state: {availableRoles: string[2], expectedStateToken: string, principals: [{role: string, team: {}}],
  teamRowOn: bool, teamRowOffAllowed: bool}}`. Roles arrive as full enum names (`GROK_BOT_ACCESS_ROLE_…`).
  `expectedStateToken` is opaque; INFERRED: it is sent back with an update so a stale dialog cannot overwrite a newer
  change.
- `GetGrokBotAgentLinkAccess {agentId}` → `{access: string}`, a full enum name (INFERRED from its length: `…_ALLOWED`).
- `ListGrokBotAgentManagers {agentId}` → `{}` (no managers).
- `GetGrokBotAgentInPlaceShareStatus {agentId}` → `not_found` when no share has been started.
- `ListGrokBotTeamReviewItems {agentId, limit: 1}` → `invalid_argument` (INFERRED: `statuses` is required).

## Publishing

- `ListGrokBotTemplates {}` → `{exportPolicy: string}` with no `templates` key (the owner has none). INFERRED from its
  length: `all`.
- `listCloudAgentPublishedApps` → `{kind: "off"}`: cloud-agent apps are switched off for this account.

## Memories, files and settings

- `ListGrokBotLibraryDocs`, `ListGrokBotLibraryPins`, `ListGrokBotAgentFiles {agentId, pageToken: ""}` and
  `ListGrokBotUserStoreFiles` → `{}` (none yet).
- `GetGrokBotUserRuntimeSettings {}` → `{settings: {autoReviewInstructions: {isEnabled: bool}, emailProvider:
  string, hasSeenOnboarding: bool, mainAgentId: string, pinnedAgents: {agentIds: string[]}, sidebarSections: {},
  updatedAtMs: string}}`.
- `GetSandBoxRunState {}` → `{state: "SAND_BOX_RUN_STATE_RUNNING", image: {registryTag: string, staticSnapshotPath:
  string}, imageUpdateAvailable: bool, egressTunnelOwnership: bool}`.
- `GetSandBoxUpgradeSchedule {}` → `invalid_argument` (INFERRED: it needs an argument the notes do not name yet).
- `GetGrokBotEgressPolicy {}` → `{}` (INFERRED: no restriction set).
- `GetGrokBotAgentAnalytics {agentId}` → `not_found` for the bot tried (INFERRED: no analytics recorded yet).
- `GetGrokBotDefaultPaymentMethod {}` → `{}` (no default payment method).
