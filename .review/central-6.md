# Central-6 planned-row triage

Offline triage of all 43 planned rows: M4 26, M1 6, M2 6 and M3 5. Every status stays planned. Group (a) can be built against fakes from documented contracts; group (b) needs owner evidence or an account/credential action; group (c) should be declined or handed to the app.

Searched every name recursively in docs and gbot. Git grep failed with Windows error 5, so rg supplied the per-name results. Checked nearby service implementations for existing behavior; no live API, CLI, token store or app bundle was accessed. These are implementation recommendations, not claims of live compatibility. The group-document asset-link concern is inferred from its expiry-bearing URL fields. The attachment resolver reference documents only the nearby lower-case adapter, not the exact planned RPC. The normalized template command can be faked without exposing the raw backend temporary link.

The Windows checkout used CRLF; the required Python serializer writes UTF-8 with LF. Restoring the old notes reproduces the original text exactly after newline normalization; no other JSON fields or rows changed.

| name | milestone | area | group | reason | doc reference |
| --- | --- | --- | --- | --- | --- |
| completeGithubConnect | M4 | channels | (b) | Completing the source-control connection needs the owner to supply a real OAuth callback and installation decision. | docs/protocol-m4b.md:132 |
| completeMcpOAuth | M4 | connectors | (b) | Completing connector OAuth consumes sensitive callback credentials and needs the owner to finish sign-in. | docs/protocol-m4a.md:68 |
| countAgents | M1 | roster | (a) | The no-argument request and numeric reply are documented and can be tested with a fake roster count. | docs/protocol-m3.md:294 |
| getAutomationWebhookCredential | M4 | automations | (b) | This can mint and return a secret bearer key, so the owner must check credential handling. | docs/protocol-m4a.md:295 |
| getBotTemplateVersion | M3 | templates | (a) | The normalized recipe reply and download mapping are documented, so fake transport and recipe data can cover it. | docs/protocol-temporal.md:122 |
| getMcpPluginLogo | M4 | connectors | (c) | Logo resolution serves app presentation, and its gateway record fields are still unknown; leave it to the app. | docs/protocol-m4a.md:25 |
| getPluginSyncStatus | M4 | plugins-skills | (b) | The owner needs to capture a populated blocked-status reply because its item fields are still unknown. | docs/protocol-m4a.md:180 |
| openAgent | M1 | roster | (a) | The documented entry-array reply can reuse transcript parsing and fake the read acknowledgement side effect. | docs/protocol-m3.md:294 |
| promptAcceptanceStatus | M1 | conversation | (a) | The documented send-status mapping supports fake accepted, rejected, pending and missing cases. | docs/protocol-temporal.md:31 |
| refreshMcp | M4 | connectors | (b) | The refresh reply is unknown and completion can follow account sign-in, so it needs an owner-authorized capture. | docs/protocol-m4a.md:26 |
| runAutomationWebhook | M4 | automations | (b) | Running a webhook can first mint a bearer key, so the owner must check the credential and execution path. | docs/protocol-temporal.md:108 |
| seedConversationName | M3 | bots | (a) | The prompt request and kept-or-seeded reply are documented and can reuse bot parsing with fakes. | docs/protocol-m3.md:31 |
| setBoxSecrets | M4 | secrets-vault | (a) | The replacement map and status-only reply are documented, so fake values can test writes without revealing stored secrets. | docs/protocol-m4b.md:179 |
| syncPluginSkills | M4 | plugins-skills | (b) | The sync result item fields are unknown and syncing changes state, so the owner needs to capture an authorized run. | docs/protocol-m4a.md:180 |
| AddGrokBotAgentSkill | M4 | plugins-skills | (a) | The skill fields and response envelope are documented and fit the existing skill and plugin projections. | docs/protocol-m4a.md:168 |
| AttachGrokBotAgentDelegatedCredential | M4 | plugins-skills | (b) | Attaching delegated account access needs the owner to choose the account and acknowledge its warning. | docs/protocol-m4a.md:170 |
| BatchCreateGrokBotVaultCredentials | M4 | secrets-vault | (b) | Bulk login creation returns credential records, so the owner must check the import and redaction behavior. | docs/protocol-m4b.md:213 |
| BeginOnePasswordConnection | M4 | secrets-vault | (b) | Starting this connection consumes a service-account token and returns a sensitive mint ticket. | docs/protocol-m4b.md:248 |
| CompleteOnePasswordConnection | M4 | secrets-vault | (b) | Completing the connection consumes a mint ticket and service-account token and requires the owner account. | docs/protocol-m4b.md:249 |
| CompleteOnePasswordOAuth | M4 | secrets-vault | (b) | Completing password-manager OAuth requires the owner browser callback and its sensitive state and code. | docs/protocol-m4b.md:251 |
| EnsureSandBox | M1 | internal | (c) | gbot already reaches it through groken's GatewayManager (groken/gateway.py:718), which mints the gateway session; no separate surface is needed. Changed from (b) in review. | docs/protocol-tui.md:275 |
| GetGrokBotSendStatus | M1 | conversation | (a) | The documented request mapping and delivery outcomes can be faked without sending a real message. | docs/protocol-temporal.md:31 |
| GetGrokBotTemplateVersion | M3 | templates | (b) | The raw backend reply returns a secret temporary recipe link, so the owner must check download and redaction handling. | docs/protocol-m5b.md:51 |
| GetGrokBotUserMcpSettings | M4 | connectors | (a) | The empty request and settings fields are documented and fit the existing connector settings service. | docs/protocol-m4a.md:20 |
| ListGrokBotAgentRoutines | M4 | automations | (a) | Routine fields and policy are documented, so fakes can cover both routine lists and the observed unsupported-account error. | docs/protocol-m4a.md:306 |
| ListGrokBotAgentSessions | M2 | conversation | (a) | The session list fields, kinds and timestamps are documented and can be tested as routing contexts. | docs/protocol-tui.md:157 |
| NudgeOnePasswordAccessRequest | M4 | secrets-vault | (a) | The access-request reminder takes three references and returns a boolean, so fake success and failure need no credentials. | docs/protocol-m4b.md:255 |
| PutGrokBotVaultItem | M4 | secrets-vault | (b) | The call returns a credential record and its accepted secret-field keys are unknown, so the owner must check the contact-write path. | docs/protocol-m4b.md:214 |
| ReadGrokBotAgentAttachmentChunk | M2 | conversation | (b) | Only conditional backend routing is documented; the owner needs to verify its reply before reusing gateway chunk parsing. | docs/protocol-m2.md:363 |
| ReadGrokBotGroupChatDocument | M2 | rooms | (b) | The reply includes expiring asset links, so the owner should check whether they grant access before exposing them. | docs/protocol-m2.md:213 |
| RemoveGrokBotAgentDelegatedCredential | M4 | plugins-skills | (b) | Revoking delegated account access returns potentially sensitive plugin configuration and needs an owner account check. | docs/protocol-m4a.md:170 |
| RemoveGrokBotAgentSkill | M4 | plugins-skills | (a) | The skill-name request and plugin response envelope are documented and can use fake skill removal results. | docs/protocol-m4a.md:168 |
| ResolveGrokBotAttachmentReads | M2 | conversation | (b) | The exact RPC name is not in our protocol notes; the nearby signed-link resolver needs an owner check of its request and secret reply. | docs/protocol-m2.md:363 |
| SearchGrokBotPlacesArea | M2 | search | (a) | The map bounds, card context and outcome enum are documented and can be tested with fake places cards. | docs/protocol-m2.md:139 |
| SendGrokBotUserMessage | M1 | conversation | (a) | The field mapping and acceptance outcomes are documented, so fakes can cover sending and duplicate handling. | docs/protocol-temporal.md:30 |
| SetGrokBotAgentAllowCollaboratorAutomationCreation | M3 | bots | (a) | The boolean update and routine-policy reply are documented and can be tested with fake permission results. | docs/protocol-m3.md:243 |
| SetGrokBotAgentRoutineEnabled | M4 | automations | (a) | The routine toggle request and optional routine reply are documented and can reuse fake automation permission cases. | docs/protocol-m4a.md:306 |
| SetGrokBotUserMcpSettings | M4 | connectors | (a) | The settings update and keep-disabled-tools flag are documented and can be tested alongside connector settings reads. | docs/protocol-m4a.md:112 |
| StartGrokBotImagePrecaption | M2 | conversation | (c) | This name is not in our protocol notes and its planned purpose is a message-composer aid, so leave it to the app. | none |
| StartOnePasswordOAuth | M4 | secrets-vault | (b) | Starting password-manager OAuth returns sensitive authorization state and requires the owner browser consent flow. | docs/protocol-m4b.md:250 |
| StoreOnePasswordIntegrationKey | M4 | secrets-vault | (b) | Storing an integration key consumes a secret from the owner OAuth callback and binds the connection. | docs/protocol-m4b.md:252 |
| UpdateGrokBotAgent | M3 | bots | (a) | The partial identity update and avatar oneof are documented, so fakes can cover managed nonowner rows. | docs/protocol-m3.md:147 |
| UpdateGrokBotAgentSkill | M4 | plugins-skills | (a) | The skill-name and content update plus response envelope are documented and fit existing skill projections. | docs/protocol-m4a.md:168 |

