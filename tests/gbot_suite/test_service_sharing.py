import json
from pathlib import Path
from typing import Any, cast

import pytest

from gbot.service import sharing
from gbot.service.fake import load_fake
from gbot.service.transport import FakeTransport
from groken.client import ConnectError

ROOT = Path(__file__).resolve().parents[2]
ROLE = "GROK_BOT_ACCESS_ROLE_"
URL = "https://example.invalid/invite?token=secret-token-123"
CODE = "secret-token-123"


def refusal(code, message):
    return ConnectError(403, json.dumps({"code": code, "message": message}))


def transport(**rpcs):
    return FakeTransport(rpcs=rpcs)


def forms(names, prefix):
    """Every way an enum can arrive: a number, a short name and a full name."""
    for number, name in enumerate(names):
        yield number, name
        yield name.upper(), name
        yield prefix + name.upper(), name


def test_enum_forms_for_every_enum():
    cases = [
        (sharing._ROLE, ROLE),
        (sharing._LINK, "GROK_BOT_AGENT_LINK_ACCESS_"),
        (sharing._VISIBILITY, "SET_GROK_BOT_AGENT_VISIBILITY_OUTCOME_"),
        (sharing._IN_PLACE, "SHARE_GROK_BOT_AGENT_IN_PLACE_OUTCOME_"),
        (sharing._IN_PLACE_STATE, "GROK_BOT_AGENT_IN_PLACE_SHARE_STATE_"),
        (sharing._IN_PLACE_STEP, "GROK_BOT_AGENT_IN_PLACE_SHARE_STEP_"),
        (sharing._CLONE, "CLONE_GROK_BOT_AGENT_TO_TEAM_OUTCOME_"),
        (sharing._MATCH, "GROK_BOT_AGENT_ACCESS_INVITE_RECIPIENT_MATCH_"),
        (sharing._INVITE_STATE, "GROK_BOT_AGENT_ACCESS_INVITE_STATE_"),
        (sharing._REASON, "GROK_BOT_AGENT_ACCESS_INVITE_INELIGIBLE_REASON_"),
        (sharing._TIER, "GROK_BOT_AGENT_ACCESS_INVITE_TIER_"),
        (sharing._STATUS, "GROK_BOT_AGENT_ACCESS_INVITE_ACCEPT_STATUS_"),
        (sharing._OUTCOME, "GROK_BOT_AGENT_ACCESS_INVITE_ACCEPT_OUTCOME_"),
    ]
    for names, prefix in cases:
        for value, expected in forms(names, prefix):
            assert sharing._enum(value, names) == expected, (value, names)
        for odd in (999, -1, "FUTURE", prefix + "FUTURE", None, True, 1.5, [], {}):
            assert sharing._enum(odd, names) == "unknown", odd
    # "not_started" must not be read as "started".
    assert sharing._enum("X_NOT_STARTED", sharing._IN_PLACE_STATE) == "not_started"
    assert sharing._enum("2", sharing._ROLE) == "manager"


def test_role_is_user_manager_or_unknown():
    for value, expected in [
        (1, "user"),
        ("MANAGER", "manager"),
        (ROLE + "USER", "user"),
        (0, "unknown"),
        (ROLE + "UNSPECIFIED", "unknown"),
        ("viewer", "unknown"),
        (None, "unknown"),
    ]:
        assert sharing._role(value) == expected


