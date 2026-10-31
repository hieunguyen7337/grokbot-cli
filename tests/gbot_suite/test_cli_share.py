import getpass
import io
import json

import pytest

from gbot import cli, context
from gbot.service import sharing
from gbot.service.transport import FakeTransport
from groken.client import ConnectError

ROLE = "GROK_BOT_ACCESS_ROLE_"
URL = "https://example.invalid/invite?token=secret-token-123"
CODE = "secret-token-123"
LINK = "grokbot://v1/agent-invite?id=bot-1&token=" + CODE


def refusal(code, message):
    return ConnectError(403, json.dumps({"code": code, "message": message}))


def setup_cli(monkeypatch, **rpcs):
    fake = FakeTransport(
        {"listAgents": [{"id": "gateway", "name": "Alpha"}]},
        {**sharing.DEMO_RPCS, **rpcs},
    )
    monkeypatch.setattr(context, "manager_factory", lambda: fake)

    class Backend:
        def unary(self, service, name, payload):
            return fake.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    return fake


def stdin(monkeypatch, text, tty=False):
    stream = io.StringIO(text)
    monkeypatch.setattr(stream, "isatty", lambda: tty)
    monkeypatch.setattr("sys.stdin", stream)
    return stream


def sent(fake, name):
    return [args for _, call, args in fake.calls if call == name]


WRITES = {
    "UpdateGrokBotAgentAccess",
    "SetGrokBotAgentVisibility",
    "ShareGrokBotAgentInPlace",
    "CloneGrokBotAgentToTeam",
    "CreateGrokBotAgentAccessInvite",
    "RevokeGrokBotAgentAccessInvite",
    "AddGrokBotAgentManager",
    "RemoveGrokBotAgentManager",
    "AcceptGrokBotAgentAccessInvite",
}


def writes(fake):
    return [name for _, name, _ in fake.calls if name in WRITES]


@pytest.mark.parametrize("json_mode", [False, True])
def test_read_shows_everything(monkeypatch, capsys, json_mode):
    fake = setup_cli(monkeypatch)
    assert cli.main(["share", "Alpha", *(["--json"] if json_mode else [])]) == 0
    out = capsys.readouterr().out
    assert [name for _, name, _ in fake.calls if name != "listAgents"] == [
        "GetGrokBotAgentAccess",
        "GetGrokBotAgentLinkAccess",
        "ListGrokBotAgentManagers",
        "ListGrokBotAgentAccessInvites",
    ]
    if json_mode:
        data = json.loads(out)
        assert data["bot"] == {"id": "gateway", "name": "Alpha"}
        assert data["access"]["owner"] == "Sam Rivera (you)"
        assert data["access"]["team_row_on"] is True
        assert [
            (p["kind"], p["id"], p["name"], p["role"])
            for p in data["access"]["principals"]
        ] == [
            ("team", None, "Everyone in the team", "user"),
            ("user", "2", "Avery Chen", "user"),
            ("group", "7", "Design", "manager"),
        ]
        assert data["link_access"] == "allowed"
        assert data["managers"] == [{"user_id": 3, "name": "Jordan Lee"}]
        assert data["invites"]["invites"][0]["email"] == "invitee@example.invalid"
        assert data["invites"]["cap_usage"] == {"used": 1, "limit": 10}
        assert "token" not in out
    else:
        for text in (
            "Share Alpha",
            "Owner: Sam Rivera (you)",
            "Team row: on (user)",
            "user:2",
            "Avery Chen",
            "group:7",
            "manager",
            "Link access: allowed",
            "Managers: Jordan Lee (3)",
            "invitee@example.invalid",
            "1 of 10 invites used",
        ):
            assert text in out, text


