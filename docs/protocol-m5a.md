# M5a protocol research: sharing, access and team features (desktop 0.77.0)

Offline bundle inspection of the extracted desktop bundle, read-only. No live service, private configuration or credential file was read, and no RPC was called. VERIFIED means client or declaration code establishes the claim (citation given). INFERRED marks interpretation beyond the code. UNKNOWN means the inspected material did not establish the detail, not that a feature is absent. This file does not prove deployed server behaviour. Conventions follow protocol-m4a: `?` optional, `[]` repeated, int64 values are decimal strings in protobuf JSON. **Secret** marks credentials (invite codes, invite URLs, consent URLs with state). **Personal** marks emails, names, user ids and user-written text.

Cross-references (not repeated here): protocol-m3 section 10 (gateway commands versus backend twins), protocol-temporal section 7 (team agent merge and the ListGrokBotTeamAgents fallback), protocol-m4b section 11 (browser handoff rows for Teams) and section 12 (events, `server-roster-changed`), protocol-tui section 1 (SSE `/events`), protocol-m4-live (live id-form caveat; no M5 RPC was captured live).

Citation keys: **P** = `dist/electron-main/proto.cjs`; **M** = `dist/electron-main/main-app.cjs`; **K** = `dist/electron-main/main-core.cjs`; **C** = `dist/node-agent-coordinator/main.cjs` (gateway; carries the same generated classes); **R** = `dist/renderer/assets/index.eager-app-BtIHj2If.js`; **U** = `dist/renderer/assets/chunk-use-bot-sharing-DrYLQw9N.js`; **G** = `dist/renderer/assets/chunk-team-bot-manager-alerts-DvY4Ytb9.js`; **S** = `dist/renderer/assets/chunk-bot-share-popover-Cnb8HivM.js`; **V** = `dist/renderer/assets/chunk-bot-share-invite-popover-CWzOgG2W.js`; **I** = `dist/renderer/assets/chunk-agent-invite-dialog-DJVg-u8g.js`; **F** = `dist/renderer/assets/index.eager-platform-BCmdOJdH.js`. Each citation gives a searchable string.

## 0. Service, call path and id keys

**VERIFIED service:** every RPC in sections 1 to 7 is a method of `aiserver.v1.GrokBotService` (P `typeName:"aiserver.v1.GrokBotService"`, method table that follows it). The team directory reads in section 8 (`GetTeams`, `GetTeamMembers`) belong to `aiserver.v1.DashboardService` (P `typeName:"aiserver.v1.DashboardService"`).

**VERIFIED call path:** the renderer does not call the backend. It calls desktop IPC methods (R `e.desktop.updateGrokBotAgentAccess`), which main handles (M `updateAccess:async(y,{entries:h`). Main builds a Connect client for GrokBotService with its backend client factory (M `function Wut(e,t=()=>de(A.GrokBotService,e)`; M `function de(e,t)`). So every row below is renderer → IPC → main process → backend GrokBotService. The gateway bundle (C) holds the same message classes and a GrokBotService method table but no handler text for these methods, so no gateway routing is shown; gateway routing is **UNKNOWN**. The preload bridge also carries the names (electron-preload/preload.cjs, name only).

**VERIFIED id keys:** main passes the IPC key straight through as the RPC `agent_id` or `team_id`. Access, invite and manager calls are keyed by `serverId` (M `getAccess:async y=>`, `listInvites:async y=>`, `listManagers:async y=>`, and the IPC table entries `getGrokBotAgentAccess:({serverId:d})`). Visibility, link access, in-place share, clone, team context, promote and review calls are keyed by `agentId` (M `setVisibility:async(y,h,S)`, `linkAccess:async y=>`, `cloneGrokBotAgentToTeam:async({agentId:d,offerEntryId:c})`). Link preview is keyed by `teamId` (M `teamLinkPreview` get/set). Invite preview and accept are keyed by the invite `code` plus `agentId` (R `previewGrokBotAgentInvite:En().args({code:wy,agentId:Ty()})`). **INFERRED:** `serverId` and `agentId` may be different id forms; protocol-temporal section 7 maps backend `agentId` to logical agent and `id` to `serverId`. Settle with one read-only capture per form before the TUI relies on either.

## 1. Access: GetGrokBotAgentAccess, UpdateGrokBotAgentAccess