ACCESS = {
    "creatorUserId": 1,
    "viewerUserId": "2",
    "state": {
        "availableRoles": [ROLE + "USER", ROLE + "MANAGER"],
        "expectedStateToken": "token-1",
        "principals": [
            {"role": ROLE + "MANAGER", "team": {}},
            {
                "userId": 12,
                "role": ROLE + "USER",
                "invitedAsEmail": "a@example.invalid",
            },
            {"groupId": "34", "role": "MANAGER"},
            {"otherTeamId": 5, "role": 1},
            {"organization": {}, "role": ROLE + "USER"},
            {"somethingNew": {}, "role": ROLE + "USER"},
        ],
        "teamRowOn": True,
        "teamRowOffAllowed": True,
        "groupsEnabled": True,
        "crossTeamSharingEnabled": True,
        "callerMayEditCrossTeamRows": True,
    },
    "personalBotPeople": [{"userId": 1, "name": "Owner Person"}],
    "botTeamDirectory": {
        "team": {"id": 9},
        "people": [{"userId": "12", "name": "Pat Doe"}],
        "groups": [{"groupId": "34", "name": "Design", "memberCount": 4}],
    },
    "crossTierDirectory": {"organization": {"name": "Example Org"}, "icon": "x"},
}


def test_access_parses_every_kind_and_the_directories():
    fake = transport(GetGrokBotAgentAccess=ACCESS)
    state = sharing.access(fake, "gateway")
    assert fake.calls == [
        (
            "rpc",
            "GetGrokBotAgentAccess",
            {"agentId": "gateway", "listsCrossTierPrincipals": True},
        )
    ]
    assert [(p.kind, p.ref, p.role) for p in state.principals] == [
        ("team", None, "manager"),
        ("user", "12", "user"),
        ("group", "34", "manager"),
        ("other_team", "5", "user"),
        ("organization", None, "user"),
        ("unknown", None, "user"),
    ]
    assert state.principals[1].invited_as_email == "a@example.invalid"
    assert state.creator_user_id == 1 and state.viewer_user_id == 2
    assert state.available_roles == ("user", "manager")
    assert state.expected_state_token == "token-1"
    assert state.team_row_on and state.team_row_off_allowed
    assert state.groups_enabled and state.cross_team_sharing_enabled
    assert state.caller_may_edit_cross_team_rows
    assert state.people == {1: "Owner Person", 12: "Pat Doe"}
    assert state.groups == {"34": sharing.Group("Design", 4)}
    assert state.organization_name == "Example Org"
    assert [state.describe(p) for p in state.principals] == [
        "Everyone in the team",
        "Pat Doe",
        "Design",
        "Team #5",
        "Everyone in Example Org",
        "Unknown access row",
    ]
    assert [p.spec for p in state.principals[:4]] == [
        "team",
        "user:12",
        "group:34",
        "other_team:5",
    ]
    assert state.owner_label() == "Owner Person"


@pytest.mark.parametrize(
    "reply",
    [
        {},
        {"state": "oops", "botTeamDirectory": 3, "crossTierDirectory": []},
        {"state": {"principals": {}, "availableRoles": "x"}},
        {"state": {"principals": [1, "x", None, {"userId": "abc"}]}},
        {"creatorUserId": "x", "personalBotPeople": [{"name": 3}, "x", {"userId": 1}]},
    ],
)
def test_access_never_raises_on_odd_shapes(reply):
    state = sharing.access(transport(GetGrokBotAgentAccess=reply), "gateway")
    assert state.available_roles == sharing.ROLES
    assert not state.team_row_on and not state.team_row_off_allowed
    assert state.people == {} and state.groups == {}
    assert state.organization_name == ""
    assert all(p.kind in ("unknown",) for p in state.principals)


def test_directory_shapes_that_parse_are_kept():
    reply = {
        "personalBotPeople": [{"userId": 7, "name": "Seven"}],
        "botTeamDirectory": {
            "teams": [{"people": [{"id": 8, "displayName": "Eight"}], "groups": []}]
        },
        "crossTierDirectory": {
            "teams": [{"name": "Cross", "groups": [{"id": 1, "name": "G"}]}]
        },
    }
    state = sharing.access(transport(GetGrokBotAgentAccess=reply), "gateway")
    assert state.people == {7: "Seven", 8: "Eight"}
    assert state.groups == {"1": sharing.Group("G", 0)}
    assert state.organization_name == "Cross"


