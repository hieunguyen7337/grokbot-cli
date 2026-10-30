import pytest

from gbot.service import teams
from gbot.service.transport import FakeTransport
from groken.client import ConnectError


@pytest.mark.parametrize(
    "names,field,prefix",
    [
        (teams.STATES, "state", "GROK_BOT_TEAMS_INSTALL_STATE"),
        (teams.CONSENTS, "consentResult", "GROK_BOT_TEAMS_CONSENT_RESULT"),
        (teams.REASONS, "reason", "GROK_BOT_TEAMS_BOT_STATUS_REASON"),
    ],
)
def test_enums(names, field, prefix):
    for number, name in enumerate(names):
        for value in (number, name.upper(), prefix + "_" + name.upper()):
            row = {field: value} if field != "reason" else {"botStatus": {field: value}}
            fake = FakeTransport(rpcs={"GetGrokBotTeamsInstallState": row})
            state = teams.install_state(fake, "gateway")
            if field == "reason":
                assert state.bot_status is not None
                actual = state.bot_status["reason"]
            else:
                actual = getattr(
                    state, "consent_result" if field == "consentResult" else field
                )
            assert actual == ("" if field == "consentResult" and number == 0 else name)
    assert teams._enum(999, names, prefix) == "unknown"
    assert teams._enum("future", names, prefix) == "unknown"


def test_missing_and_errors():
    for name, function in (
        ("GetGrokBotTeamsInstallState", teams.install_state),
        ("ListGrokBotTeamsJoinedTeams", teams.joined_teams),
    ):
        fake = FakeTransport(rpcs={name: ConnectError(404, '{"code":"not_found"}')})
        result = function(fake, "gateway")
        assert result == (
            teams.TeamsState("not_connected") if function == teams.install_state else ()
        )
        fake.rpcs[name] = ConnectError(403, "permission_denied")
        with pytest.raises(ConnectError):
            function(fake, "gateway")


def test_requests_and_shapes():
    fake = FakeTransport(
        rpcs={
            **teams.DEMO_RPCS,
            "DisconnectGrokBotTeamsAccount": {
                "revoked": True,
                "state": 2,
                "stillInstalledAgentIds": ["other"],
            },
        }
    )
    teams.install_state(fake, "gateway", nonce="n")
    teams.start_connect(fake, "gateway", admin=True)
    teams.install(
        fake,
        "gateway",
        tenant_id="tenant",
        team_ids=("a", "b"),
        personal=False,
        nonce="n",
    )
    teams.reinstall(fake, "gateway", nonce="n")
    teams.uninstall(fake, "gateway")
    teams.joined_teams(fake, "gateway")
    teams.add_to_team(fake, "gateway", "a", nonce="n")
    assert teams.disconnect(fake, "gateway", "tenant") == (
        True,
        "connected",
        ("other",),
    )
    assert teams.account_links(fake) == ()
    teams.start_account_link(fake, "tenant")
    assert teams.unlink_account(fake, "tenant") is False
    assert [payload for _, _, payload in fake.calls] == [
        {"agentId": "gateway", "consentNonce": "n"},
        {
            "agentId": "gateway",
            "requestAdminScopes": True,
            "grantScopeTeam": False,
            "forceAccountSelection": False,
        },
        {
            "agentId": "gateway",
            "tenantId": "tenant",
            "teamIds": ["a", "b"],
            "installPersonal": False,
            "consentNonce": "n",
        },
        {"agentId": "gateway", "consentNonce": "n"},
        {"agentId": "gateway"},
        {"agentId": "gateway"},
        {"agentId": "gateway", "teamId": "a", "consentNonce": "n"},
        {"agentId": "gateway", "tenantId": "tenant"},
        {},
        {"tenantHint": "tenant"},
        {"tenantId": "tenant"},
    ]


def test_sentences_and_fields():
    assert (
        teams.sentence("pending_admin_approval")
        == "Waiting for a Teams admin to approve the app."
    )
    for name in (*teams.STATES, *teams.CONSENTS, *teams.REASONS):
        assert teams.sentence(name).endswith(".")
        assert "could not complete" not in teams.sentence(name)
    assert teams.sentence("access_denied") != teams.sentence("grant_conflict")
    fake = FakeTransport(
        rpcs={
            "GetGrokBotTeamsInstallState": {
                "state": 4,
                "tenantId": "t",
                "tenantDisplayName": "Tenant",
                "managerIsAdmin": True,
                "installedTeams": [{"teamId": "one", "displayName": "One"}],
                "failureReason": "unavailable",
                "rejectionNote": "Please ask admin",
                "pollAfterMs": 123,
                "botStatus": {"reason": 6, "adminConsentUrl": "secret"},
            }
        }
    )
    state = teams.install_state(fake, "bot")
    assert (
        state.tenant_id,
        state.tenant_name,
        state.manager_is_admin,
        state.poll_after_ms,
    ) == ("t", "Tenant", True, 123)
    assert state.installed_teams[0]["displayName"] == "One"
    assert teams.sentence("unavailable") in state.messages
    assert "secret" not in str(state)


@pytest.mark.parametrize(
    "row", [{"consentResult": 2}, {"connectedAccount": {}}, {"terminal": True}]
)
def test_connect_completion(row):
    fake = FakeTransport(rpcs={"GetGrokBotTeamsInstallState": {}})
    check = teams.connect_check(fake, "gateway", "nonce")
    assert check() is None
    fake.rpcs["GetGrokBotTeamsInstallState"] = row
    assert isinstance(check(), teams.TeamsState)
    assert fake.calls[-1][2] == {"agentId": "gateway", "consentNonce": "nonce"}


def test_account_completion_new_tuple_only():
    row = {"tenantId": "t", "aadObjectId": "a", "linkedAtMs": "1"}
    fake = FakeTransport(rpcs={"GetMicrosoftTeamsAccountLinkStatus": {"links": [row]}})
    before = teams.account_links(fake)
    check = teams.account_link_check(fake, before)
    assert check() is None
    row["linkedAtMs"] = "2"
    assert check() == teams.AccountLink("t", "a", 2)


@pytest.mark.parametrize("admin", [False, True])
def test_start_connect_without_link_refuses(admin):
    transport = FakeTransport(
        rpcs={
            "StartGrokBotTeamsConnect": {
                "consentUrl": "" if not admin else "https://example.invalid/c",
                "adminConsentUrl": "" if admin else "https://example.invalid/a",
                "nonce": "n",
            },
            "StartMicrosoftTeamsAccountLink": {},
        }
    )
    with pytest.raises(ValueError, match="sign-in link"):
        teams.start_connect(transport, "bot", admin=admin)
    with pytest.raises(ValueError, match="sign-in link"):
        teams.start_account_link(transport)