Counts: (a) 20; (b) 20; (c) 3. Total: 43.

Suggested group (a) batch order by area, smallest first (row count; ties alphabetical):

1. search (1): SearchGrokBotPlacesArea.
2. templates (1): getBotTemplateVersion.
3. automations (2): ListGrokBotAgentRoutines, SetGrokBotAgentRoutineEnabled.
4. connectors (2): GetGrokBotUserMcpSettings, SetGrokBotUserMcpSettings.
5. roster (2): countAgents, openAgent.
6. secrets-vault (2): setBoxSecrets, NudgeOnePasswordAccessRequest.
7. bots (3): seedConversationName, SetGrokBotAgentAllowCollaboratorAutomationCreation, UpdateGrokBotAgent.
8. plugins-skills (3): AddGrokBotAgentSkill, RemoveGrokBotAgentSkill, UpdateGrokBotAgentSkill.
9. conversation (4): promptAcceptanceStatus, GetGrokBotSendStatus, ListGrokBotAgentSessions, SendGrokBotUserMessage.

All rows have a decision. Group (b) records the remaining owner checks; no such check was performed in this unit.

Review (main session): accepted with one change, EnsureSandBox moved from (b) to (c). setBoxSecrets stays (a): build it against fakes only, its CLI verb needs --yes, and it never prints a value.