**VERIFIED request/reply shapes (P `GetGrokBotAgentAccessRequest|1 agent_id 9|2 lists_cross_tier_principals 8`; P `GetGrokBotAgentAccessResponse|1 state #0|2 creator_user_id 5|3 deleted_group_ids 3*|4 cross_tier_directory #1|5 viewer_user_id 5|6 bot_team_directory #2|7 personal_bot_people #3*`).**
- `GetGrokBotAgentAccessResponse.state` is `GrokBotAgentAccessState`: `principals` (repeated `GrokBotAccessPrincipal`), `team_row_on` (bool), `available_roles` (repeated `GrokBotAccessRole`), `expected_state_token` (string, optimistic-concurrency token), `groups_enabled`, `team_row_off_allowed`, `cross_team_sharing_enabled`, `caller_may_edit_cross_team_rows` (bools). P `GrokBotAgentAccessState|1 principals #0*`.
- `creator_user_id` is an int32 **Personal** id of the bot owner; `viewer_user_id` is the caller's **Personal** id.
- `deleted_group_ids` lists groups that no longer exist (int64).
- `cross_tier_directory` (organization name, optional icon, teams); `bot_team_directory` (one team entry, people, groups with member counts); `personal_bot_people` (user id and name). Names are **Personal**.
- `GrokBotAccessPrincipal` is a oneof with `team` (empty message, whole team), `user_id` (int32), `group_id` (int64), `other_team_id` (int32), `organization` (empty message, whole organization), plus `role` (`GrokBotAccessRole`) and `invited_as_email` (string, optional, **Personal**). P `GrokBotAccessPrincipal|1 team #0 principal`. The principal kinds are therefore team, user, group, other team and organization. There is no email or domain kind in the oneof; an email appears only as `invited_as_email`. P `GrokBotAccessTeamPrincipal`, `GrokBotAccessOrganizationPrincipal` (both empty).
- `GrokBotAccessRole` enum: UNSPECIFIED, USER, MANAGER. P `"GrokBotAccessRole",[[0,"UNSPECIFIED"],[1,"USER"],[2,"MANAGER"]]`.
- `UpdateGrokBotAgentAccessRequest`: `agent_id`, `update` (`GrokBotAgentAccessUpdate`: `principals` [], `expected_state_token`, `lists_cross_tier_principals`). Reply: same shape as the Get reply. P `GrokBotAgentAccessUpdate|1 principals #0*`.
- The desktop sends `lists_cross_tier_principals` true on reads (M `getAccess:async y=>{let h=await o().getGrokBotAgentAccess({agentId:y,listsCrossTierPrincipals:!0}`) and sends the whole principal list with the token on update (M `updateAccess:async(y,{entries:h,expectedStateToken:S})`).
- Entries the renderer builds: kinds `team`, `user` (with user id), `group` (with group id), `other_team` (with team id), `organization`, each with a role of `user` or `manager` (R `var joe=[\`user\`,\`manager\`]`; R `kind:Wn(\`other_team\`)`).

**VERIFIED share dialog layout (U, G, S):** the state is mapped to a list with the owner row first (G builds `{kind:'owner', userId: creatorUserId}`), then the principal rows. The renderer maps principal role `manager` to a manager label, `user` to a collaborator label, and anything else to viewer; the order is viewer < collaborator < manager (U `je={viewer:0,collaborator:1,manager:2}`). A team row can be set on or off (G `case\`set-team-row\``). Turning the team row off is not offered when no other row would remain and the server's `team_row_off_allowed` flag is false. Setting the team row to manager asks for a confirmation (G `confirm:t.role===\`manager\`?\`team-manager-add\``). A general-access summary is derived from organization and everyone kinds (U `e.generalAccess.kind===\`everyone\``). Candidate people, groups and organization come from the directory fields of the reply. The owner is implicit: it is not a stored principal, and the share state is non-default when the team row is on or a non-user row or a user row other than the creator exists (R `function Gl(e){return e.teamRowOn||`).

**VERIFIED what changes:** Update changes access (write). Get is read-only.

**VERIFIED what the app asks first:** before adding a team-wide manager it shows a confirmation (G). Other additions and removals are made from the share popover; the bundle shows no further confirmation step for them (strings are localized IDs, so wording is **UNKNOWN**; locale files are in `electron-main/locales`).

**UNKNOWN:** what USER and MANAGER allow on the server. The client only labels them. **INFERRED:** the team row and organization principals are the grant paths that make a bot visible beyond the owner.

## 2. Visibility and link access