def test_owner_label():
    state = sharing.AccessState(creator_user_id=1, viewer_user_id=1)
    assert state.owner_label() == "you"
    assert sharing.AccessState(1, 1, people={1: "Pat"}).owner_label() == "Pat (you)"
    assert sharing.AccessState(1, 2).owner_label() == "User #1"
    assert sharing.AccessState().owner_label() == "unknown"


def test_update_sends_the_whole_list_the_token_and_cross_tier_flag():
    fake = transport(UpdateGrokBotAgentAccess=ACCESS)
    rows = (
        sharing.Principal("team", None, "manager"),
        sharing.Principal("user", "12", "user", "a@example.invalid"),
        sharing.Principal("group", "34", "manager"),
        sharing.Principal("other_team", "5", "user"),
        sharing.Principal("organization", None, "user"),
    )
    result = sharing.update_access(fake, "gateway", rows, "token-1")
    assert isinstance(result, sharing.AccessState)
    assert fake.calls == [
        (
            "rpc",
            "UpdateGrokBotAgentAccess",
            {
                "agentId": "gateway",
                "update": {
                    "principals": [
                        {"team": {}, "role": ROLE + "MANAGER"},
                        {
                            "userId": 12,
                            "role": ROLE + "USER",
                            "invitedAsEmail": "a@example.invalid",
                        },
                        {"groupId": "34", "role": ROLE + "MANAGER"},
                        {"otherTeamId": 5, "role": ROLE + "USER"},
                        {"organization": {}, "role": ROLE + "USER"},
                    ],
                    "expectedStateToken": "token-1",
                    "listsCrossTierPrincipals": True,
                },
            },
        )
    ]
    # The owner is implicit: an empty list is a valid update and sends no owner row.
    sharing.update_access(fake, "gateway", (), "t")
    assert cast(dict[str, Any], fake.calls[-1][2])["update"]["principals"] == []


@pytest.mark.parametrize(
    "row",
    [
        sharing.Principal("unknown", None, "user"),
        sharing.Principal("user", "1", "unknown"),
        sharing.Principal("user", None, "user"),
    ],
)
def test_update_refuses_a_list_it_cannot_resend_faithfully(row):
    fake = transport(UpdateGrokBotAgentAccess=ACCESS)
    with pytest.raises(ValueError):
        sharing.update_access(fake, "gateway", (row,), "token")
    assert fake.calls == []


def test_pure_helpers():
    team = sharing.Principal("team", None, "user")
    pat = sharing.Principal("user", "12", "user", "a@example.invalid")
    rows = (team, pat)
    assert sharing.with_principal(rows, sharing.Principal("group", "3", "user")) == (
        *rows,
        sharing.Principal("group", "3", "user"),
    )
    # Granting an existing row changes its role and keeps the invited email.
    changed = sharing.with_principal(rows, sharing.Principal("user", "12", "manager"))
    assert changed[1] == sharing.Principal("user", "12", "manager", "a@example.invalid")
    assert sharing.without_principal(rows, "user", "12") == (team,)
    with pytest.raises(ValueError):
        sharing.without_principal(rows, "user", "99")
    assert sharing.with_role(rows, "team", None, "manager")[0].role == "manager"
    with pytest.raises(ValueError):
        sharing.with_role(rows, "user", "99", "manager")
    with pytest.raises(ValueError):
        sharing.with_role(rows, "user", "12", "owner")
    assert rows == (team, pat)


