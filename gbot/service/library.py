"""Documents a bot has touched and the pins that keep some of them close."""

from dataclasses import dataclass

from groken.client import ConnectError

from .errors import refusal
from .transport import Transport

RPCS = frozenset(
    (
        "ListGrokBotLibraryDocs",
        "ListGrokBotLibraryPins",
        "SetGrokBotLibraryPin",
        "MergeGrokBotLibraryPins",
    )
)
KINDS = ("page", "media", "doc", "app")
MEDIA_KINDS = ("unspecified", "image", "video", "file", "link")
MEDIA_PREFIX = "GROK_BOT_LIBRARY_PIN_MEDIA_KIND_"


@dataclass(frozen=True)
class LibraryDoc:
    key: str
    provider: str
    external_id: str
    url: str
    title: str
    created_by_bot: bool
    last_action: str
    first_touched_at_ms: int
    last_touched_at_ms: int
    kind: str


@dataclass(frozen=True)
class Pin:
    kind: str
    store_id: str = ""
    canvas_id: str = ""
    document_id: str = ""
    media_kind: str = ""
    source: str = ""
    name: str = ""
    posted_at_ms: int = 0
    key: str = ""
    pinned_at_ms: int = 0

    def to_wire(self) -> dict[str, object]:
        wire: dict[str, object] = {}
        if self.kind == "page":
            page: dict[str, object] = {"storeId": self.store_id}
            if self.canvas_id:
                page["canvasId"] = self.canvas_id
            elif self.document_id:
                page["documentId"] = self.document_id
            wire["page"] = page
        elif self.kind == "media":
            media: dict[str, object] = {
                "kind": MEDIA_PREFIX + self.media_kind.upper(),
                "source": self.source,
                "name": self.name,
            }
            if self.posted_at_ms:
                media["postedAtMs"] = str(self.posted_at_ms)
            wire["media"] = media
        elif self.kind == "doc":
            wire["externalDocKey"] = self.key
        elif self.kind == "app":
            wire["appKey"] = self.key
        wire["pinnedAtMs"] = str(self.pinned_at_ms)
        return wire


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(str(value))
    except ValueError:
        return 0


def _rows(value: object) -> tuple[dict[str, object], ...]:
    return (
        tuple(dict(row) for row in value if isinstance(row, dict))
        if isinstance(value, list)
        else ()
    )


def _text(row: dict[str, object], name: str) -> str:
    value = row.get(name)
    return value if isinstance(value, str) else ""


def _media_kind(value: object) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        return MEDIA_KINDS[value] if 0 <= value < len(MEDIA_KINDS) else "unknown"
    name = str(value).lower().removeprefix(MEDIA_PREFIX.lower())
    if name.isdecimal():
        return _media_kind(int(name))
    return name if name in MEDIA_KINDS else "unknown"


def pin_from_wire(row: object) -> Pin | None:
    """A pin, or None when it names no known target (the app drops those)."""
    if not isinstance(row, dict):
        return None
    pinned = _int(row.get("pinnedAtMs"))
    page, media = row.get("page"), row.get("media")
    if isinstance(page, dict):
        return Pin(
            "page",
            _text(page, "storeId"),
            _text(page, "canvasId"),
            _text(page, "documentId"),
            pinned_at_ms=pinned,
        )
    if isinstance(media, dict):
        return Pin(
            "media",
            media_kind=_media_kind(media.get("kind", 0)),
            source=_text(media, "source"),
            name=_text(media, "name"),
            posted_at_ms=_int(media.get("postedAtMs")),
            pinned_at_ms=pinned,
        )
    for kind, field in (("doc", "externalDocKey"), ("app", "appKey")):
        key = _text(row, field)
        if key:
            return Pin(kind, key=key, pinned_at_ms=pinned)
    return None


def _pins(reply: dict[str, object]) -> tuple[Pin, ...]:
    return tuple(
        pin for pin in map(pin_from_wire, _rows(reply.get("pins"))) if pin is not None
    )


def library_docs(transport: Transport, bot_id: str) -> tuple[LibraryDoc, ...]:
    reply = transport.rpc("ListGrokBotLibraryDocs", {"agentId": bot_id})
    return tuple(
        LibraryDoc(
            _text(row, "key"),
            _text(row, "provider"),
            _text(row, "externalId"),
            _text(row, "url"),
            _text(row, "title"),
            bool(row.get("createdByBot")),
            _text(row, "lastAction"),
            _int(row.get("firstTouchedAtMs")),
            _int(row.get("lastTouchedAtMs")),
            _text(row, "kind"),
        )
        for row in _rows(reply.get("docs"))
    )


def library_pins(transport: Transport, bot_id: str) -> tuple[Pin, ...]:
    return _pins(transport.rpc("ListGrokBotLibraryPins", {"agentId": bot_id}))


def set_pin(
    transport: Transport, bot_id: str, pin: Pin, pinned: bool
) -> tuple[Pin, ...]:
    return _pins(
        transport.rpc(
            "SetGrokBotLibraryPin",
            {"agentId": bot_id, "pin": pin.to_wire(), "isPinned": pinned},
        )
    )


def merge_pins(
    transport: Transport, bot_id: str, pins: tuple[Pin, ...] | list[Pin]
) -> tuple[Pin, ...]:
    try:
        reply = transport.rpc(
            "MergeGrokBotLibraryPins",
            {"agentId": bot_id, "pins": [pin.to_wire() for pin in pins]},
        )
    except ConnectError as error:
        refused = refusal(error)
        if refused is not None and refused.code == "not_found":
            return ()
        raise
    return _pins(reply)


DEMO_RPCS: dict[str, object] = {name: {} for name in RPCS}
