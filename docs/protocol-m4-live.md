# M4 read-only live captures (2026-10-31)

Read-only calls against the owner's account, all 14 non-group bots backend-hosted. Only reply *shapes* were
recorded: key names, types, list lengths, and enum values. No names, prompts, addresses or credentials were
kept. These replies complement `protocol-m4a.md` and `protocol-m4b.md`; where a live reply and a bundle reading
disagree, the live reply describes what the server sends today.

## Ids

- Backend reads keyed by `agentId` take the **gateway** agent id. The backend id is refused with
  `invalid_argument` by `ListGrokBotAgentAutomations`, `ListGrokBotAgentRoutines` and `ListGrokBotSubagents`.
- `ListGrokBotSecrets` takes the backend id in `id` and returns `{}` when the bot has no secrets.
- An empty repeated field is omitted, so an empty list arrives as `{}`.

## Connectors

- `getMcpCatalog` → a list of about 490 catalog plugins. Each has `id`, `name`, `displayName`, `pluginName`,
  `description`, `category` (such as `Featured`), `categoryKey`, `categoryKeys[]`, `iconUrl`, `repositoryUrl`,
  `isPublicListed`, `popularityRank`, `publisher {name, displayName, isUserOwned}`, `connectors[] {name,
  description}`, and `fields[]` for setup. A setup field has `key`, `label`, `hint`, `placeholder`, `type`
  (`string` seen), `isRequired`, `isSecret` and optional `options[] {label, rawValue}`.
- `getMcpState` → `{servers[]}`. A server has `id`, `name`, `serverIdentifier`, `rowServerIdentifier`,
  `pluginId`, `pluginDisplayName`, `pluginTeam`, `isTeamServer`, `accountKey`, `credentialIsCursorAccount`,
  `cursorScmProvider`, `customInstructions`, `command`, `url`, `transport`, `servedBy`, `toolCount`, `status`
  (`connected` seen) and `statusDetail {kind}` (`authentication_required` seen). The account had 14 servers.
- `GetGrokBotUserMcpSettings` → `{settings {autoReviewInstructions {isEnabled}, updatedAtMs, userTimeZone}}`; no
  per-server rows on this account.
- `GetGrokBotConnectorSharedSpaceAllowlist` → `{}` (empty allowlist).

## Plugins and skills

- `skillsCatalog` → a list of about 1,900 skills with `id`, `name`, `description`, `publisher`, `iconUrl`,
  `source` (`marketplace`) and `install {kind, url}` (`url` seen).
- `getPluginSyncStatus` → `{authBlocked[]}`.
- `GetGrokBotAgentPlugins {agentId, includeMcpConfig:false}` → `{customMcpPerUser, serviceAccountsEnabled}` for a
  bot with no plugins.
- `ListGrokBotAgentSkills` → `{}` for a bot with no skills.

## Automations, workflows and routines

- `ListGrokBotAccountAutomations {agentIds[]}` → `{agents[] {agentId, automations[]}}`; every bot had one or two
  automations. `ListGrokBotAgentAutomations {agentId}` returns the same per-bot rows without needing `timeZone`.
- An automation row is `{automationId, recordJson, viewerPermissions {allowedActions[]}}`. Allowed actions are
  enum names: `GROK_BOT_AUTOMATION_ACTION_OPEN`, `_EDIT`, `_TOGGLE`, `_DELETE`.
- `recordJson` is a JSON string. Its object has `id`, `name`, `prompt`, `isEnabled`, `createdAt`, `lastRunAt`,
  `nextRunAt`, `runs[]`, `provenance`, `filePath`, `schedule`, `triggerDescription`, `trigger {type, schedule}`
  (type `cron` seen) and `triggerPresentation {version, trigger}`.
- The gateway's `getAgentAutomations` and `listAllAutomations` return `[]` for these bots: for backend-hosted bots
  the backend lists are the source of truth.
- The gateway's `getAgentWorkflows {id}` returned about 140 rows for a backend-hosted bot, each with `id`, `name`,
  `description`, `body` (Markdown), `filePath`, `source` (`managed`), `sourceRef`, `pluginId`, `trigger`,
  `scheduleDescription`, `lastRunAt`, `nextRunAt`, `runs[]`, `helperScripts[]`, `createdAt` and
  `publishedByCurrentUser`.
- `ListGrokBotAgentRoutines {agentId}` → `not_found` on this account.

## Channels, inboxes and vault

- `GetGrokBotSlackInstallState`, `GetGrokBotTeamsInstallState` and `ListGrokBotTeamsJoinedTeams` →
  `not_found` with either id: nothing installed here, so treat `not_found` as "not installed".
- `GetMicrosoftTeamsAccountLinkStatus` → `{}`.
- `GetGrokBotMessagingLinkStatus` and `ListGrokBotMessagingLinkedPhones` → `permission_denied` with the message
  that texting a bot is not available yet. Show that message instead of an error.
- `getListenerIntegrations` → `{integrations[] {platform, state, isConnected, neededByCount}}` (`idle` seen,
  6 platforms).
- `ListGrokBotEmailInboxes`, `ListGrokBotVaultCredentials`, `GetOnePasswordState` and `ListPasskeys` → `{}`.
- `getBoxSecretsStatus` → `{keys[], cardKeys[], isApplied, lastAppliedAtMs}`; names only, never values.

## Desktop computer

- `getForeverBoxStatus {id}` → `{agentId, state, handoff, hostVersion, hostUpdateAvailable,
  imageUpdateAvailable, vncUrl}`; state `absent` seen, with `handoff` and `vncUrl` null.