def test_team_row_helpers_and_the_off_rule():
    team = sharing.Principal("team", None, "user")
    pat = sharing.Principal("user", "12", "user")
    only_team = sharing.AccessState(principals=(team,), team_row_on=True)
    with pytest.raises(ValueError, match="cannot be turned off"):
        sharing.with_team_row(only_team, False)
    allowed = sharing.AccessState(
        principals=(team,), team_row_on=True, team_row_off_allowed=True
    )
    assert sharing.with_team_row(allowed, False) == ()
    # Other rows remain, so the flag does not matter.
    with_other = sharing.AccessState(principals=(team, pat), team_row_on=True)
    assert sharing.with_team_row(with_other, False) == (pat,)
    # On: add at the end, or change the role in place.
    off = sharing.AccessState(principals=(pat,))
    assert sharing.with_team_row(off, True) == (pat, team)
    assert sharing.with_team_row(off, True, "manager")[-1].role == "manager"
    assert sharing.with_team_row(with_other, True, "manager") == (
        sharing.Principal("team", None, "manager"),
        pat,
    )
    with pytest.raises(ValueError):
        sharing.with_team_row(off, True, "owner")


def test_link_access_and_visibility():
    for value, expected in [
        ("GROK_BOT_AGENT_LINK_ACCESS_ALLOWED", "allowed"),
        (2, "no_access"),
        ("NOT_FOUND", "not_found"),
        (0, "unknown"),
        ("later", "unknown"),
    ]:
        fake = transport(GetGrokBotAgentLinkAccess={"access": value})
        assert sharing.link_access(fake, "gateway") == expected
        assert fake.calls[0][2] == {"agentId": "gateway"}
    fake = transport(SetGrokBotAgentVisibility={"outcome": "UPDATED"})
    assert sharing.make_team_visible(fake, "gateway") == "updated"
    assert fake.calls[0][2] == {
        "agentId": "gateway",
        "visibility": "GROK_BOT_AGENT_VISIBILITY_TEAM",
    }
    sharing.make_team_visible(fake, "gateway", ["TOKEN", "KEY"])
    assert fake.calls[1][2]["personalSecretNames"] == ["TOKEN", "KEY"]
    for value, expected in [
        ("UPDATED", "updated"),
        (2, "unsupported_harness"),
        ("NO_TEAM", "no_team"),
        (4, "busy"),
        (0, "unknown"),
    ]:
        fake = transport(SetGrokBotAgentVisibility={"outcome": value})
        assert sharing.make_team_visible(fake, "gateway") == expected


def test_every_outcome_has_its_own_sentence():
    generic = sharing.sentence("unknown")
    names = {
        name
        for table in (
            sharing._LINK,
            sharing._VISIBILITY,
            sharing._IN_PLACE,
            sharing._IN_PLACE_STATE,
            sharing._CLONE,
            sharing._MATCH,
            sharing._INVITE_STATE,
            sharing._REASON,
            sharing._STATUS,
            sharing._OUTCOME,
        )
        for name in table
    }
    for name in sorted(names - {"unknown"}):
        assert sharing.sentence(name).endswith("."), name
        if name != "unspecified":
            assert sharing.sentence(name) != generic, name
    assert sharing.sentence("never-seen") == generic
    assert "token" not in generic


def test_invites_list_create_and_revoke():
    fake = transport(
        ListGrokBotAgentAccessInvites={
            "invites": [
                {
                    "email": "a@example.invalid",
                    "expiresAtMs": "1800000000000",
                    "lastSharedAtMs": "5",
                    "createdAtMs": 3,
                },
                "junk",
            ],
            "capUsage": {"used": 1, "limit": "10"},
        },
        CreateGrokBotAgentAccessInvite={
            "invite": {"email": "b@example.invalid", "expiresAtMs": "7"},
            "inviteCreated": True,
            "inviteUrl": URL,
            "graceMs": "60000",
            "capUsage": {"used": 2, "limit": 10},
            "inviteEmailSent": True,
        },
        RevokeGrokBotAgentAccessInvite={
            "revokedCount": 1,
            "capUsage": {"used": 1, "limit": 10},
        },
    )
    rows, cap = sharing.invites(fake, "gateway")
    assert rows == (sharing.Invite("a@example.invalid", 1800000000000, 5, 3),)
    assert cap == sharing.CapUsage(1, 10)
    result = sharing.create_invite(fake, "gateway", " b@example.invalid ")
    assert fake.calls[1][2] == {
        "agentId": "gateway",
        "email": "b@example.invalid",
        "sendEmail": True,
    }
    sharing.create_invite(fake, "gateway", "b@example.invalid", language="pt-BR")
    assert fake.calls[2][2]["language"] == "pt-BR"
    assert result.created and result.email_sent and result.grace_ms == 60000
    assert result.cap_usage == sharing.CapUsage(2, 10)
    assert result.invite.expires_at_ms == 7 and result.url == URL
    count, cap = sharing.revoke_invite(fake, "gateway", "b@example.invalid")
    assert (count, cap) == (1, sharing.CapUsage(1, 10))
    assert fake.calls[-1][2] == {"agentId": "gateway", "email": "b@example.invalid"}
    # Secrets and personal data stay out of every repr.
    for value in (result, result.invite, rows[0]):
        assert URL not in repr(value) and CODE not in repr(value)
        assert "@example.invalid" not in repr(value)


