"""Cloud computer egress, bot analytics, default payment method and address lookup. Every call here is a read."""

import math
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from groken.client import ConnectError

from . import vault
from .errors import Refusal, refusal
from .models import _record, _strings, _text
from .transport import Transport

RPCS = (
    "GetGrokBotEgressPolicy",
    "GetGrokBotAgentAnalytics",
    "GetGrokBotDefaultPaymentMethod",
    "SuggestGrokBotAddresses",
    "ResolveGrokBotAddress",
)
NO_ANALYTICS = "No analytics yet."
NO_PAYMENT = "No default payment method."
CHANGE_PAYMENT = "Change the default payment method in the Grok Bot app."
UNRESOLVED = "This address could not be resolved."
NOT_MEASURED = "Not measured"
_WALLETS = ("x_money", "stripe_link")
_WALLET_LABELS = {"x_money": "X Money", "stripe_link": "Stripe Link"}


def _enum(value: object, prefix: str, names: tuple[str, ...]) -> str:
    """A full name, short name or 1-based number as a lowercase short name; anything else is unknown."""
    if isinstance(value, int) and not isinstance(value, bool):
        return names[value - 1] if 0 < value <= len(names) else "unknown"
    text = str(value).lower().removeprefix(prefix.lower() + "_")
    if text.isdecimal():
        return _enum(_int(text), prefix, names)
    return text if text in names else "unknown"


