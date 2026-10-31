import uuid

import pytest

from gbot.service import account as service
from gbot.service.errors import Refusal
from gbot.service.fake import load_fake
from gbot.service.transport import FakeTransport
from groken.client import ConnectError

VAULT_CARD = "vault-card-secret-7731"
SESSION = "session-secret-0a1b"


def _method(fake: FakeTransport) -> service.DefaultPaymentMethod:
    value = service.default_payment_method(fake)
    assert isinstance(value, service.DefaultPaymentMethod)
    return value


def _vault(card_id: str = VAULT_CARD) -> dict[str, object]:
    return {
        "outcome": 1,
        "paymentMethods": [
            {"id": card_id, "brand": "Visa", "last4": "4242", "kind": 1},
            {"id": "other", "brand": "Amex", "last4": "0005", "kind": 1},
        ],
    }


def test_egress_open_restricted_and_refused():
    fake = FakeTransport(rpcs={"GetGrokBotEgressPolicy": {}})
    assert service.egress_policy(fake) == service.EgressPolicy(restricted=False)
    fake.rpcs["GetGrokBotEgressPolicy"] = {
        "restricted": True,
        "allowedDomains": ["example.com"],
        "allowedTcpDestinations": [{"cidr": "10.0.0.0/8", "port": 443}],
    }
    assert service.egress_policy(fake) == service.EgressPolicy(
        True, ("example.com",), (("10.0.0.0/8", 443),)
    )
    assert fake.calls[-1] == ("rpc", "GetGrokBotEgressPolicy", {})
    fake.rpcs["GetGrokBotEgressPolicy"] = ConnectError(
        400, '{"code":"failed_precondition","message":"Egress is not set up."}'
    )
    assert service.egress_policy(fake) == Refusal(
        "failed_precondition", "Egress is not set up."
    )
    fake.rpcs["GetGrokBotEgressPolicy"] = ConnectError(500, "upstream exploded")
    with pytest.raises(ConnectError):
        service.egress_policy(fake)


def test_egress_odd_shapes_read_safely():
    fake = FakeTransport(
        rpcs={
            "GetGrokBotEgressPolicy": {
                "restricted": "yes",
                "allowedDomains": "example.com",
                "allowedTcpDestinations": [
                    "junk",
                    {"cidr": 7, "port": "x"},
                ],
                "extra": {"ignored": True},
            }
        }
    )
    assert service.egress_policy(fake) == service.EgressPolicy(False, (), (("", 0),))
    assert service.egress_lines(service.EgressPolicy(True)) == (
        "Allowed domains:",
        "No domains are allowed.",
        "",
        "Allowed TCP destinations:",
        "No TCP destinations are allowed.",
    )
    assert service.egress_lines(service.EgressPolicy(False)) == (
        "No outbound network restriction is set.",
    )


def _analytics_reply() -> dict[str, object]:
    return {
        "weeklyActiveUsers": 2,
        "totalMinutesSaved": 12.5,
        "days": [
            {
                "day": "2026-10-30",
                "activeUsers": 1,
                "trailingSevenDayActiveUsers": 2,
                "userTurns": 3,
                "minutesSaved": 4.0,
            },
            {
                "day": "2026-10-31",
                "activeUsers": 2,
                "trailingSevenDayActiveUsers": 2,
                "userTurns": 5,
                "minutesSaved": "2.5",
            },
        ],
        "minutesSavedBeforeWindow": 6,
        "topUsers": [
            {
                "userId": 7,
                "displayName": "Ada",
                "userTurns": 9,
                "minutesSaved": 6.0,
                "isExternal": True,
                "activeDays": 4,
            }
        ],
        "minutesSavedMeasured": True,
        "topUsersByWindow": [
            {
                "windowDays": 7,
                "topUsers": [
                    {
                        "userId": 7,
                        "displayName": "Ada",
                        "userTurns": 9,
                        "minutesSaved": 6.0,
                        "isExternal": True,
                        "activeDays": 4,
                    }
                ],
            }
        ],
    }