def test_invites_odd_and_empty_replies():
    fake = transport(
        ListGrokBotAgentAccessInvites={},
        CreateGrokBotAgentAccessInvite={},
        RevokeGrokBotAgentAccessInvite={},
    )
    assert sharing.invites(fake, "gateway") == ((), None)
    result = sharing.create_invite(fake, "gateway", "a@example.invalid")
    assert result == sharing.InviteResult(sharing.Invite())
    assert sharing.revoke_invite(fake, "gateway", "a@example.invalid") == (0, None)


@pytest.mark.parametrize(
    "email", ["", "plain", "a@b", "a b@example.invalid", "@example.invalid"]
)
def test_invalid_emails_send_nothing(email):
    fake = transport(CreateGrokBotAgentAccessInvite={})
    with pytest.raises(ValueError, match="valid email"):
        sharing.create_invite(fake, "gateway", email)
    assert fake.calls == []


def test_invite_code_from_a_link_or_raw_text():
    assert sharing.invite_code("  abc-123 \n") == "abc-123"
    assert (
        sharing.invite_code("https://example.invalid/x?token=abc%2B1&id=2") == "abc+1"
    )
    assert sharing.invite_code("grokbot://v1/agent-invite?id=42&token=tok-1") == "tok-1"
    # A link without a token is not a code; the trimmed text is used as is.
    assert sharing.invite_code(" https://example.invalid/x?id=2 ") == (
        "https://example.invalid/x?id=2"
    )
    assert sharing.invite_code("https://example.invalid/x?token=") == (
        "https://example.invalid/x?token="
    )
    assert sharing.invite_code("") == ""


def test_preview_sends_only_the_code_and_parses_every_field():
    fake = transport(
        PreviewGrokBotAgentAccessInvite={
            "found": True,
            "recipientMatch": "GROK_BOT_AGENT_ACCESS_INVITE_RECIPIENT_MATCH_DOES_NOT_MATCH",
            "sender": {"displayName": "Pat Doe", "avatar": {}},
            "invites": [
                {
                    "inviteId": "i1",
                    "bot": {"agentId": "bot-1", "name": "Helper"},
                    "role": "manager",
                    "state": "NOT_SHAREABLE",
                    "expiresAtMs": "1800000000000",
                }
            ],
            "eligibility": {
                "eligible": False,
                "reason": "TIER_NOT_ELIGIBLE",
                "currentTier": "PLUS",
            },
            "truncated": False,
        }
    )
    preview = sharing.preview_invite(fake, CODE)
    assert fake.calls == [("rpc", "PreviewGrokBotAgentAccessInvite", {"code": CODE})]
    assert preview.found and preview.recipient_match == "does_not_match"
    assert preview.sender_name == "Pat Doe"
    assert preview.items == (
        sharing.InviteItem(
            "bot-1", "Helper", "manager", "not_shareable", "", 1800000000000
        ),
    )
    assert preview.eligibility == sharing.Eligibility(
        False, "tier_not_eligible", "plus"
    )
    assert CODE not in repr(preview) and "Pat Doe" not in repr(preview)