**VERIFIED visibility (P `SetGrokBotAgentVisibilityRequest|1 agent_id 9|2 visibility #0|3 personal_secret_names 9*`; P `"GrokBotAgentVisibility",[[0,"UNSPECIFIED"],[1,"OWNER"],[2,"TEAM"]]`).** `visibility` is OWNER or TEAM. The reply is `SetGrokBotAgentVisibilityResponse|1 agent #0|2 outcome #1` with outcome UPDATED, UNSUPPORTED_HARNESS, NO_TEAM or BUSY (P `SetGrokBotAgentVisibilityOutcome`). Only UPDATED carries the agent (M `setVisibility:async(y,h,S)` maps it to `updated`). The desktop only ever sends TEAM here (M `visibility:A.GrokBotAgentVisibility.TEAM`). **UNKNOWN:** the call that returns a bot to OWNER.

**VERIFIED personal secrets:** `personal_secret_names` is a repeated string list of secret names the user chose to carry (M `personalSecretNames:[...S?.personalSecretNames??[]]`). **INFERRED:** named personal secrets become team secrets when the bot goes to a team; the carry-over behaviour on the server is **UNKNOWN**.

**VERIFIED link access (P `GetGrokBotAgentLinkAccessResponse|1 access #0`; P `"GrokBotAgentLinkAccess",[[0,"UNSPECIFIED"],[1,"ALLOWED"],[2,"NO_ACCESS"],[3,"NOT_FOUND"]]`).** The reply holds one enum value and nothing else. It does not hold a link, a code or a token, so it grants nothing by itself and no field needs **Secret** marking. The desktop maps ALLOWED to `allowed`, NO_ACCESS to `no_access`, NOT_FOUND to `not_found` (M `function VQn(e){switch(e){case A.GrokBotAgentLinkAccess.ALLOWED`). **UNKNOWN:** what ALLOWED opens to, and whether the bundle ever creates a link-access change (no RPC for that is listed in the M5 set).

**VERIFIED relation:** the access list (section 1) decides who holds the bot; visibility TEAM and the team row are the two team-level switches. **INFERRED:** visibility TEAM corresponds to a team-visible grant; the bundle does not state the mapping.

**VERIFIED what changes:** SetGrokBotAgentVisibility writes. GetGrokBotAgentLinkAccess reads. Neither is a credential.

## 3. Invites

**VERIFIED invite object (P `GrokBotAgentAccessInvite|1 email 9|2 expires_at_ms 3|3 last_shared_at_ms 3|4 created_at_ms 3`).** The list object has no id, no role and no status. `email` is **Personal**. Invites are addressed by email in the revoke call, not by id.

**VERIFIED create (P `CreateGrokBotAgentAccessInviteRequest|1 agent_id 9|2 email 9|3 send_email 8|4 language 9?`; P `CreateGrokBotAgentAccessInviteResponse|1 invite #0|2 invite_created 8|3 invite_url 9|4 grace_ms 3|5 cap_usage #1|6 invite_email_sent 8`).** Reply: `invite`, `invite_created`, `invite_url` (**Secret**: it carries the invite code), `grace_ms` (int64), `cap_usage` (`GrokBotInviteCapUsage`: `used`, `limit`, int32), `invite_email_sent`. Changes data: yes. The desktop shows the URL in a popover with the email, expiry, a re-share flag and the grace period, and shows the URL without opening it (V `kind:\`link\`,email:n.invite.email,inviteUrl:n.inviteUrl,expiresAtMs`). **INFERRED:** `grace_ms` covers a re-share of the same invite; the exact rule is UNKNOWN.

**VERIFIED list (P `ListGrokBotAgentAccessInvitesResponse|1 invites #0*|2 cap_usage #1`).** Read-only. Entries are invite objects (section 3 above, **Personal** emails).

**VERIFIED revoke (P `RevokeGrokBotAgentAccessInviteRequest|1 agent_id 9|2 email 9`; P `RevokeGrokBotAgentAccessInviteResponse|1 revoked_count 5|2 cap_usage #0`).** Writes. Keyed by email (**Personal**).

