import json

import pytest

from gbot import cli, context
from gbot.service import account
from gbot.service.transport import FakeTransport
from groken.client import ConnectError

SESSION = "cli-session-secret-42"
VAULT_CARD = "cli-vault-card-secret-9"
READS = {
    "GetGrokBotEgressPolicy",
    "GetGrokBotAgentAnalytics",
    "GetGrokBotDefaultPaymentMethod",
    "ListGrokBotStripeLinkPaymentMethods",
    "SuggestGrokBotAddresses",
    "ResolveGrokBotAddress",
}


def setup_cli(monkeypatch):
    fake = FakeTransport(
        {"listAgents": [{"id": "gateway", "name": "Alpha"}]}, {**account.DEMO_RPCS}
    )
    monkeypatch.setattr(context, "manager_factory", lambda: fake)

    class Backend:
        def unary(self, service, name, payload):
            return fake.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    monkeypatch.setattr(account, "new_session_token", lambda: SESSION)
    return fake


def _analytics() -> dict[str, object]:
    return {
        "weeklyActiveUsers": 2,
        "totalMinutesSaved": 4.0,
        "minutesSavedMeasured": False,
        "days": [
            {
                "day": "2026-10-31",
                "activeUsers": 2,
                "trailingSevenDayActiveUsers": 2,
                "userTurns": 5,
                "minutesSaved": 1.0,
            }
        ],
        "topUsers": [
            {
                "userId": 3,
                "displayName": "Ada",
                "userTurns": 5,
                "minutesSaved": 1.0,
                "isExternal": False,
                "activeDays": 1,
            }
        ],
    }


