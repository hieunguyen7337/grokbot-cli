import json

import pytest

from gbot.service import channels as c
from gbot.service.transport import FakeTransport
from groken.client import ConnectError


@pytest.mark.parametrize(
    "value", [3, "connected", "CONNECTED", "GROK_BOT_SLACK_INSTALL_STATUS_CONNECTED"]
)
def test_status_forms(value):
    t = FakeTransport(rpcs={c.RPCS[0]: {"status": value}})
    assert c.slack_state(t, "gateway-id").status == "connected"
    assert t.calls == [("rpc", c.RPCS[0], {"agentId": "gateway-id"})]


@pytest.mark.parametrize("value", [None, 99, -1, "future", True])
def test_unknown(value):
    assert (
        c.slack_state(FakeTransport(rpcs={c.RPCS[0]: {"status": value}}), "b").status
        == "unknown"
    )


def test_error_mapping():
    t = FakeTransport(
        rpcs={c.RPCS[0]: ConnectError(400, json.dumps({"code": "not_found"}))}
    )
    assert c.slack_state(t, "b").status == "not_connected"
    reason = "Texting a bot is not available yet."
    denied = ConnectError(
        403, json.dumps({"code": "permission_denied", "message": reason})
    )
    t.rpcs.update({c.RPCS[5]: denied, c.RPCS[7]: denied})
    assert c.messaging_link(t) == c.MessagingLink(False, reason)
    assert c.linked_phones(t) == ()
    t.rpcs[c.RPCS[0]] = ConnectError(500, "broken")
    with pytest.raises(ConnectError):
        c.slack_state(t, "b")


SENTENCES = {
    "unspecified": "Slack did not complete the request.",
    "unknown": "Slack did not complete the request.",
    "pending_admin_approval": "Waiting for a Slack admin to approve the app.",
    "not_connected": "Connect your Slack account first.",
    "workspace_required": "Choose a Slack workspace first.",
    "manager_reauth_required": "Reconnect your Slack account first.",
    "insufficient_scopes": "Reconnect Slack to grant the required permissions.",
    "install_conflict": "A Slack app is already installed in another workspace.",
    "ratelimited": "Slack rate limit reached. Try again in 42 seconds.",
    "slack_rejected": "Slack rejected the request: denied.",
    "unsupported_harness": "This bot does not support Slack.",
    "not_published": "Publish this bot before connecting Slack.",
    "workspace_not_allowed": "This Slack workspace is not allowed.",
    "recreate_required": "Recreate the Slack app by installing it again.",
    "throttled": "Slack app updates are temporarily throttled. Try again later.",
}


@pytest.mark.parametrize(
    "kind,method,action",
    [
        ("INSTALL", c.RPCS[2], c.install_slack),
        ("REINSTALL", c.RPCS[3], c.reinstall_slack),
        ("CONNECT", c.RPCS[1], c.start_slack_connect),
        ("UNINSTALL", c.RPCS[4], c.uninstall_slack),
    ],
)
def test_all_outcomes(kind, method, action):
    names = c._ENUMS[kind + "_OUTCOME"].split()
    for index, name in enumerate(names):
        for value in (index, name, f"GROK_BOT_SLACK_{kind}_OUTCOME_{name.upper()}"):
            t = FakeTransport(
                rpcs={
                    method: {
                        "outcome": value,
                        "retryAfterSeconds": 42,
                        "slackError": "denied",
                        "oauthAuthorizeUrl": "https://example.test",
                    }
                }
            )
            outcome, url, sentence = action(t, "b")
            assert outcome == name and url == "https://example.test"
            assert sentence == SENTENCES.get(name, "")


def test_requests_and_sms():
    t = FakeTransport(c.DEMO_COMMANDS, c.DEMO_RPCS)
    c.start_slack_connect(t, "b")
    c.install_slack(t, "b", "team")
    c.reinstall_slack(t, "b")
    c.uninstall_slack(t, "b")
    assert [p for _, _, p in t.calls] == [
        {"agentId": "b", "returnToMobileApp": False},
        {
            "agentId": "b",
            "slackTeamId": "team",
            "replaceExistingApp": False,
            "approvalRequestResubmitted": False,
        },
        {"agentId": "b", "automatic": False},
        {"agentId": "b", "forgetIfUnreachable": False},
    ]
    link = c.issue_link_code(t)
    assert link.pending_code == (
        "DEMO",
        1800000600000,
        "Link DEMO",
        "sms:+15550100?body=Link%20DEMO",
    )
    t.rpcs[c.RPCS[5]] = {"lineNumber": "line", "pendingCode": c.DEMO_RPCS[c.RPCS[6]]}
    assert c.messaging_link(t).pending_code == link.pending_code
    t.rpcs[c.RPCS[7]] = {
        "phones": [
            {
                "handleId": "h",
                "address": "phone",
                "linkedAtMs": "1",
                "lastSeenAtMs": "2",
            }
        ]
    }
    assert c.linked_phones(t) == (c.LinkedPhone("h", "phone", 1, 2),)
    c.unlink_phone(t, "h")
    assert t.calls[-1][2] == {"handleId": "h"}


def test_listener_and_completion_checks():
    t = FakeTransport(c.DEMO_COMMANDS, c.DEMO_RPCS)
    before = c.slack_state(t, "b")
    check = c.slack_check(t, "b", before)
    assert check() is None
    t.rpcs[c.RPCS[0]] = {**c.DEMO_RPCS[c.RPCS[0]], "pendingReinstallApproval": True}
    changed = check()
    assert changed is not None and changed.pending_reinstall_approval
    check_listener = c.listener_check(t, "github")
    assert check_listener() is None
    t.commands["getListenerIntegrations"] = {
        "integrations": [
            {
                "platform": "github",
                "state": "listening",
                "isConnected": True,
                "neededByCount": 3,
                "detail": "Ready",
                "grantedRepos": ["org/repo"],
                "scopeIssues": [{"kind": "not-found", "scope": "old"}],
            }
        ]
    }
    row = check_listener()
    assert row == c.Integration(
        "github",
        True,
        3,
        "listening",
        "Ready",
        ("org/repo",),
        ({"kind": "not-found", "scope": "old"},),
    )
    assert c.listener_connect_url(t, "github") == "https://example.test/listener"
    assert t.calls[-1] == ("command", "getListenerConnectUrl", {"platform": "github"})
