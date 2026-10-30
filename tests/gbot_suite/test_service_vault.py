from dataclasses import asdict

import pytest

from gbot.service import vault as v
from gbot.service.transport import FakeTransport


def fake():
    return FakeTransport(rpcs=v.DEMO_RPCS)


def test_list_and_empty():
    t = fake()
    rows = v.list_items(t)
    assert [r.kind for r in rows] == ["login", "card", "contact"]
    assert t.calls == [
        ("rpc", v.RPCS[0], {"includeKinds": [1, 2, 3], "includeManaged": True})
    ]
    t.rpcs[v.RPCS[0]] = {}
    assert v.list_items(t) == []


@pytest.mark.parametrize("kind", [1, "LOGIN", "GROK_BOT_VAULT_ITEM_KIND_LOGIN"])
def test_projection(kind):
    t = fake()
    t.rpcs[v.RPCS[0]] = {
        "credentials": [
            {
                "id": "id",
                "kind": kind,
                "createdAtMs": "123",
                "password": "hidden",
                "card": {
                    "brand": "Visa",
                    "last4": "1234",
                    "number": "hidden",
                    "billingAddress": {"secret": "hidden"},
                },
            }
        ]
    }
    item = v.list_items(t)[0]
    assert item.kind == "login" and item.created_at_ms == 123
    assert item.card is not None
    assert set(asdict(item.card)) == {
        "brand",
        "last4",
        "exp_month",
        "exp_year",
        "holder_name",
        "nickname",
    }
    assert "hidden" not in repr(item)


def test_put_and_delete():
    t = fake()
    password = "test-password-unique"
    for item_id in (None, "login"):
        assert (
            v.put_login(
                t,
                id=item_id,
                title="Title",
                username="user",
                password=password,
                sites=(" example.com ", "example.com", "https://example.org/login"),
            )
            is None
        )
        payload = t.calls[-1][2]
        assert payload["sites"] == ["example.com", "https://example.org/login"]
        assert payload["password"] == password
        assert ("id" in payload) == (item_id is not None)
    v.delete_item(t, "id")
    assert t.calls[-1][2] == {"id": "id"}
    assert all(password not in repr(c) for c in t.calls if c[1] != v.RPCS[1])
    t.rpcs[v.RPCS[1]] = RuntimeError(password)
    with pytest.raises(ValueError) as error:
        v.put_login(t, title="T", username="U", password=password)
    assert password not in str(error.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "", "username": ""},
        {"password": ""},
        {"id": "x", "password": ""},
        {"sites": ["bad site"]},
        {"sites": ["https://user:secret@example.com"]},
        {"sites": ["ftp://example.com"]},
    ],
)
def test_validation(changes):
    t = fake()
    with pytest.raises(ValueError):
        v.put_login(
            t, **dict({"title": "T", "username": "U", "password": "secret"}, **changes)
        )
    assert not t.calls


@pytest.mark.parametrize(
    "value,expected",
    [
        (1, "ok"),
        (2, "needs_auth"),
        (3, "unavailable"),
        (4, "account_closed"),
        (0, "unknown"),
        ("GROK_BOT_STRIPE_LINK_PAYMENT_METHODS_OUTCOME_OK", "ok"),
        ("NEEDS_AUTH", "needs_auth"),
    ],
)
def test_payments(value, expected):
    t = fake()
    t.rpcs[v.RPCS[3]] = {"outcome": value, "unavailableCount": 2}
    assert v.payment_methods(t) == (expected, [], 2)


@pytest.mark.parametrize(
    "device,expected",
    [
        ("singleDevice", "single_device"),
        ("multiDevice", "multi_device"),
        ("future", "unknown"),
    ],
)
def test_passkeys(device, expected):
    t = fake()
    t.rpcs[v.RPCS[4]] = {
        "passkeys": [{"credentialId": "id", "deviceType": device, "lastUsedAtMs": "42"}]
    }
    key = v.list_passkeys(t)[0]
    assert key.device_type == expected and key.last_used_at_ms == 42
    v.revoke_passkey(t, key.credential_id)
    assert t.calls[-1][2] == {"credentialId": "id"}


def test_onepassword():
    t = fake()
    reply = {
        "connections": [
            {
                "connectionId": "id",
                "accountEmail": "a@example.com",
                "vaultName": "Personal",
                "itemCount": 2,
                "lastSuccessfulSyncAtMs": "42",
                "lifecycleState": "CREDENTIAL_LIFECYCLE_STATE_ACTIVE",
                "serviceAccountToken": "hidden",
            }
        ],
        "items": [{"token": "hidden"}],
        "previousVaults": [{"vaultName": "Old", "token": "hidden"}],
    }
    for name in v.RPCS[6:]:
        t.rpcs[name] = reply
    state = v.onepassword_state(t)
    assert (
        state.item_count == 1 and state.connections[0].last_successful_sync_at_ms == 42
    )
    assert "hidden" not in repr(state) and "token" not in repr(asdict(state))
    assert v.sync_onepassword(t) == state
    assert t.calls[-1][2] == {"trigger": 1}
    assert v.delete_onepassword(t, "id") == state
    assert t.calls[-1][2] == {"connectionId": "id"}