def test_preview_and_accept_with_missing_fields():
    fake = transport(
        PreviewGrokBotAgentAccessInvite={},
        AcceptGrokBotAgentAccessInvite={"items": [{"outcome": 99}, 3]},
    )
    assert sharing.preview_invite(fake, CODE) == sharing.InvitePreview()
    result = sharing.accept_invite(fake, CODE)
    assert fake.calls[1] == ("rpc", "AcceptGrokBotAgentAccessInvite", {"code": CODE})
    assert result.status == "unknown"
    assert result.items == (sharing.InviteItem(role="unknown", outcome="unknown"),)


def test_accept_statuses_and_outcomes():
    for status in sharing._STATUS[1:]:
        fake = transport(
            AcceptGrokBotAgentAccessInvite={
                "status": "STATUS_" + status.upper(),
                "items": [
                    {
                        "bot": {"agentId": "b", "name": "N"},
                        "role": "user",
                        "outcome": o.upper(),
                    }
                    for o in sharing._OUTCOME[1:]
                ],
            }
        )
        result = sharing.accept_invite(fake, CODE)
        assert result.status == status
        assert [i.outcome for i in result.items] == list(sharing._OUTCOME[1:])
        assert all(i.state == "" for i in result.items)


def test_managers():
    fake = transport(
        ListGrokBotAgentManagers={"managerUserIds": [3, "4", "x", None, True]},
        AddGrokBotAgentManager={},
        RemoveGrokBotAgentManager={},
    )
    assert sharing.managers(fake, "gateway") == (3, 4)
    sharing.add_manager(fake, "gateway", 12)
    sharing.remove_manager(fake, "gateway", 12)
    assert fake.calls[1:] == [
        ("rpc", "AddGrokBotAgentManager", {"agentId": "gateway", "userId": 12}),
        ("rpc", "RemoveGrokBotAgentManager", {"agentId": "gateway", "userId": 12}),
    ]
    assert sharing.managers(transport(ListGrokBotAgentManagers={}), "gateway") == ()
    for bad in (0, -1, True, "12"):
        with pytest.raises(ValueError):
            sharing.add_manager(fake, "gateway", cast(Any, bad))
    assert len(fake.calls) == 3


def test_in_place_share_and_status():
    for value, expected in [
        ("STARTED", "started"),
        (2, "unsupported"),
        ("INELIGIBLE", "ineligible"),
        (0, "unknown"),
    ]:
        fake = transport(ShareGrokBotAgentInPlace={"outcome": value})
        assert sharing.share_in_place(fake, "gateway") == expected
        assert fake.calls[0] == (
            "rpc",
            "ShareGrokBotAgentInPlace",
            {"agentId": "gateway"},
        )
    fake = transport(
        GetGrokBotAgentInPlaceShareStatus={
            "state": "GROK_BOT_AGENT_IN_PLACE_SHARE_STATE_RUNNING",
            "step": "GROK_BOT_AGENT_IN_PLACE_SHARE_STEP_VERIFY_FILES",
            "shared": True,
        }
    )
    assert sharing.in_place_status(fake, "gateway") == sharing.InPlaceStatus(
        "running", "verify_files", "", True
    )
    fake.rpcs["GetGrokBotAgentInPlaceShareStatus"] = {
        "state": 4,
        "failureReason": "disk full",
    }
    assert sharing.in_place_status(fake, "gateway") == sharing.InPlaceStatus(
        "failed", "", "disk full", False
    )
    fake.rpcs["GetGrokBotAgentInPlaceShareStatus"] = {}
    assert sharing.in_place_status(fake, "gateway").state == "unknown"