@pytest.mark.parametrize("json_mode", [False, True])
def test_a_refused_part_shows_its_sentence_and_the_read_succeeds(
    monkeypatch, capsys, json_mode
):
    setup_cli(
        monkeypatch,
        ListGrokBotAgentAccessInvites=refusal(
            "failed_precondition", "Invites need a team."
        ),
        ListGrokBotAgentManagers=refusal("permission_denied", "Not a manager."),
    )
    assert cli.main(["share", "Alpha", *(["--json"] if json_mode else [])]) == 0
    out = capsys.readouterr().out
    if json_mode:
        data = json.loads(out)
        assert data["invites"] == {"refused": "Invites need a team."}
        assert data["managers"] == {"refused": "Not a manager."}
        assert data["access"]["owner"] == "Sam Rivera (you)"
    else:
        assert "Invites: Invites need a team." in out
        assert "Managers: Not a manager." in out
        assert "Owner: Sam Rivera (you)" in out


def test_an_unexpected_failure_is_an_error(monkeypatch, capsys):
    setup_cli(monkeypatch, GetGrokBotAgentLinkAccess=ConnectError(500, "upstream down"))
    assert cli.main(["share", "Alpha"]) == 1
    assert "upstream down" in capsys.readouterr().err


MUTATIONS = [
    (["--grant", "user:12=manager"], "UpdateGrokBotAgentAccess"),
    (["--revoke", "user:2"], "UpdateGrokBotAgentAccess"),
    (["--team-row", "off"], "UpdateGrokBotAgentAccess"),
    (["--team-visible"], "SetGrokBotAgentVisibility"),
    (["--share-in-place"], "ShareGrokBotAgentInPlace"),
    (["--clone-to-team"], "CloneGrokBotAgentToTeam"),
    (["--invite", "new@example.invalid"], "CreateGrokBotAgentAccessInvite"),
    (["--revoke-invite", "invitee@example.invalid"], "RevokeGrokBotAgentAccessInvite"),
    (["--add-manager", "12"], "AddGrokBotAgentManager"),
    (["--remove-manager", "3"], "RemoveGrokBotAgentManager"),
]


@pytest.mark.parametrize("argv,rpc", MUTATIONS)
def test_a_change_without_yes_sends_nothing(monkeypatch, capsys, argv, rpc):
    fake = setup_cli(monkeypatch)
    stdin(monkeypatch, "", tty=False)
    assert cli.main(["share", "Alpha", *argv]) == 1
    assert "--yes" in capsys.readouterr().err
    assert fake.calls == []


