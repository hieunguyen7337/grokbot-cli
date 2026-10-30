"""Account vault metadata and write-only login submission."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from .transport import Transport

RPCS = (
    "ListGrokBotVaultCredentials",
    "PutGrokBotVaultCredential",
    "DeleteGrokBotVaultCredential",
    "ListGrokBotStripeLinkPaymentMethods",
    "ListPasskeys",
    "RevokePasskey",
    "GetOnePasswordState",
    "SyncOnePasswordConnections",
    "DeleteOnePasswordConnection",
)


def _enum(value: object, prefix: str, names: tuple[str, ...]) -> str:
    if isinstance(value, int) or str(value).isdigit():
        number = int(str(value))
        return names[number - 1] if 0 < number <= len(names) else "unknown"
    name = str(value or "").removeprefix(prefix).lower()
    return name if name in names else "unknown"


def _rows(value: object) -> list[dict]:
    return (
        [dict(row) for row in value if isinstance(row, Mapping)]
        if isinstance(value, list)
        else []
    )


def _int(value: object) -> int:
    return int(str(value or 0))


@dataclass(frozen=True)
class Card:
    brand: str
    last4: str
    exp_month: int
    exp_year: int
    holder_name: str
    nickname: str


@dataclass(frozen=True)
class VaultItem:
    id: str
    kind: str
    title: str
    username: str
    notes: str
    sites: tuple[str, ...]
    created_at_ms: int
    updated_at_ms: int
    card: Card | None
    contact: dict[str, object] | None
    managed_by: str


def _item(row: dict) -> VaultItem:
    card = row.get("card")
    contact = row.get("contact")
    return VaultItem(
        str(row.get("id", "")),
        _enum(
            row.get("kind"), "GROK_BOT_VAULT_ITEM_KIND_", ("login", "card", "contact")
        ),
        str(row.get("title", "")),
        str(row.get("username", "")),
        str(row.get("notes", "")),
        tuple(str(s) for s in row.get("sites", [])),
        _int(row.get("createdAtMs")),
        _int(row.get("updatedAtMs")),
        Card(
            str(card.get("brand", "")),
            str(card.get("last4", "")),
            _int(card.get("expMonth")),
            _int(card.get("expYear")),
            str(card.get("holderName", "")),
            str(card.get("nickname", "")),
        )
        if isinstance(card, dict)
        else None,
        {
            k: contact[k]
            for k in ("address", "defaultShipping", "email", "more")
            if k in contact
        }
        if isinstance(contact, dict)
        else None,
        _enum(
            row.get("managedBy"), "GROK_BOT_VAULT_ITEM_MANAGER_", ("grok_bot_email",)
        ),
    )


def list_items(transport: Transport) -> list[VaultItem]:
    reply = transport.rpc(RPCS[0], {"includeKinds": [1, 2, 3], "includeManaged": True})
    return [_item(row) for row in _rows(reply.get("credentials"))]


def login_sites(sites: Iterable[str]) -> tuple[str, ...]:
    result = []
    for site in sites:
        site = site.strip()
        if not site:
            continue
        try:
            parsed = urlsplit(site if "://" in site else "//" + site)
            host = parsed.hostname or ""
            valid = bool(
                re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", host)
            )
            valid = valid and not parsed.username and not parsed.password
            valid = valid and (not parsed.scheme or parsed.scheme in {"http", "https"})
            valid = valid and not any(c.isspace() for c in site)
            _ = parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Sites must be hosts or HTTP URLs.")
        if site not in result:
            result.append(site)
    return tuple(result)


def put_login(
    transport: Transport,
    *,
    id: str | None = None,
    title: str,
    username: str,
    password: str,
    notes: str = "",
    sites: Iterable[str] = (),
) -> VaultItem | None:
    if not title.strip() and not username.strip():
        raise ValueError("Enter a title or username.")
    if not password:
        raise ValueError(
            "Enter the password again to update this login."
            if id
            else "Enter a password."
        )
    payload: dict[str, object] = {
        "title": title.strip(),
        "username": username.strip(),
        "password": password,
        "notes": notes,
        "sites": list(login_sites(sites)),
    }
    if id is not None:
        payload["id"] = _id(id)
    try:
        reply = transport.rpc(RPCS[1], payload)
        row = reply.get("credential")
        return _item(row) if isinstance(row, dict) else None
    except Exception:  # noqa: BLE001 - password redaction boundary
        # A transport/refusal may echo the request. Never let it cross this boundary.
        raise ValueError("Login was not saved; no password is displayed.") from None
    finally:
        payload.clear()
        password = ""


def _id(value: str) -> str:
    if not value.strip():
        raise ValueError("An item id is required.")
    return value


def delete_item(transport: Transport, item_id: str) -> None:
    transport.rpc(RPCS[2], {"id": _id(item_id)})


@dataclass(frozen=True)
class PaymentMethod:
    id: str
    name: str
    is_default: bool
    kind: str
    brand: str
    last4: str
    exp_month: int
    exp_year: int
    ineligible_reason: str


def payment_methods(transport: Transport) -> tuple[str, list[PaymentMethod], int]:
    reply = transport.rpc(RPCS[3], {})
    return (
        _enum(
            reply.get("outcome"),
            "GROK_BOT_STRIPE_LINK_PAYMENT_METHODS_OUTCOME_",
            ("ok", "needs_auth", "unavailable", "account_closed"),
        ),
        [
            PaymentMethod(
                str(r.get("id", "")),
                str(r.get("name", "")),
                bool(r.get("isDefault")),
                _enum(
                    r.get("kind"),
                    "GROK_BOT_STRIPE_LINK_PAYMENT_METHOD_KIND_",
                    ("card", "bank_account"),
                ),
                str(r.get("brand", "")),
                str(r.get("last4", "")),
                _int(r.get("expMonth")),
                _int(r.get("expYear")),
                str(r.get("ineligibleReason", "")),
            )
            for r in _rows(reply.get("paymentMethods"))
        ],
        _int(reply.get("unavailableCount")),
    )


@dataclass(frozen=True)
class Passkey:
    credential_id: str
    name: str
    created_at_ms: int
    last_used_at_ms: int
    device_type: str
    backed_up: bool


def list_passkeys(transport: Transport) -> list[Passkey]:
    return [
        Passkey(
            str(r.get("credentialId", "")),
            str(r.get("name", "")),
            _int(r.get("createdAtMs")),
            _int(r.get("lastUsedAtMs")),
            {
                "singleDevice": "single_device",
                "multiDevice": "multi_device",
                "single_device": "single_device",
                "multi_device": "multi_device",
            }.get(str(r.get("deviceType")), "unknown"),
            bool(r.get("backedUp")),
        )
        for r in _rows(transport.rpc(RPCS[4], {}).get("passkeys"))
    ]


def revoke_passkey(transport: Transport, credential_id: str) -> None:
    transport.rpc(RPCS[5], {"credentialId": _id(credential_id)})


@dataclass(frozen=True)
class OnePasswordConnection:
    connection_id: str
    account_email: str
    vault_name: str
    item_count: int
    last_successful_sync_at_ms: int
    last_sync_error_code: str
    lifecycle_state: str
    expires_at_ms: int


@dataclass(frozen=True)
class PreviousVault:
    connection_id: str
    vault_name: str
    item_count: int


@dataclass(frozen=True)
class OnePassword:
    connections: tuple[OnePasswordConnection, ...]
    item_count: int
    previous_vaults: tuple[PreviousVault, ...]


def _onepassword(reply: dict[str, object]) -> OnePassword:
    return OnePassword(
        tuple(
            OnePasswordConnection(
                str(r.get("connectionId", "")),
                str(r.get("accountEmail", "")),
                str(r.get("vaultName", "")),
                _int(r.get("itemCount")),
                _int(r.get("lastSuccessfulSyncAtMs")),
                str(r.get("lastSyncErrorCode", "")),
                _enum(
                    r.get("lifecycleState"),
                    "CREDENTIAL_LIFECYCLE_STATE_",
                    ("active", "expiring", "grace", "expired", "provider_rejected"),
                ),
                _int(r.get("expiresAtMs")),
            )
            for r in _rows(reply.get("connections"))
        ),
        len(_rows(reply.get("items"))),
        tuple(
            PreviousVault(
                str(r.get("connectionId", "")),
                str(r.get("vaultName", "")),
                _int(r.get("itemCount")),
            )
            for r in _rows(reply.get("previousVaults"))
        ),
    )


def onepassword_state(transport: Transport) -> OnePassword:
    return _onepassword(transport.rpc(RPCS[6], {}))


def sync_onepassword(transport: Transport) -> OnePassword:
    return _onepassword(transport.rpc(RPCS[7], {"trigger": 1}))


def delete_onepassword(transport: Transport, connection_id: str) -> OnePassword:
    return _onepassword(transport.rpc(RPCS[8], {"connectionId": _id(connection_id)}))


DEMO_RPCS: dict[str, object] = {
    **{name: {} for name in RPCS},
    RPCS[0]: {
        "credentials": [
            {
                "id": "demo-login",
                "kind": 1,
                "title": "Example",
                "username": "demo@example.com",
                "sites": ["example.com"],
            },
            {
                "id": "demo-card",
                "kind": 2,
                "title": "Travel card",
                "card": {
                    "brand": "Visa",
                    "last4": "4242",
                    "expMonth": 12,
                    "expYear": 2030,
                },
            },
            {
                "id": "demo-contact",
                "kind": 3,
                "title": "Home",
                "contact": {"email": "demo@example.com"},
            },
        ]
    },
    RPCS[3]: {
        "outcome": 1,
        "paymentMethods": [
            {
                "id": "demo-payment",
                "name": "Link card",
                "kind": 1,
                "brand": "Visa",
                "last4": "1234",
                "expMonth": 6,
                "expYear": 2031,
            }
        ],
    },
    RPCS[4]: {
        "passkeys": [
            {
                "credentialId": "demo-passkey",
                "name": "Security key",
                "deviceType": "singleDevice",
                "backedUp": False,
                "lastUsedAtMs": "1800000000000",
            }
        ]
    },
    RPCS[6]: {
        "connections": [
            {
                "connectionId": "demo-1password",
                "accountEmail": "demo@example.com",
                "vaultName": "Personal",
                "itemCount": 3,
                "lifecycleState": 1,
            }
        ]
    },
}