def test_analytics_full_reply_and_payload():
    fake = FakeTransport(rpcs={"GetGrokBotAgentAnalytics": _analytics_reply()})
    value = service.analytics(fake, "gateway")
    assert isinstance(value, service.Analytics)
    assert value.weekly_active_users == 2
    assert value.total_minutes_saved == 12.5
    assert value.minutes_saved_measured is True
    assert value.minutes_saved_before_window == 6.0
    assert value.days[1] == service.Day("2026-10-31", 2, 2, 5, 2.5)
    assert value.top_users == (service.TopUser(7, "Ada", 9, 6.0, True, 4),)
    assert value.top_users_by_window[0].window_days == 7
    assert fake.calls[-1] == (
        "rpc",
        "GetGrokBotAgentAnalytics",
        {"agentId": "gateway"},
    )
    assert [day.day for day in service.recent_days(value)] == [
        "2026-10-31",
        "2026-10-30",
    ]


def test_analytics_partial_and_not_measured():
    fake = FakeTransport(rpcs={"GetGrokBotAgentAnalytics": {"weeklyActiveUsers": "3"}})
    value = service.analytics(fake, "gateway")
    assert isinstance(value, service.Analytics)
    assert value == service.Analytics(
        weekly_active_users=3,
        total_minutes_saved=0.0,
        minutes_saved_measured=False,
        minutes_saved_before_window=0.0,
        days=(),
        top_users=(),
        top_users_by_window=(),
    )
    assert service.minutes_label(False, 9.0) == "Not measured"
    assert service.minutes_label(True, 9.0) == "9.0"
    assert service.analytics_lines(value) == (
        "Last 14 days, latest first:",
        "No daily activity yet.",
        "",
        "Top users:",
        "No top users yet.",
    )


def test_analytics_not_found_is_none_and_refusals_are_notices():
    fake = FakeTransport(
        rpcs={"GetGrokBotAgentAnalytics": ConnectError(404, '{"code":"not_found"}')}
    )
    assert service.analytics(fake, "gateway") is None
    fake.rpcs["GetGrokBotAgentAnalytics"] = ConnectError(
        403, '{"code":"permission_denied","message":"Only owners can see this."}'
    )
    assert service.analytics(fake, "gateway") == Refusal(
        "permission_denied", "Only owners can see this."
    )


def test_analytics_lines_show_windows_and_users():
    value = service.analytics(
        FakeTransport(rpcs={"GetGrokBotAgentAnalytics": _analytics_reply()}),
        "gateway",
    )
    assert isinstance(value, service.Analytics)
    assert service.analytics_fields(value) == (
        ("Weekly active users", "2"),
        ("Minutes saved", "12.5"),
    )
    lines = service.analytics_lines(value)
    assert "2026-10-31: active 2, turns 5, minutes saved 2.5" in lines
    assert "Top users, last 7 days:" in lines
    assert "Ada (external): turns 9, minutes saved 6.0, active days 4" in lines


def test_payment_card_is_labelled_from_the_vault_and_secret_is_dropped():
    fake = FakeTransport(
        rpcs={
            "GetGrokBotDefaultPaymentMethod": {"method": {"vaultCardId": VAULT_CARD}},
            "ListGrokBotStripeLinkPaymentMethods": _vault(),
        }
    )
    method = service.default_payment_method(fake)
    assert method == service.DefaultPaymentMethod("card", "", "Visa ending 4242")
    assert VAULT_CARD not in repr(method)
    assert [name for _, name, _ in fake.calls] == [
        "GetGrokBotDefaultPaymentMethod",
        "ListGrokBotStripeLinkPaymentMethods",
    ]


def test_payment_card_without_a_vault_match_is_unlabelled():
    fake = FakeTransport(
        rpcs={
            "GetGrokBotDefaultPaymentMethod": {"method": {"vaultCardId": VAULT_CARD}},
            "ListGrokBotStripeLinkPaymentMethods": _vault("someone-else"),
        }
    )
    assert _method(fake).label == "A saved card"
    fake.rpcs["ListGrokBotStripeLinkPaymentMethods"] = ConnectError(
        403, '{"code":"permission_denied","message":"Vault is locked."}'
    )
    assert _method(fake).label == "Vault is locked."
    fake.rpcs["ListGrokBotStripeLinkPaymentMethods"] = ConnectError(500, "boom")
    assert _method(fake).label == "A saved card"