@pytest.mark.parametrize("argv,rpc", MUTATIONS)
def test_a_change_declined_at_the_prompt_sends_nothing(monkeypatch, capsys, argv, rpc):
    fake = setup_cli(monkeypatch)
    stdin(monkeypatch, "", tty=True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert cli.main(["share", "Alpha", *argv]) == 1
    assert "Cancelled" in capsys.readouterr().err
    assert writes(fake) == []


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("argv,rpc", MUTATIONS)
def test_every_change_works_with_yes(monkeypatch, capsys, argv, rpc, json_mode):
    # The demo replies are a personal account's refusals; these changes succeed on a team.
    fake = setup_cli(
        monkeypatch,
        SetGrokBotAgentVisibility={"outcome": "UPDATED"},
        ShareGrokBotAgentInPlace={"outcome": "STARTED"},
        CloneGrokBotAgentToTeam={"outcome": "CLONED"},
    )
    assert (
        cli.main(["share", "Alpha", *argv, "--yes", *(["--json"] if json_mode else [])])
        == 0
    )
    out = capsys.readouterr().out
    assert out.strip()
    if json_mode:
        json.loads(out)
    assert writes(fake) == [rpc]


ACCESS = {
    "creatorUserId": 1,
    "viewerUserId": 1,
    "state": {
        "expectedStateToken": "tok",
        "availableRoles": [ROLE + "USER", ROLE + "MANAGER"],
        "principals": [
            {"team": {}, "role": ROLE + "USER"},
            {"userId": 2, "role": ROLE + "USER", "invitedAsEmail": "p@example.invalid"},
            {"groupId": "7", "role": ROLE + "MANAGER"},
        ],
        "teamRowOn": True,
        "teamRowOffAllowed": False,
    },
}


def update(fake):
    (payload,) = sent(fake, "UpdateGrokBotAgentAccess")
    assert payload["agentId"] == "gateway"
    assert payload["update"]["expectedStateToken"] == "tok"
    assert payload["update"]["listsCrossTierPrincipals"] is True
    return payload["update"]["principals"]


def test_grants_and_revokes_send_the_whole_list(monkeypatch, capsys):
    fake = setup_cli(
        monkeypatch, GetGrokBotAgentAccess=ACCESS, UpdateGrokBotAgentAccess=ACCESS
    )
    argv = [
        "share",
        "Alpha",
        "--grant",
        "user:2=manager",
        "--grant",
        "other_team:5=user",
        "--grant",
        "organization=user",
        "--grant",
        "group:9=manager",
        "--revoke",
        "group:7",
        "--yes",
    ]
    assert cli.main(argv) == 0
    assert update(fake) == [
        {"team": {}, "role": ROLE + "USER"},
        {
            "userId": 2,
            "role": ROLE + "MANAGER",
            "invitedAsEmail": "p@example.invalid",
        },
        {"otherTeamId": 5, "role": ROLE + "USER"},
        {"organization": {}, "role": ROLE + "USER"},
        {"groupId": "9", "role": ROLE + "MANAGER"},
    ]
    assert "Updated access to Alpha." in capsys.readouterr().out


def test_team_row_options(monkeypatch, capsys):
    fake = setup_cli(
        monkeypatch, GetGrokBotAgentAccess=ACCESS, UpdateGrokBotAgentAccess=ACCESS
    )
    assert (
        cli.main(["share", "Alpha", "--team-row", "on", "--role", "manager", "--yes"])
        == 0
    )
    assert update(fake)[0] == {"team": {}, "role": ROLE + "MANAGER"}
    # Off while other rows remain is allowed even though the server flag is off.
    fake = setup_cli(
        monkeypatch, GetGrokBotAgentAccess=ACCESS, UpdateGrokBotAgentAccess=ACCESS
    )
    assert cli.main(["share", "Alpha", "--team-row", "off", "--yes"]) == 0
    assert [next(iter(row)) for row in update(fake)] == ["userId", "groupId"]
    capsys.readouterr()


def test_team_row_on_without_role_keeps_a_manager_row(monkeypatch, capsys):
    manager_team = {
        **ACCESS,
        "state": {
            **ACCESS["state"],
            "principals": [
                {"team": {}, "role": ROLE + "MANAGER"},
                {"userId": 2, "role": ROLE + "USER"},
            ],
        },
    }
    fake = setup_cli(
        monkeypatch,
        GetGrokBotAgentAccess=manager_team,
        UpdateGrokBotAgentAccess=manager_team,
    )
    assert (
        cli.main(
            ["share", "Alpha", "--team-row", "on", "--grant", "user:2=manager", "--yes"]
        )
        == 0
    )
    assert update(fake)[0] == {"team": {}, "role": ROLE + "MANAGER"}
    assert update(fake)[1] == {"userId": 2, "role": ROLE + "MANAGER"}


def test_the_last_row_cannot_be_turned_off(monkeypatch, capsys):
    only_team = {
        **ACCESS,
        "state": {
            **ACCESS["state"],
            "principals": [{"team": {}, "role": ROLE + "USER"}],
        },
    }
    fake = setup_cli(monkeypatch, GetGrokBotAgentAccess=only_team)
    assert cli.main(["share", "Alpha", "--team-row", "off", "--yes"]) == 1
    assert "cannot be turned off" in capsys.readouterr().err
    assert writes(fake) == []


def test_no_change_sends_nothing(monkeypatch, capsys):
    fake = setup_cli(monkeypatch, GetGrokBotAgentAccess=ACCESS)
    assert (
        cli.main(["share", "Alpha", "--grant", "group:7=manager", "--yes", "--json"])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["changed"] is False
    assert writes(fake) == []


@pytest.mark.parametrize(
    "argv,message",
    [
        (["--grant", "user:12"], "--grant KIND"),
        (["--grant", "user=user"], "take an id"),
        (["--grant", "team:1=user"], "take no id"),
        (["--grant", "team=user"], "--team-row on"),
        (["--grant", "user:12=owner"], "ROLE user or manager"),
        (["--grant", "robot:1=user"], "Not an access row"),
        (["--grant", "user:99999999999=user"], "at most"),
        (["--revoke", "team"], "--team-row off"),
        (["--revoke", "user"], "take an id"),
        (["--grant", "user:1=user", "--revoke", "user:1"], "granted and revoked"),
        (["--role", "manager"], "--team-row on"),
        (["--team-row", "off", "--role", "user"], "--team-row on"),
        (["--language", "en"], "--invite"),
        (["--carry-secret", "A"], "--clone-to-team"),
        (
            ["--invite", "a@example.invalid", "--language", "english now"],
            "language tag",
        ),
        (["--team-visible", "--clone-to-team"], "one action"),
        (["--team-row", "on", "--invite", "a@example.invalid"], "one action"),
        (["--add-manager", "abc"], "invalid int"),
        (["--invite", "not-an-email"], "valid email"),
        (["--add-manager", "0"], "positive"),
        (["--revoke", "user:77"], "does not have access"),
    ],
)
def test_bad_options_send_nothing(monkeypatch, capsys, argv, message):
    fake = setup_cli(monkeypatch)
    assert cli.main(["share", "Alpha", *argv, "--yes"]) == 1
    assert message in capsys.readouterr().err
    assert writes(fake) == []


def test_bot_is_required_except_for_invite_codes(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    assert cli.main(["share", "--team-visible", "--yes"]) == 1
    assert "Specify BOT" in capsys.readouterr().err
    stdin(monkeypatch, CODE + "\n")
    assert cli.main(["share", "Alpha", "--preview-invite"]) == 1
    assert "take no BOT" in capsys.readouterr().err
    assert fake.calls == []


def test_team_visible_updated(monkeypatch, capsys):
    fake = setup_cli(monkeypatch, SetGrokBotAgentVisibility={"outcome": "UPDATED"})
    argv = [
        "share",
        "Alpha",
        "--team-visible",
        "--carry-secret",
        "A",
        "B",
        "--yes",
        "--json",
    ]
    assert cli.main(argv) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["outcome"] == "updated"
    assert "now visible" in data["message"].lower()
    assert sent(fake, "SetGrokBotAgentVisibility") == [
        {
            "agentId": "gateway",
            "visibility": "GROK_BOT_AGENT_VISIBILITY_TEAM",
            "personalSecretNames": ["A", "B"],
        }
    ]


@pytest.mark.parametrize("outcome,expected", [("NO_TEAM", "no team"), ("BUSY", "busy")])
def test_a_refused_visibility_outcome_uses_the_error_channel(
    monkeypatch, capsys, outcome, expected
):
    fake = setup_cli(monkeypatch, SetGrokBotAgentVisibility={"outcome": outcome})
    assert cli.main(["share", "Alpha", "--team-visible", "--yes"]) == 1
    captured = capsys.readouterr()
    assert expected in captured.err.lower()
    assert captured.out == ""
    assert sent(fake, "SetGrokBotAgentVisibility")


def test_a_refused_visibility_outcome_json_is_an_error(monkeypatch, capsys):
    setup_cli(monkeypatch, SetGrokBotAgentVisibility={"outcome": "NO_TEAM"})
    assert cli.main(["share", "Alpha", "--team-visible", "--yes", "--json"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)["error"]
    assert error["message"] == sharing.sentence("no_team")
    assert error["exit_code"] == 1


def test_a_refused_single_change_exits_1_with_the_server_message(monkeypatch, capsys):
    setup_cli(
        monkeypatch,
        CloneGrokBotAgentToTeam=refusal("failed_precondition", "Join a team first."),
    )
    assert cli.main(["share", "Alpha", "--clone-to-team", "--yes"]) == 1
    captured = capsys.readouterr()
    assert captured.err.strip() == "Join a team first."
    assert captured.out == ""
    setup_cli(
        monkeypatch,
        UpdateGrokBotAgentAccess=refusal("permission_denied", "Only the owner."),
    )
    assert cli.main(["share", "Alpha", "--team-row", "off", "--yes", "--json"]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert error["message"] == "Only the owner." and error["exit_code"] == 1


def test_clone_and_in_place(monkeypatch, capsys):
    fake = setup_cli(
        monkeypatch,
        CloneGrokBotAgentToTeam={"outcome": "CLONED", "agent": {"agentId": "copy"}},
        ShareGrokBotAgentInPlace={"outcome": "STARTED"},
    )
    argv = [
        "share",
        "Alpha",
        "--clone-to-team",
        "--carry-secret",
        "A",
        "--carry-secret",
        "B",
        "C",
    ]
    assert cli.main([*argv, "--yes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "outcome": "cloned",
        "message": sharing.sentence("cloned"),
        "agent_id": "copy",
    }
    assert sent(fake, "CloneGrokBotAgentToTeam") == [
        {"agentId": "gateway", "personalSecretNames": ["A", "B", "C"]}
    ]
    assert cli.main(["share", "Alpha", "--share-in-place", "--yes"]) == 0
    assert sharing.sentence("started") in capsys.readouterr().out
    fake.rpcs["ShareGrokBotAgentInPlace"] = {"outcome": "INELIGIBLE"}
    assert cli.main(["share", "Alpha", "--share-in-place", "--yes"]) == 1
    captured = capsys.readouterr()
    assert sharing.sentence("ineligible") in captured.err
    assert captured.out == ""


@pytest.mark.parametrize("json_mode", [False, True])
def test_share_status_is_one_read_and_needs_no_yes(monkeypatch, capsys, json_mode):
    fake = setup_cli(
        monkeypatch,
        GetGrokBotAgentInPlaceShareStatus={"state": "RUNNING", "step": "GRANTS"},
    )
    stdin(monkeypatch, "", tty=False)
    assert (
        cli.main(
            ["share", "Alpha", "--share-status", *(["--json"] if json_mode else [])]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert len(sent(fake, "GetGrokBotAgentInPlaceShareStatus")) == 1
    if json_mode:
        assert (
            json.loads(out)["state"] == "running"
            and json.loads(out)["step"] == "grants"
        )
    else:
        assert "running" in out and "grants" in out
    fake.rpcs["GetGrokBotAgentInPlaceShareStatus"] = ConnectError(
        404, '{"code":"not_found"}'
    )
    assert cli.main(["share", "Alpha", "--share-status"]) == 0
    assert "not been started" in capsys.readouterr().out
    fake.rpcs["GetGrokBotAgentInPlaceShareStatus"] = {
        "state": "FAILED",
        "failureReason": "disk full",
    }
    assert cli.main(["share", "Alpha", "--share-status"]) == 0
    assert "disk full" in capsys.readouterr().out
    fake.rpcs["GetGrokBotAgentInPlaceShareStatus"] = refusal(
        "permission_denied", "Not yours."
    )
    assert cli.main(["share", "Alpha", "--share-status"]) == 1
    assert capsys.readouterr().err.strip() == "Not yours."


def test_invites_never_show_the_link(monkeypatch, capsys):
    fake = setup_cli(
        monkeypatch,
        CreateGrokBotAgentAccessInvite={
            "invite": {"email": "new@example.invalid", "expiresAtMs": "1802592000000"},
            "inviteCreated": True,
            "inviteUrl": URL,
            "graceMs": "60000",
            "capUsage": {"used": 2, "limit": 10},
            "inviteEmailSent": True,
        },
    )
    argv = [
        "share",
        "Alpha",
        "--invite",
        "new@example.invalid",
        "--language",
        "pt-BR",
        "--yes",
    ]
    assert cli.main(argv) == 0
    text = capsys.readouterr()
    assert "created" in text.out and "email sent" in text.out
    assert (
        "expires 2027-02-14" in text.out.lower() and "2 of 10 invites used" in text.out
    )
    assert sent(fake, "CreateGrokBotAgentAccessInvite") == [
        {
            "agentId": "gateway",
            "email": "new@example.invalid",
            "sendEmail": True,
            "language": "pt-BR",
        }
    ]
    assert cli.main([*argv, "--json"]) == 0
    json_out = capsys.readouterr()
    data = json.loads(json_out.out)
    assert data == {
        "email": "new@example.invalid",
        "created": True,
        "email_sent": True,
        "expires_at_ms": 1802592000000,
        "grace_ms": 60000,
        "cap_usage": {"used": 2, "limit": 10},
    }
    assert URL not in text.out + text.err + json_out.out + json_out.err
    assert CODE not in text.out + text.err + json_out.out + json_out.err


def test_revoke_invite_and_managers(monkeypatch, capsys):
    fake = setup_cli(
        monkeypatch,
        RevokeGrokBotAgentAccessInvite={
            "revokedCount": 2,
            "capUsage": {"used": 0, "limit": 10},
        },
    )
    assert (
        cli.main(
            [
                "share",
                "Alpha",
                "--revoke-invite",
                "a@example.invalid",
                "--yes",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {
        "revoked_count": 2,
        "cap_usage": {"used": 0, "limit": 10},
    }
    assert sent(fake, "RevokeGrokBotAgentAccessInvite") == [
        {"agentId": "gateway", "email": "a@example.invalid"}
    ]
    assert cli.main(["share", "Alpha", "--add-manager", "12", "--yes"]) == 0
    assert "Manager 12 added" in capsys.readouterr().out
    assert (
        cli.main(["share", "Alpha", "--remove-manager", "12", "--yes", "--json"]) == 0
    )
    assert json.loads(capsys.readouterr().out) == {"user_id": 12, "removed": True}
    assert sent(fake, "AddGrokBotAgentManager") == [
        {"agentId": "gateway", "userId": 12}
    ]
    assert sent(fake, "RemoveGrokBotAgentManager") == [
        {"agentId": "gateway", "userId": 12}
    ]


PREVIEW = {
    "found": True,
    "recipientMatch": "MATCHES",
    "sender": {"displayName": "Pat Doe"},
    "invites": [
        {
            "bot": {"agentId": "bot-1", "name": "Helper"},
            "role": "manager",
            "state": "OPEN",
            "expiresAtMs": "1802592000000",
        }
    ],
    "eligibility": {"eligible": True},
}


@pytest.mark.parametrize("tty", [False, True])
@pytest.mark.parametrize("raw", [CODE, LINK])
def test_preview_reads_the_code_from_the_hidden_prompt(monkeypatch, capsys, tty, raw):
    fake = setup_cli(monkeypatch, PreviewGrokBotAgentAccessInvite=PREVIEW)
    stream = stdin(monkeypatch, raw + "\nsecond-line\n", tty=tty)
    prompts = []
    monkeypatch.setattr(
        getpass, "getpass", lambda prompt: prompts.append(prompt) or raw
    )
    assert cli.main(["share", "--preview-invite"]) == 0
    out = capsys.readouterr()
    assert len(prompts) == (1 if tty else 0)
    assert sent(fake, "PreviewGrokBotAgentAccessInvite") == [{"code": CODE}]
    assert (
        "Invite from Pat Doe" in out.out
        and "Helper" in out.out
        and "role manager" in out.out
    )
    assert "Ready to accept" in out.out and "You can accept this invite." in out.out
    assert CODE not in out.out + out.err and "grokbot://" not in out.out + out.err
    if not tty:
        assert stream.readline() == "second-line\n"
    assert [name for _, name, _ in fake.calls] == ["PreviewGrokBotAgentAccessInvite"]


def test_preview_json_and_not_found(monkeypatch, capsys):
    setup_cli(monkeypatch, PreviewGrokBotAgentAccessInvite=PREVIEW)
    stdin(monkeypatch, LINK + "\n")
    assert cli.main(["share", "--preview-invite", "--json"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["found"] is True and data["recipient_match"] == "matches"
    assert (
        data["items"][0]["bot_name"] == "Helper"
        and data["eligibility"]["eligible"] is True
    )
    assert CODE not in out
    setup_cli(monkeypatch, PreviewGrokBotAgentAccessInvite={})
    stdin(monkeypatch, CODE + "\n")
    assert cli.main(["share", "--preview-invite"]) == 1
    assert "not found" in capsys.readouterr().out
    setup_cli(
        monkeypatch,
        PreviewGrokBotAgentAccessInvite={
            **PREVIEW,
            "eligibility": {"eligible": False, "reason": "NO_SUBSCRIPTION"},
            "recipientMatch": "DOES_NOT_MATCH",
        },
    )
    stdin(monkeypatch, CODE + "\n")
    assert cli.main(["share", "--preview-invite"]) == 0
    out = capsys.readouterr().out
    assert "different email address" in out and "need a Grok Bot subscription" in out


def test_an_empty_prompt_and_an_unhideable_terminal(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    stdin(monkeypatch, "\n")
    assert cli.main(["share", "--preview-invite"]) == 1
    assert "No invite code" in capsys.readouterr().err
    stdin(monkeypatch, "", tty=True)

    def cannot_hide(prompt):
        import warnings

        warnings.warn("echo", getpass.GetPassWarning, stacklevel=1)
        return CODE

    monkeypatch.setattr(getpass, "getpass", cannot_hide)
    assert cli.main(["share", "--preview-invite"]) == 1
    assert "cannot hide input" in capsys.readouterr().err
    assert fake.calls == []


def test_the_code_never_reaches_an_error_message(monkeypatch, capsys):
    setup_cli(
        monkeypatch,
        PreviewGrokBotAgentAccessInvite=refusal(
            "invalid_argument", f"Bad code {CODE}."
        ),
        AcceptGrokBotAgentAccessInvite=ConnectError(500, f"upstream {LINK} failed"),
    )
    stdin(monkeypatch, LINK + "\n")
    assert cli.main(["share", "--preview-invite"]) == 1
    err = capsys.readouterr().err
    assert CODE not in err and "[redacted]" in err
    stdin(monkeypatch, LINK + "\n")
    assert cli.main(["share", "--accept-invite", "--yes", "--json"]) == 1
    err = capsys.readouterr().err
    assert CODE not in err and "grokbot://" not in err


def test_accept_needs_yes_and_leaves_stdin_alone(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    stream = stdin(monkeypatch, CODE + "\n", tty=False)
    assert cli.main(["share", "--accept-invite"]) == 1
    assert "--yes" in capsys.readouterr().err
    assert fake.calls == [] and stream.readline() == CODE + "\n"


@pytest.mark.parametrize("json_mode", [False, True])
def test_accept(monkeypatch, capsys, json_mode):
    fake = setup_cli(monkeypatch)
    stdin(monkeypatch, LINK + "\n")
    assert (
        cli.main(
            ["share", "--accept-invite", "--yes", *(["--json"] if json_mode else [])]
        )
        == 0
    )
    out = capsys.readouterr()
    assert sent(fake, "AcceptGrokBotAgentAccessInvite") == [{"code": CODE}]
    if json_mode:
        data = json.loads(out.out)
        assert data["status"] == "redeemed"
        assert data["items"][0]["outcome"] == "granted"
    else:
        assert (
            "Invite accepted." in out.out
            and "Shared helper: Access granted." in out.out
        )
    assert CODE not in out.out + out.err
    fake.rpcs["AcceptGrokBotAgentAccessInvite"] = {"status": "RECIPIENT_MISMATCH"}
    stdin(monkeypatch, CODE + "\n")
    assert cli.main(["share", "--accept-invite", "--yes"]) == 1
    assert "different email address" in capsys.readouterr().out


def test_share_flags_are_documented():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "docs/gbot.md").read_text(
        encoding="utf-8"
    )
    section = text.split("## share", 1)[1].split("\n## ", 1)[0]
    for flag in (
        "--grant",
        "--revoke",
        "--team-row",
        "--role",
        "--team-visible",
        "--share-in-place",
        "--share-status",
        "--clone-to-team",
        "--carry-secret",
        "--invite",
        "--language",
        "--revoke-invite",
        "--add-manager",
        "--remove-manager",
        "--preview-invite",
        "--accept-invite",
        "--yes",
        "--json",
    ):
        assert flag in section, flag