**VERIFIED preview (P `PreviewGrokBotAgentAccessInviteRequest|1 code 9`; P `PreviewGrokBotAgentAccessInviteResponse|1 found 8|2 recipient_match #0|3 sender #1|4 invites #2*|5 truncated 8|6 other_resource_invite_count 13|7 eligibility #3`).** Read-only, but `code` is **Secret**. Reply: `found`; `recipient_match` (MATCHES, DOES_NOT_MATCH, UNKNOWN; P `GrokBotAgentAccessInviteRecipientMatch`); `sender` (display name, avatar; **Personal**); `invites` items with `invite_id`, `bot` (agent id, name, avatar fields), `role` (string), `state` (OPEN, ACCEPTED, EXPIRED, REVOKED, UNAVAILABLE, NOT_SHAREABLE; P `GrokBotAgentAccessInviteState`), `expires_at_ms`; `eligibility` (`eligible`, `reason` from NO_SUBSCRIPTION, TIER_NOT_ELIGIBLE, NOT_INDIVIDUAL, SUBSCRIPTION_NOT_ACTIVE, and `current_tier` from NONE, PLUS, PREMIUM, SUPER, ULTRA). The app's dialog has bot, sender, ineligible, invalid and not-eligible states (I `case\`ineligible\``). The request carries only `code`; the app's `agentId` argument is not sent to the RPC (M `previewInvite:async({code:y,agentId:h})`).

**VERIFIED accept (P `AcceptGrokBotAgentAccessInviteRequest|1 code 9`; P `AcceptGrokBotAgentAccessInviteResponse|1 status #0|2 items #1*|3 truncated 8|4 other_resource_invite_count 13|5 eligibility #2`).** Writes (grants access). `code` is **Secret**. `status`: UNSPECIFIED, REDEEMED, INVALID_CODE, RECIPIENT_MISMATCH, NOT_ELIGIBLE, TRY_AGAIN (P `GrokBotAgentAccessInviteAcceptStatus`). Items: `invite_id`, `bot`, `role`, `outcome` (GRANTED, ALREADY_HELD, ALREADY_ACCEPTED, ACCEPTED_BY_SOMEONE_ELSE, EXPIRED, REVOKED, NOT_IN_CODE, NOT_GRANTABLE, TRY_AGAIN; P `GrokBotAgentAccessInviteAcceptOutcome`). The dialog shows the result and an accept action (I `agent-invite-accept`).

**VERIFIED where the user gets the input:** a deep link. The app's custom-scheme router has an `agent-invite` route under `/v1/agent-invite` with an agent `id` and a `token` of up to 1024 characters (K `"agent-invite":Ue(EG,{id:K(Oc),token:K({maxDecodedLength:$ue})})`). The token is the invite code. The renderer reads it and calls preview with `code` set to the token and `agentId` set to the id (R `previewGrokBotAgentInvite({code:t.token,agentId:t.agentId})`). **UNKNOWN:** whether the desktop accepts a pasted invite URL; the bundle shows only the deep-link path. Email delivery is server-side (`send_email`), so an emailed invite reaches the user through a link, not through a desktop call.

**VERIFIED eligibility:** the recipient needs an eligible individual subscription (P `GrokBotAgentAccessInviteIneligibleReason`). Which tiers count as eligible: **UNKNOWN**.

**INFERRED TUI shape:** list and revoke use email; preview and accept use the code from the link. A TUI cannot get an invite id from list.

## 4. Managers

**VERIFIED (P `ListGrokBotAgentManagersRequest|1 agent_id 9`; P `ListGrokBotAgentManagersResponse|1 manager_user_ids 5*`).** Read-only. Ids only, int32, **Personal**. Names are not returned.

**VERIFIED add and remove (P `AddGrokBotAgentManagerRequest|1 agent_id 9|2 user_id 5`; P `RemoveGrokBotAgentManagerRequest|1 agent_id 9|2 user_id 5`).** Both write. The identifier is the int32 user id, not an email. The renderer picks people from the directory and then sends the user id (M `addManager:async(y,h)=>{await o().addGrokBotAgentManager({agentId:y,userId:h}`). Responses are empty.

**VERIFIED versus access principals:** a manager is a separate list keyed by user id. An access principal is a row in the access list (section 1), and its role may be MANAGER. **INFERRED:** a manager and a MANAGER-role user row are two channels to the same permission; the bundle does not say which one grants what. **UNKNOWN:** who may call add or remove on the server.

## 5. In-place share

**VERIFIED request/reply (P `ShareGrokBotAgentInPlaceRequest|1 agent_id 9`; P `ShareGrokBotAgentInPlaceResponse|1 outcome #0`; P `"ShareGrokBotAgentInPlaceOutcome",[[0,"UNSPECIFIED"],[1,"STARTED"],[2,"UNSUPPORTED"],[3,"INELIGIBLE"]]`).** Writes. STARTED starts a server-side job; the request does not return the result.