def _int(value: object) -> int:
    """int32 arrives as a JSON number and int64 as a decimal string; anything else reads as zero."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if not isinstance(value, str) or not value.strip().isdecimal():
        return 0
    try:
        return int(value)
    except ValueError:  # over Python's integer string digit limit
        return 0


def _float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return 0.0
    try:
        number = float(value)
    except ValueError:
        return 0.0
    return number if math.isfinite(number) else 0.0


def _rows(value: object) -> list[Mapping[str, object]]:
    return (
        [row for row in value if isinstance(row, Mapping)]
        if isinstance(value, list)
        else []
    )


def _refused(error: ConnectError) -> Refusal:
    """The refusal to show as a notice; any other failure stays an error."""
    found = refusal(error)
    if found is None:
        raise error
    return found


def _section(title: str, rows: Iterable[str], empty: str) -> list[str]:
    return [title, *(list(rows) or [empty])]


@dataclass(frozen=True)
class EgressPolicy:
    restricted: bool
    allowed_domains: tuple[str, ...] = ()
    allowed_tcp: tuple[tuple[str, int], ...] = ()


def egress_policy(transport: Transport) -> EgressPolicy | Refusal:
    try:
        reply = transport.rpc("GetGrokBotEgressPolicy", {})
    except ConnectError as error:
        return _refused(error)
    return EgressPolicy(
        reply.get("restricted") is True,
        _strings(reply.get("allowedDomains")),
        tuple(
            (_text(row.get("cidr")), _int(row.get("port")))
            for row in _rows(reply.get("allowedTcpDestinations"))
        ),
    )


def egress_fields(policy: EgressPolicy) -> tuple[tuple[str, str], ...]:
    return (("Mode", "Restricted" if policy.restricted else "Open"),)


def egress_lines(policy: EgressPolicy) -> tuple[str, ...]:
    if not policy.restricted:
        return ("No outbound network restriction is set.",)
    return (
        *_section(
            "Allowed domains:", policy.allowed_domains, "No domains are allowed."
        ),
        "",
        *_section(
            "Allowed TCP destinations:",
            (f"{cidr} port {port}" for cidr, port in policy.allowed_tcp),
            "No TCP destinations are allowed.",
        ),
    )


@dataclass(frozen=True)
class Day:
    day: str
    active_users: int
    trailing_seven_day_active_users: int
    user_turns: int
    minutes_saved: float


@dataclass(frozen=True)
class TopUser:
    user_id: int
    display_name: str
    user_turns: int
    minutes_saved: float
    is_external: bool
    active_days: int


@dataclass(frozen=True)
class TopUsersWindow:
    window_days: int
    top_users: tuple[TopUser, ...]


@dataclass(frozen=True)
class Analytics:
    weekly_active_users: int
    total_minutes_saved: float
    minutes_saved_measured: bool
    minutes_saved_before_window: float
    days: tuple[Day, ...]
    top_users: tuple[TopUser, ...]
    top_users_by_window: tuple[TopUsersWindow, ...]


def _top_user(row: Mapping[str, object]) -> TopUser:
    return TopUser(
        _int(row.get("userId")),
        _text(row.get("displayName")),
        _int(row.get("userTurns")),
        _float(row.get("minutesSaved")),
        row.get("isExternal") is True,
        _int(row.get("activeDays")),
    )


def _analytics(reply: Mapping[str, object]) -> Analytics:
    return Analytics(
        _int(reply.get("weeklyActiveUsers")),
        _float(reply.get("totalMinutesSaved")),
        reply.get("minutesSavedMeasured") is True,
        _float(reply.get("minutesSavedBeforeWindow")),
        tuple(
            Day(
                _text(row.get("day")),
                _int(row.get("activeUsers")),
                _int(row.get("trailingSevenDayActiveUsers")),
                _int(row.get("userTurns")),
                _float(row.get("minutesSaved")),
            )
            for row in _rows(reply.get("days"))
        ),
        tuple(_top_user(row) for row in _rows(reply.get("topUsers"))),
        tuple(
            TopUsersWindow(
                _int(row.get("windowDays")),
                tuple(_top_user(user) for user in _rows(row.get("topUsers"))),
            )
            for row in _rows(reply.get("topUsersByWindow"))
        ),
    )


def analytics(transport: Transport, bot_id: str) -> Analytics | Refusal | None:
    """None when the bot has no analytics yet (a not_found refusal); other refusals come back as notices."""
    try:
        reply = transport.rpc("GetGrokBotAgentAnalytics", {"agentId": bot_id})
    except ConnectError as error:
        found = _refused(error)
        return None if found.code == "not_found" else found
    return _analytics(reply)


def minutes_label(measured: bool, minutes: float) -> str:
    return f"{minutes:.1f}" if measured else NOT_MEASURED


def analytics_fields(value: Analytics) -> tuple[tuple[str, str], ...]:
    return (
        ("Weekly active users", str(value.weekly_active_users)),
        (
            "Minutes saved",
            minutes_label(value.minutes_saved_measured, value.total_minutes_saved),
        ),
    )


def recent_days(value: Analytics, count: int = 14) -> tuple[Day, ...]:
    """The newest days first; day strings sort as ISO dates."""
    return tuple(sorted(value.days, key=lambda day: day.day, reverse=True)[:count])


def _day_line(day: Day, measured: bool) -> str:
    return (
        f"{day.day}: active {day.active_users}, turns {day.user_turns}, "
        f"minutes saved {minutes_label(measured, day.minutes_saved)}"
    )


def _user_line(user: TopUser, measured: bool) -> str:
    name = user.display_name or f"User {user.user_id}"
    external = " (external)" if user.is_external else ""
    return (
        f"{name}{external}: turns {user.user_turns}, minutes saved "
        f"{minutes_label(measured, user.minutes_saved)}, active days {user.active_days}"
    )


def analytics_lines(value: Analytics) -> tuple[str, ...]:
    measured = value.minutes_saved_measured
    lines = _section(
        "Last 14 days, latest first:",
        (_day_line(day, measured) for day in recent_days(value)),
        "No daily activity yet.",
    )
    if value.top_users_by_window:
        for window in value.top_users_by_window:
            lines += [
                "",
                *_section(
                    f"Top users, last {window.window_days} days:",
                    (_user_line(user, measured) for user in window.top_users),
                    "No users yet.",
                ),
            ]
    else:
        lines += [
            "",
            *_section(
                "Top users:",
                (_user_line(user, measured) for user in value.top_users),
                "No top users yet.",
            ),
        ]
    return tuple(lines)


@dataclass(frozen=True)
class DefaultPaymentMethod:
    kind: str
    wallet: str
    label: str


def default_payment_method(transport: Transport) -> DefaultPaymentMethod | Refusal:
    """The method's label only. The vault card id is a secret reference: it is matched and dropped here."""
    try:
        reply = transport.rpc("GetGrokBotDefaultPaymentMethod", {})
    except ConnectError as error:
        return _refused(error)
    method = _record(reply.get("method"))
    card_id = _text(method.get("vaultCardId"))
    if card_id:
        return DefaultPaymentMethod("card", "", _card_label(transport, card_id))
    if method.get("wallet") is not None:
        wallet = _enum(method["wallet"], "GROK_BOT_PAYMENT_WALLET", _WALLETS)
        return DefaultPaymentMethod(
            "wallet", wallet, _WALLET_LABELS.get(wallet, "A wallet")
        )
    return DefaultPaymentMethod("none", "", NO_PAYMENT)


def _card_label(transport: Transport, card_id: str) -> str:
    # The label is cosmetic: a refused vault list still shows the card, labelled with the refusal sentence.
    try:
        _, methods, _ = vault.payment_methods(transport)
    except ConnectError as error:
        found = refusal(error)
        return found.message if found is not None else "A saved card"
    for method in methods:
        if method.id == card_id and method.brand and method.last4:
            return f"{method.brand} ending {method.last4}"
    return "A saved card"


@dataclass(frozen=True)
class Suggestion:
    id: str
    title: str
    subtitle: str


@dataclass(frozen=True)
class AddressParts:
    street: str
    city: str
    state: str
    postal_code: str
    country: str
    country_code: str
    formatted: str


def new_session_token() -> str:
    """One token per lookup: the same value goes to suggest and to resolve. Never shown."""
    return uuid.uuid4().hex