def test_overlong_digit_strings_read_as_zero_and_never_raise():
    huge = "9" * 5000
    assert service._int(huge) == 0
    assert service._enum(huge, "GROK_BOT_PAYMENT_WALLET", ("x_money",)) == "unknown"
    fake = FakeTransport(
        rpcs={
            "GetGrokBotAgentAnalytics": {
                "weeklyActiveUsers": huge,
                "topUsers": [{"userId": huge, "userTurns": huge}],
            },
            "GetGrokBotDefaultPaymentMethod": {"method": {"wallet": huge}},
        }
    )
    value = service.analytics(fake, "bot")
    assert isinstance(value, service.Analytics)
    assert value.weekly_active_users == 0
    assert value.top_users[0].user_id == 0 and value.top_users[0].user_turns == 0
    assert _method(fake) == service.DefaultPaymentMethod(
        "wallet", "unknown", "A wallet"
    )


@pytest.mark.parametrize(
    "wallet,kind,label",
    [
        (1, "x_money", "X Money"),
        ("GROK_BOT_PAYMENT_WALLET_X_MONEY", "x_money", "X Money"),
        ("x_money", "x_money", "X Money"),
        (2, "stripe_link", "Stripe Link"),
        ("STRIPE_LINK", "stripe_link", "Stripe Link"),
        (0, "unknown", "A wallet"),
        ("GROK_BOT_PAYMENT_WALLET_UNSPECIFIED", "unknown", "A wallet"),
        (99, "unknown", "A wallet"),
    ],
)
def test_wallet_enum_forms(wallet, kind, label):
    fake = FakeTransport(
        rpcs={"GetGrokBotDefaultPaymentMethod": {"method": {"wallet": wallet}}}
    )
    assert service.default_payment_method(fake) == service.DefaultPaymentMethod(
        "wallet", kind, label
    )


def test_payment_none_and_refusal():
    fake = FakeTransport(rpcs={"GetGrokBotDefaultPaymentMethod": {}})
    assert service.default_payment_method(fake) == service.DefaultPaymentMethod(
        "none", "", "No default payment method."
    )
    fake.rpcs["GetGrokBotDefaultPaymentMethod"] = {"method": {"vaultCardId": ""}}
    assert _method(fake).kind == "none"
    fake.rpcs["GetGrokBotDefaultPaymentMethod"] = ConnectError(
        403, '{"code":"permission_denied","message":"Not for you."}'
    )
    assert service.default_payment_method(fake) == Refusal(
        "permission_denied", "Not for you."
    )


@pytest.mark.parametrize(
    "outcome,expected",
    [
        (1, "suggested"),
        (2, "unavailable"),
        ("GROK_BOT_ADDRESS_LOOKUP_OUTCOME_SUGGESTED", "suggested"),
        ("unavailable", "unavailable"),
        (0, "unknown"),
        ("GROK_BOT_ADDRESS_LOOKUP_OUTCOME_FUTURE", "unknown"),
        (True, "unknown"),
    ],
)
def test_address_outcome_enum_forms(outcome, expected):
    fake = FakeTransport(
        rpcs={
            "SuggestGrokBotAddresses": {
                "outcome": outcome,
                "suggestions": [{"id": "a", "title": "1 Main", "subtitle": "Town"}],
            }
        }
    )
    actual, suggestions = service.suggest_addresses(fake, "main", SESSION)
    assert actual == expected
    assert bool(suggestions) is (expected == "suggested")


def test_address_suggestions_payload_and_odd_rows():
    fake = FakeTransport(
        rpcs={
            "SuggestGrokBotAddresses": {
                "outcome": "SUGGESTED",
                "suggestions": [
                    {"id": "one", "title": "1 Main", "subtitle": "Town"},
                    {"title": "no id"},
                    "junk",
                    {"id": "two"},
                ],
            }
        }
    )
    outcome, suggestions = service.suggest_addresses(fake, "main st", SESSION)
    assert outcome == "suggested"
    assert suggestions == (
        service.Suggestion("one", "1 Main", "Town"),
        service.Suggestion("two", "", ""),
    )
    assert fake.calls[-1] == (
        "rpc",
        "SuggestGrokBotAddresses",
        {"query": "main st", "sessionToken": SESSION},
    )