**VERIFIED status (P `GetGrokBotAgentInPlaceShareStatusRequest|1 agent_id 9`; P `GetGrokBotAgentInPlaceShareStatusResponse|1 state #0|2 step #1|3 failure_reason 9|4 shared 8`).** `state`: NOT_STARTED, RUNNING, DONE, FAILED (P `GrokBotAgentInPlaceShareState`). `step`: CHECK, MARK, MEMORY, FILES, VERIFY_FILES, GRANTS, FLIP, FINISH, CLEAR (P `GrokBotAgentInPlaceShareStep`). `shared` is a bool. `failure_reason` is a string.

**VERIFIED polling (M `function UQn(e=LQn)`; M `LQn={timeoutMs:45*6e4,initialDelayMs:1e3,maxDelayMs:5e3}`; M `shareInPlace:y=>{let h=i.get(y)`).** The app is long-running. It polls the status until DONE or FAILED. Delay starts at 1 second, grows by a factor of 1.5 with equal jitter, and is capped at 5 seconds. It keeps polling while the state is NOT_STARTED or RUNNING, and retries transient connect errors. The whole wait has a 45-minute deadline, and each status call has a 30-second timeout (M `DQn=3e4`). Calls for the same agent are de-duplicated.

**INFERRED meaning:** "shared in place" means the same bot is made visible to the team by running the step list above on that bot; it is not a copy. Consistent with this, the desktop returns "shared" at once when visibility is already TEAM (R `shareAgentInPlace:(t,{teamId:r})=>n.get().agentsById.get(t)?.visibility===\`team\``). The exact effect of each step is **UNKNOWN**.

**VERIFIED what it is not:** the clone call has an `in_place` flag (P `CloneGrokBotAgentToTeamRequest|1 agent_id 9|2 personal_secret_names 9*|3 offer_entry_id 9|4 in_place 8`), but the desktop never sets it (M `cloneToTeam:async(y,{offerEntryId:h,personalSecretNames:S})` sends only agent, offer entry and secret names).

**VERIFIED read-only use:** GetGrokBotAgentInPlaceShareStatus is read-only and can be called once to read the state.

## 6. Clone to team

**VERIFIED request/reply (P `CloneGrokBotAgentToTeamRequest|1 agent_id 9|2 personal_secret_names 9*|3 offer_entry_id 9|4 in_place 8`; P `CloneGrokBotAgentToTeamResponse|1 outcome #0|2 agent #1`; P `"CloneGrokBotAgentToTeamOutcome",[[0,"UNSPECIFIED"],[1,"CLONED"],[2,"UNSUPPORTED"],[3,"NO_TEAM"]]`).** Writes. The reply is synchronous: CLONED carries the new `agent`, and the desktop reads its agent id at once (M `case A.CloneGrokBotAgentToTeamOutcome.CLONED`). NO_TEAM means the user has no team to clone into. There is no job id and no follow-up polling in the desktop (M `cloneToTeam` has no status loop). The client timeout value is set by shared options that were not traced (**UNKNOWN**).

**VERIFIED arguments the app sends:** `agent_id`, `offer_entry_id` (string; meaning **UNKNOWN**, it names an entry of an offer that the desktop passes through), `personal_secret_names` (repeated string, names only).

**VERIFIED what is copied:** the bundle names no copy scope for clone. **INFERRED:** named personal secrets are carried to the copy. Memories, files, connectors and skills: **UNKNOWN**. The desktop has a separate secret carry-over path for box secrets (M `carryBoxSecretsToBot`), which is not part of this RPC.

**Secret and Personal fields:** `personal_secret_names` holds names, not values; values are never sent.

## 7. Team features

**ListGrokBotTeamAgents (cite protocol-temporal section 7 and protocol-m3 section 10).** Request: `role` (string, optional). Reply: `entries` (agent plus signals: user turns, teammate turns, last turn time, slack link state, owner avatar, added users), `slack_connections`, `teams_connections` (P `ListGrokBotTeamAgentsRequest|1 role 9?`; P `ListGrokBotTeamAgentsResponse|1 entries #0*|2 slack_connections #1*|3 teams_connections #2*`). Read-only. The desktop treats an Unimplemented reply as "no list" (M `function uVn(e,t)`), then falls back as protocol-temporal describes.