def test_in_place_not_found_is_not_started():
    fake = transport(
        GetGrokBotAgentInPlaceShareStatus=ConnectError(404, '{"code":"not_found"}')
    )
    assert sharing.in_place_status(fake, "gateway") == sharing.InPlaceStatus(
        "not_started"
    )
    fake.rpcs["GetGrokBotAgentInPlaceShareStatus"] = refusal("permission_denied", "No.")
    with pytest.raises(ConnectError):
        sharing.in_place_status(fake, "gateway")
    fake.rpcs["GetGrokBotAgentInPlaceShareStatus"] = ConnectError(500, "boom")
    with pytest.raises(ConnectError):
        sharing.in_place_status(fake, "gateway")


def test_poll_delay_and_deadline():
    delays = [sharing.next_poll_delay(None)]
    for _ in range(5):
        delays.append(sharing.next_poll_delay(delays[-1]))
    assert delays == [1, 1.5, 2.25, 3.375, 5, 5]
    assert sharing.POLL_DEADLINE_S == 45 * 60


def test_clone_to_team():
    fake = transport(
        CloneGrokBotAgentToTeam={
            "outcome": "CLONED",
            "agent": {"agentId": "new-bot", "id": "server"},
        }
    )
    assert sharing.clone_to_team(fake, "gateway") == sharing.CloneResult(
        "cloned", "new-bot"
    )
    assert fake.calls[0][2] == {"agentId": "gateway"}
    sharing.clone_to_team(fake, "gateway", ["TOKEN"])
    assert fake.calls[1][2] == {"agentId": "gateway", "personalSecretNames": ["TOKEN"]}
    for value, expected in [(2, "unsupported"), ("NO_TEAM", "no_team"), (0, "unknown")]:
        fake.rpcs["CloneGrokBotAgentToTeam"] = {"outcome": value}
        assert sharing.clone_to_team(fake, "gateway") == sharing.CloneResult(
            expected, ""
        )


def test_overview_turns_a_refused_part_into_its_message_and_keeps_the_rest():
    fake = transport(
        GetGrokBotAgentAccess=ACCESS,
        GetGrokBotAgentLinkAccess={"access": "ALLOWED"},
        ListGrokBotAgentManagers={},
        ListGrokBotAgentAccessInvites=refusal(
            "failed_precondition", "Invites need a team."
        ),
    )
    view = sharing.overview(fake, "gateway")
    assert view.access is not None and view.link_access == "allowed"
    assert view.managers == () and view.invites is None
    assert view.refused == {"invites": "Invites need a team."}
    fake.rpcs["GetGrokBotAgentLinkAccess"] = ConnectError(500, "upstream down")
    with pytest.raises(ConnectError):
        sharing.overview(fake, "gateway")


def test_attempt():
    assert sharing.attempt(lambda: 5) == (5, None)
    error = refusal("permission_denied", "Not yours.")
    assert sharing.attempt(lambda: (_ for _ in ()).throw(error)) == (None, "Not yours.")
    assert sharing.refused_message(error) == "Not yours."
    assert sharing.refused_message(ValueError("x")) is None


def test_demo_replies_and_parity():
    assert set(sharing.RPCS) == set(sharing.DEMO_RPCS)
    assert len(sharing.RPCS) == 15
    fake = load_fake()
    assert set(sharing.RPCS) <= fake.transport.rpcs.keys()
    view = sharing.overview(fake.transport, "demo-helper")
    assert not view.refused
    assert view.access is not None and view.access.team_row() is not None
    assert len([p for p in view.access.principals if p.kind != "team"]) == 2
    assert view.managers == (3,) and len(view.invites or ()) == 1
    entries = json.loads((ROOT / "docs/parity.json").read_text(encoding="utf-8"))[
        "entries"
    ]
    mine = [e for e in entries if e["name"] in sharing.RPCS]
    assert len(mine) == 15
    assert all(
        e["status"] == "done" and e["note"] == "Implemented in gbot.service.sharing"
        for e in mine
    )