@pytest.mark.parametrize(
    "failure",
    [
        ConnectError(500, "boom"),
        ConnectError(403, '{"code":"permission_denied"}'),
        RuntimeError("timeout"),
    ],
)
def test_address_failures_read_as_unavailable(failure):
    fake = FakeTransport(rpcs={"SuggestGrokBotAddresses": failure})
    assert service.suggest_addresses(fake, "main", SESSION) == ("unavailable", ())


def test_resolve_parts_unresolved_and_refusal():
    parts = {
        "street": "1 Main St",
        "city": "Town",
        "state": "CA",
        "postalCode": "90001",
        "country": "United States",
        "countryCode": "US",
        "formatted": "1 Main St, Town, CA 90001, United States",
    }
    fake = FakeTransport(rpcs={"ResolveGrokBotAddress": {"parts": parts}})
    value = service.resolve_address(fake, "one", SESSION)
    assert isinstance(value, service.AddressParts)
    assert value == service.AddressParts(
        "1 Main St",
        "Town",
        "CA",
        "90001",
        "United States",
        "US",
        "1 Main St, Town, CA 90001, United States",
    )
    assert fake.calls[-1] == (
        "rpc",
        "ResolveGrokBotAddress",
        {"id": "one", "sessionToken": SESSION},
    )
    assert service.address_fields(value)[:2] == (
        ("Street", "1 Main St"),
        ("City", "Town"),
    )
    fake.rpcs["ResolveGrokBotAddress"] = {}
    assert service.resolve_address(fake, "one", SESSION) is None
    fake.rpcs["ResolveGrokBotAddress"] = ConnectError(
        403, '{"code":"permission_denied","message":"Sign in again."}'
    )
    assert service.resolve_address(fake, "one", SESSION) == Refusal(
        "permission_denied", "Sign in again."
    )


def test_same_session_token_for_suggest_and_resolve(monkeypatch):
    token = service.new_session_token()
    assert uuid.UUID(token).version == 4 and uuid.UUID(hex=token).hex == token
    monkeypatch.setattr(service, "new_session_token", lambda: SESSION)
    fake = load_fake().transport
    fake.rpcs["SuggestGrokBotAddresses"] = {
        "outcome": 1,
        "suggestions": [{"id": "x", "title": "1 Main"}],
    }
    outcome, suggestions = service.suggest_addresses(
        fake, "main", service.new_session_token()
    )
    service.resolve_address(fake, suggestions[0].id, SESSION)
    tokens = [
        payload["sessionToken"]
        for _, _, payload in fake.calls
        if "sessionToken" in payload
    ]
    assert outcome == "suggested" and tokens == [SESSION, SESSION]


def test_secrets_stay_out_of_reprs():
    fake = FakeTransport(
        rpcs={
            "GetGrokBotDefaultPaymentMethod": {"method": {"vaultCardId": VAULT_CARD}},
            "ListGrokBotStripeLinkPaymentMethods": _vault(),
            "SuggestGrokBotAddresses": {
                "outcome": 1,
                "suggestions": [{"id": "x", "title": "1 Main"}],
            },
            "ResolveGrokBotAddress": {"parts": {"formatted": "1 Main"}},
        }
    )
    outputs = [repr(service.default_payment_method(fake))]
    _, suggestions = service.suggest_addresses(fake, "main", SESSION)
    outputs.append(repr(suggestions))
    outputs.append(repr(service.resolve_address(fake, "x", SESSION)))
    for text in outputs:
        assert VAULT_CARD not in text and SESSION not in text


def test_demo_replies_cover_every_rpc():
    fake = load_fake()
    assert set(service.RPCS) <= fake.transport.rpcs.keys()
    analytics = service.analytics(fake.transport, "demo-helper")
    assert isinstance(analytics, service.Analytics)
    assert len(analytics.days) == 7
    assert [user.display_name for user in analytics.top_users] == ["Ada", "Grace"]
    assert _method(fake.transport).label == ("Visa ending 1234")