**GetGrokBotTeamContextSummary (read-only).** Request: `agent_id`. Reply: `summary` (`memory_version` uint32, `generated_at_ms` int64, `prose` and `summary_model`, **Personal** prose), `stale` (bool), `skills` [], `learned` [] (`fact_id`, `text` (**Personal**), `learned_at_ms`), `memory_count` (uint32) (P `GetGrokBotTeamContextSummaryResponse|1 summary #0?|4 stale 8|5 skills #1*|6 learned #2*|7 memory_count 13`; P `GrokBotTeamContextLearnedEntry|1 fact_id 9|2 text 9|3 learned_at_ms 3`). The desktop reads `learned` as the shared memories (R `getSharedMemories` maps `factId`, `text`).

**Link preview (team setting, not the bot card).** Get: `team_id` → `setting` (`enabled` bool). Set: `team_id`, `enabled` → `setting` (P `GetGrokBotTeamLinkPreviewRequest|1 team_id 5`; P `SetGrokBotTeamLinkPreviewRequest|1 team_id 5|2 enabled 8`; P `GrokBotTeamLinkPreviewSetting|1 enabled 8`). The desktop passes `isEnabled` through IPC and sends `enabled` to the RPC (R `setGrokBotTeamLinkPreview:En().args({teamId:ln(),isEnabled:Tn()})`). So "link preview" here is a team-wide on or off switch. The per-bot public card is a different RPC: `GetPublicGrokBotAgentPreview` returns `GrokBotAgentLinkPreview` (name, description, avatar shape and colour; P `GetPublicGrokBotAgentPreviewResponse|1 preview #0`). The desktop does not call it (zero hits in M and R). The card's use is **UNKNOWN**.

**PromoteGrokBotMemoriesToTeam.** Request: `agent_id`, `fact_ids` (repeated string). Reply: `created` [], `already_in_team` [] (both `GrokBotMemoryFact`: `fact_id`, `text` (**Personal**), `learned_at_ms`), `kept_private_count` (uint32) (P `PromoteGrokBotMemoriesToTeamRequest|1 agent_id 9|2 fact_ids 9*`; P `PromoteGrokBotMemoriesToTeamResponse|1 created #0*|2 already_in_team #0*|3 kept_private_count 13`). Writes. Memories are selected from `ListGrokBotUserBotMemories` (`GrokBotMemoryFact` list; R `promoteToTeam:async(n,r)`). **INFERRED:** the user picks facts; the rest stay private (the count). The server rule for "kept private" is **UNKNOWN**.

**ListGrokBotTeamReviewItems (read-only).** Request: `agent_id`, `statuses` (repeated `GrokBotTeamReviewItemStatus`: UNSPECIFIED, PENDING, APPROVED, REJECTED), `limit` (uint32). Reply: `items` []. Item (P `GrokBotTeamReviewItem|1 item_id 9|2 status #0|3 proposed_by_user_id 3|4 reviewed_by_user_id 3|5 created_at_ms 3|6 change #1|7 reviewed_at_ms 3`). The user ids are **Personal**. The change is a oneof with three kinds (P `GrokBotTeamReviewChange`): memory (action WRITE or FORGET, `text`, `memory_type`), skill (action ADD, UPDATE or REMOVE, `name`, `description`, `content`), and folder memory (action, `memory_type`, `text`, `meta_json`, `path`), plus `method` and `summary`. Text fields are **Personal**. The desktop asks for pending items with a limit of 100 and approved items with a limit of 20 (R `listBotReviewItems({agentId:t,statuses:[\`pending\`],limit:iSe})`, iSe=100; aSe=20).

**ResolveGrokBotTeamReviewItem (writes).** Request: `agent_id`, `item_id`, `decision` (`GrokBotTeamReviewDecision`: UNSPECIFIED, APPROVE, REJECT). Reply: `item` (P `ResolveGrokBotTeamReviewItemRequest|1 agent_id 9|2 item_id 9|3 decision #0`; P `ResolveGrokBotTeamReviewItemResponse|1 item #0`). The desktop wraps it as `resolveBotReviewItem` (R). **UNKNOWN:** who may resolve. The renderer hook has no role check that this pass located; the server rule is not in the bundle.

**AddGrokBotTeamReviewItem.** Declined in parity.json; no desktop call site (see section 11).

## 8. Teams and roles