def suggest_addresses(
    transport: Transport, query: str, session_token: str
) -> tuple[str, tuple[Suggestion, ...]]:
    try:
        reply = transport.rpc(
            "SuggestGrokBotAddresses", {"query": query, "sessionToken": session_token}
        )
    except Exception:  # noqa: BLE001 - the app reads every lookup failure as unavailable
        return "unavailable", ()
    outcome = _enum(
        reply.get("outcome"),
        "GROK_BOT_ADDRESS_LOOKUP_OUTCOME",
        ("suggested", "unavailable"),
    )
    if outcome != "suggested":
        return outcome, ()
    suggestions = []
    for row in _rows(reply.get("suggestions")):
        identifier = _text(row.get("id"))
        if identifier:
            suggestions.append(
                Suggestion(
                    identifier, _text(row.get("title")), _text(row.get("subtitle"))
                )
            )
    return outcome, tuple(suggestions)


def resolve_address(
    transport: Transport, suggestion_id: str, session_token: str
) -> AddressParts | Refusal | None:
    """None when the lookup returns no parts (unresolved)."""
    try:
        reply = transport.rpc(
            "ResolveGrokBotAddress",
            {"id": suggestion_id, "sessionToken": session_token},
        )
    except ConnectError as error:
        return _refused(error)
    parts = _record(reply.get("parts"))
    if not parts:
        return None
    return AddressParts(
        _text(parts.get("street")),
        _text(parts.get("city")),
        _text(parts.get("state")),
        _text(parts.get("postalCode")),
        _text(parts.get("country")),
        _text(parts.get("countryCode")),
        _text(parts.get("formatted")),
    )


def lookup_sentence(outcome: str) -> str:
    """The one sentence shown when a lookup gives no suggestions."""
    return {
        "suggested": "No address suggestions.",
        "unavailable": "Address suggestions are unavailable.",
    }.get(outcome, "Address lookup returned an unknown result.")


_ADDRESS_FIELDS = (
    ("Street", "street"),
    ("City", "city"),
    ("State", "state"),
    ("Postal code", "postal_code"),
    ("Country", "country"),
    ("Country code", "country_code"),
)


def address_fields(parts: AddressParts) -> tuple[tuple[str, str], ...]:
    return tuple(
        (label, getattr(parts, name))
        for label, name in _ADDRESS_FIELDS
        if getattr(parts, name)
    )


DEMO_RPCS: dict[str, object] = {name: {} for name in RPCS}
_DEMO_DAYS = tuple(
    {
        "day": f"2026-10-{day:02d}",
        "activeUsers": active,
        "trailingSevenDayActiveUsers": 2,
        "userTurns": turns,
        "minutesSaved": minutes,
    }
    for day, active, turns, minutes in (
        (25, 1, 3, 4.5),
        (26, 2, 7, 11.0),
        (27, 2, 6, 9.5),
        (28, 1, 2, 3.0),
        (29, 2, 8, 12.0),
        (30, 2, 5, 8.0),
        (31, 1, 4, 6.5),
    )
)
_DEMO_TOP_USERS = [
    {
        "userId": 1,
        "displayName": "Ada",
        "userTurns": 22,
        "minutesSaved": 31.0,
        "isExternal": False,
        "activeDays": 6,
    },
    {
        "userId": 2,
        "displayName": "Grace",
        "userTurns": 9,
        "minutesSaved": 12.5,
        "isExternal": True,
        "activeDays": 4,
    },
]
DEMO_RPCS.update(
    {
        "GetGrokBotEgressPolicy": {
            "restricted": True,
            "allowedDomains": ["example.com", "api.example.com"],
            "allowedTcpDestinations": [{"cidr": "203.0.113.0/24", "port": 443}],
        },
        "GetGrokBotAgentAnalytics": {
            "weeklyActiveUsers": 2,
            "totalMinutesSaved": 65.5,
            "days": list(_DEMO_DAYS),
            "minutesSavedBeforeWindow": 0,
            "topUsers": _DEMO_TOP_USERS,
            "minutesSavedMeasured": True,
            "topUsersByWindow": [{"windowDays": 7, "topUsers": _DEMO_TOP_USERS}],
        },
        "GetGrokBotDefaultPaymentMethod": {"method": {"vaultCardId": "demo-payment"}},
        "SuggestGrokBotAddresses": {
            "outcome": 1,
            "suggestions": [
                {
                    "id": "demo-address-1",
                    "title": "1 Example Street",
                    "subtitle": "Springfield, IL",
                },
                {
                    "id": "demo-address-2",
                    "title": "2 Example Avenue",
                    "subtitle": "Springfield, IL",
                },
            ],
        },
        "ResolveGrokBotAddress": {
            "parts": {
                "street": "1 Example Street",
                "city": "Springfield",
                "state": "IL",
                "postalCode": "62701",
                "country": "United States",
                "countryCode": "US",
                "formatted": "1 Example Street, Springfield, IL 62701, United States",
            }
        },
    }
)