def test_egress_open_and_restricted(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    fake.rpcs["GetGrokBotEgressPolicy"] = {}
    assert cli.main(["account", "egress"]) == 0
    assert capsys.readouterr().out == (
        "Mode: Open\nNo outbound network restriction is set.\n"
    )
    assert cli.main(["account", "egress", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "restricted": False,
        "allowed_domains": [],
        "allowed_tcp": [],
    }
    fake.rpcs["GetGrokBotEgressPolicy"] = {
        "restricted": True,
        "allowedDomains": ["example.com"],
        "allowedTcpDestinations": [{"cidr": "10.0.0.0/8", "port": 443}],
    }
    assert cli.main(["account", "egress"]) == 0
    out = capsys.readouterr().out
    assert "Mode: Restricted" in out
    assert "example.com" in out
    assert "10.0.0.0/8 port 443" in out
    assert cli.main(["account", "egress", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["allowed_tcp"] == [
        {"cidr": "10.0.0.0/8", "port": 443}
    ]


def test_refused_egress_is_the_servers_message(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    fake.rpcs["GetGrokBotEgressPolicy"] = ConnectError(
        400, '{"code":"failed_precondition","message":"Egress is not set up."}'
    )
    assert cli.main(["account", "egress"]) == 1
    captured = capsys.readouterr()
    assert "Egress is not set up." in captured.err
    assert captured.out == ""
    assert cli.main(["account", "egress", "--json"]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert error["message"] == "Egress is not set up."
    assert error["exit_code"] == 1


def test_analytics_text_json_and_not_found(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    fake.rpcs["GetGrokBotAgentAnalytics"] = _analytics()
    assert cli.main(["account", "analytics", "Alpha"]) == 0
    out = capsys.readouterr().out
    assert "Weekly active users: 2" in out
    assert "Minutes saved: Not measured" in out
    assert "2026-10-31: active 2, turns 5, minutes saved Not measured" in out
    assert fake.calls[-1] == (
        "rpc",
        "GetGrokBotAgentAnalytics",
        {"agentId": "gateway"},
    )
    assert cli.main(["account", "analytics", "Alpha", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["weekly_active_users"] == 2
    assert data["top_users"][0]["display_name"] == "Ada"
    fake.rpcs["GetGrokBotAgentAnalytics"] = ConnectError(404, '{"code":"not_found"}')
    assert cli.main(["account", "analytics", "Alpha"]) == 0
    assert capsys.readouterr().out == "No analytics yet.\n"
    assert cli.main(["account", "analytics", "Alpha", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) is None


def test_payment_label_without_the_vault_secret(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    fake.rpcs["GetGrokBotDefaultPaymentMethod"] = {
        "method": {"vaultCardId": VAULT_CARD}
    }
    fake.rpcs["ListGrokBotStripeLinkPaymentMethods"] = {
        "outcome": 1,
        "paymentMethods": [{"id": VAULT_CARD, "brand": "Visa", "last4": "4242"}],
    }
    assert cli.main(["account", "payment"]) == 0
    out = capsys.readouterr().out
    assert out == (
        "Visa ending 4242\nChange the default payment method in the Grok Bot app.\n"
    )
    assert cli.main(["account", "payment", "--json"]) == 0
    raw = capsys.readouterr().out
    assert json.loads(raw) == {
        "kind": "card",
        "wallet": "",
        "label": "Visa ending 4242",
    }
    assert VAULT_CARD not in raw
    fake.rpcs["GetGrokBotDefaultPaymentMethod"] = {}
    assert cli.main(["account", "payment"]) == 0
    assert capsys.readouterr().out.startswith("No default payment method.\n")


def _address_rpcs(fake):
    fake.rpcs["SuggestGrokBotAddresses"] = {
        "outcome": 1,
        "suggestions": [
            {"id": "one", "title": "1 Main St", "subtitle": "Town, CA"},
            {"id": "two", "title": "2 Main St", "subtitle": ""},
        ],
    }
    fake.rpcs["ResolveGrokBotAddress"] = lambda args: {
        "parts": {
            "street": f"Street for {args['id']}",
            "city": "Town",
            "state": "CA",
            "postalCode": "90001",
            "country": "United States",
            "countryCode": "US",
            "formatted": f"Formatted {args['id']}, Town, CA",
        }
    }


def test_address_lists_then_picks_in_the_same_session(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    _address_rpcs(fake)
    assert cli.main(["account", "address", "main st"]) == 0
    out = capsys.readouterr().out
    assert "1. 1 Main St, Town, CA" in out
    assert "2. 2 Main St" in out
    assert SESSION not in out
    assert cli.main(["account", "address", "main st", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["suggestions"][1] == {
        "index": 2,
        "title": "2 Main St",
        "subtitle": "",
    }
    assert cli.main(["account", "address", "main st", "--pick", "2", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["formatted"] == "Formatted two, Town, CA"
    assert data["postal_code"] == "90001"
    payloads = [
        payload
        for _, name, payload in fake.calls
        if name in {"SuggestGrokBotAddresses", "ResolveGrokBotAddress"}
    ]
    assert {payload["sessionToken"] for payload in payloads} == {SESSION}
    assert payloads[-1] == {"id": "two", "sessionToken": SESSION}


def test_address_pick_errors_and_unavailable(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    _address_rpcs(fake)
    assert cli.main(["account", "address", "main st", "--pick", "9"]) == 1
    assert "Pick a number from 1 to 2." in capsys.readouterr().err
    fake.rpcs["SuggestGrokBotAddresses"] = {"outcome": 2}
    assert cli.main(["account", "address", "main st"]) == 0
    assert capsys.readouterr().out == "Address suggestions are unavailable.\n"
    assert cli.main(["account", "address", "main st", "--pick", "1"]) == 1
    assert "Address suggestions are unavailable." in capsys.readouterr().err
    fake.rpcs["SuggestGrokBotAddresses"] = ConnectError(500, "boom")
    assert cli.main(["account", "address", "main st"]) == 0
    assert "unavailable" in capsys.readouterr().out


def test_unresolved_pick_and_empty_query(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    _address_rpcs(fake)
    fake.rpcs["ResolveGrokBotAddress"] = {}
    assert cli.main(["account", "address", "main st", "--pick", "1"]) == 1
    assert "could not be resolved" in capsys.readouterr().err
    assert cli.main(["account", "address", "  "]) == 1
    assert "Enter an address" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["account", "egress"],
        ["account", "analytics", "Alpha"],
        ["account", "payment"],
        ["account", "address", "main st", "--pick", "1"],
    ],
)
def test_reads_send_no_changes_and_need_no_yes(monkeypatch, capsys, argv):
    fake = setup_cli(monkeypatch)
    _address_rpcs(fake)
    fake.rpcs["GetGrokBotAgentAnalytics"] = _analytics()
    assert cli.main(argv) == 0
    assert fake.calls
    assert {name for _, name, _ in fake.calls} <= READS | {"listAgents"}