**VERIFIED team list (DashboardService, section 0).** `GetTeams` request: `active_only` (bool, optional). Reply: `teams` [] of `Team` with `name`, `id` (int32), `role` (`TeamRole`), `seats`, `has_billing`, `is_direct_member` and billing fields (P `GetTeamsRequest|1 active_only 8?`; P `Team|1 name 9|2 id 5|3 role #0|4 seats 5|5 has_billing 8`; P `"TeamRole",[[0,"UNSPECIFIED"],[1,"OWNER"],[2,"MEMBER"],[3,"FREE_OWNER"],[4,"REMOVED"]]`). The desktop calls it from main (M `r.getTeams(new A.GetTeamsRequest({})`), and its mapper keeps id, name, billing flags, seats, direct-member flag, enterprise flag and icon. It does not keep `role` (M `function Zcn(`). So the user's role in each team is in the reply, but the desktop does not show it through this path.

**VERIFIED members (DashboardService).** `GetTeamMembers` request: `team_id`, `include_org_admins` (optional). Reply: `team_members` [] (`TeamMember`: `name`, `email` (**Personal**), `id`, `role` (`TeamRole`), `is_removed`, and billing fields), `user_id` (the caller's own id, **Personal**), `org_admins` [] (P `TeamMember|1 name 9|4 email 9|2 id 5|3 role #0|5 is_removed 8`; P `GetTeamMembersResponse|1 team_members #0*|2 user_id 5`). The desktop reads `user_id` as the self id and drops removed members (M `function Jcn(`).

**VERIFIED what the app hides or disables for a non-owner (R `function mu(e)`).** For a bot the viewer does not own, the app shows the wrench, the settings editor, Slack management, share, analytics and the learnings review only when the server says the viewer can manage (`viewerCanManage`). Publish, owner-only shared memories and shared files are owner-only, and shared files are never shown in that function (`canSeeSharedFiles:!1`). The share popover reads `viewerRole` and treats `owner` as the owner case (S `f=d===\`owner\``), and requires `canShare` before enabling sharing controls (S `if(!n.canShare)`). Share-in-place is enabled only when the server lists `share_in_place` in `viewerAllowedActions` (R `function Xoe(e){return e?.viewerAllowedActions?.includes(\`share_in_place\`)`). Manage-credentials works the same way (R `Zoe`).

**UNKNOWN:** which of these server flags carries the admin or manager role for a team (the bundle has no `can_manage` on the bot-level reads). The team-level `can_manage` fields belong to other RPCs (for example GetTeamTailnet) and are not used by the bot share path.

## 9. Browser handoff

Browser handoffs that touch these areas are listed in protocol-m4b section 11. In the sharing and access area (sections 1 to 7) the bundle opens no external URL: the invite URL is shown and copied (V). In the chunks checked (U, G, S, V, I and the renderer index), the clone, share and promote flows open nothing.

**Teams (protocol-m4b section 11 rows, not repeated):** Teams consent and admin consent, Teams package download, and the human Teams account link. Completion is observed by polling the Teams install state (with the consent nonce) and the Teams account link status, not by the browser returning.

**Slack (same pattern, outside M5; protocol-m4b section 11):** the Slack consent handoff in F (`case\`awaiting_workspace\``, `consentUrl`) is opened with `openExternal`. Completion is by polling.

**Inbound deep link (not a handoff):** the invite route in section 3 is the only inbound path in this area. The app's router sends the URL to the app (K `function WZ(e,t,n)` calls `activateDeepLink` for the app route).

## 10. Events

**VERIFIED /events channels (M `XOn={"transport-connected":!0,"transport-down":!0,"agents-event":!0,"agents-roster-seed":!0,"agent-activity":!0,"team-agent-activity":!0,"server-roster-changed":!0,"server-feed-changed":!0}`).** This list is the complete event allow-list the main process forwards. None of its names is an access, invite, manager, share or review event.

**VERIFIED server-roster-changed (protocol-m4b section 12 has the shapes).** Its `agent` kind carries an `agentId`; `resync` triggers a refresh of the dock badge and menu bar (M `"server-roster-changed"` handler calls `noteServerRosterChanged`). The desktop refreshes its own roster after its writes (R `t.roster.noteServerRosterChanged()`; R `setVisibility` and clone paths call the roster refresh).

**VERIFIED backend stream (P `GrokBotTranscriptWatchRosterChanged|1 kind #0|2 agent_id 9|3 changed_at_ms 3|4 agent #1?|5 changed_fields #2*`; P `"GrokBotRosterChangeKind",[[0,"UNSPECIFIED"],[1,"AGENT_CREATED"],[2,"AGENT_UPDATED"],[3,"AGENT_DELETED"],[4,"AGENT_VISIBILITY_CHANGED"],[5,"ROOM_MEMBERS_CHANGED"],[6,"SIDEBAR_VISIBILITY_CHANGED"],[7,"USER_SETTINGS_CHANGED"]]`).** The roster-change message arrives on the `WatchGrokBotTranscripts` server stream (P `WatchGrokBotTranscripts` ServerStreaming). The desktop bundle has no consumer for `RosterChanged` (**VERIFIED** absence in M, K, R and the chunks). Its kinds include AGENT_VISIBILITY_CHANGED, but nothing in the desktop bundle reacts to it. Whether the gateway turns it into `server-roster-changed` is **UNKNOWN**.

**VERIFIED absence:** no access-changed, invite-accepted, invite-created, manager-changed, share-status or review-item event name exists in the allow-list or in the watch message kinds. **UNKNOWN:** whether the backend emits any such event at all.

**INFERRED TUI rule:** refresh access, invites, managers and review items after the TUI's own writes; use `server-roster-changed` (agent kind for one bot, resync for all); poll the in-place status while it is RUNNING (section 5); poll review items on a slow interval because no event is known.

## 11. Read-only capture shortlist and parity proposals

Read-only RPCs (no side effects) with the smallest arguments that would capture a real reply. Use the id form settled in section 0; until settled, use the form the desktop uses for that RPC. Mark captured personal fields as shapes only.
- GetGrokBotAgentAccess: agent id (form per section 0) and `lists_cross_tier_principals` true, as the app sends.
- GetGrokBotAgentLinkAccess: agent id.
- ListGrokBotAgentAccessInvites: agent id (**Personal** emails; capture shapes only).
- ListGrokBotAgentManagers: agent id.
- GetGrokBotAgentInPlaceShareStatus: agent id.
- ListGrokBotTeamAgents: no arguments (team account only).
- GetGrokBotTeamContextSummary: agent id.
- GetGrokBotTeamLinkPreview: a team id from GetTeams.
- ListGrokBotTeamReviewItems: agent id, one status, limit 1.
- ListGrokBotUserBotMemories: agent id (needed to see the promote source).
- GetTeams (DashboardService): `active_only` true.
- GetTeamMembers (DashboardService): a team id; **Personal** emails and names, capture shapes only.

Not read-only (do not call to capture): every Set, Update, Create, Revoke, Accept, Add, Remove, Share, Clone, Promote and Resolve RPC, and PreviewGrokBotAgentAccessInvite (needs a real invite code, which is **Secret**).

Parity proposals (the app does not offer these on this path):
- AddGrokBotAgentAccessPrincipal, RemoveGrokBotAgentAccessPrincipal, ListGrokBotAgentAccessPrincipals: keep `declined`. The desktop uses only GetGrokBotAgentAccess and UpdateGrokBotAgentAccess, and no caller of the three was found.
- AddGrokBotTeamReviewItem: keep `declined`. No desktop call site.
- GetPublicGrokBotAgentPreview (parity.json M3, area templates): already `declined`; re-confirmed, no desktop call site.
- Team-only actions for a personal (non-team) account: SetGrokBotAgentVisibility (NO_TEAM outcome), CloneGrokBotAgentToTeam (NO_TEAM), ShareGrokBotAgentInPlace (INELIGIBLE), GetGrokBotTeamLinkPreview and SetGrokBotTeamLinkPreview (need a team id), PromoteGrokBotMemoriesToTeam, ResolveGrokBotTeamReviewItem. Proposed status `handoff` to the desktop app, reason: the server answers NO_TEAM or needs a team id, so the TUI cannot do them without a team.

## 12. Open items

- Id form for serverId-keyed calls versus agentId-keyed calls (section 0). Settled by a capture of GetGrokBotAgentAccess with each form.
- Meaning of ALLOWED versus NO_ACCESS in link access; how a team-visible bot returns to OWNER (section 2).
- What USER and MANAGER allow on the server; what the manager list grants compared with MANAGER rows (sections 1 and 4).
- What each in-place step does and whether the flip changes visibility (section 5). Settled by server source or a paired status capture around a test bot, which is out of scope here.
- What clone copies beyond named secrets; what offer_entry_id names (section 6).
- Who may resolve team review items; whether the backend emits any access, invite or review event (sections 7 and 10).
- Which tiers are eligible for invites (section 3).
