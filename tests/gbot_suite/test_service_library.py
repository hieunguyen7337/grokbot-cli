import json

import pytest

from gbot.service import library
from gbot.service.transport import FakeTransport
from groken.client import ConnectError

WIRE = [
    {"page": {"storeId": "s", "canvasId": "c"}, "pinnedAtMs": "5"},
    {"page": {"storeId": "s", "documentId": "d"}, "pinnedAtMs": "6"},
    {
        "media": {
            "kind": "GROK_BOT_LIBRARY_PIN_MEDIA_KIND_IMAGE",
            "source": "src",
            "name": "pic",
            "postedAtMs": "7",
        },
        "pinnedAtMs": "8",
    },
    {"externalDocKey": "doc-1", "pinnedAtMs": "9"},
    {"appKey": "app-1", "pinnedAtMs": "10"},
]


def test_pin_round_trip_all_kinds():
    pins = [library.pin_from_wire(row) for row in WIRE]
    assert [p.kind for p in pins if p] == ["page", "page", "media", "doc", "app"]
    assert [p.to_wire() for p in pins if p] == WIRE


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("VIDEO", "video"),
        (3, "file"),
        ("link", "link"),
        ("zzz", "unknown"),
        (99, "unknown"),
    ],
)
def test_media_kind_forms(kind, expected):
    pin = library.pin_from_wire({"media": {"kind": kind, "source": "s"}})
    assert pin is not None and pin.media_kind == expected


@pytest.mark.parametrize(
    "row",
    [{}, {"pinnedAtMs": "1"}, "x", None, {"page": 3}, {"page": {}}, {"media": {}}],
)
def test_unknown_targets_dropped(row):
    assert library.pin_from_wire(row) is None


def test_unknown_media_kind_is_not_sent_as_a_full_name():
    pin = library.pin_from_wire({"media": {"kind": 99, "source": "s"}})
    assert pin is not None and pin.media_kind == "unknown"
    media = pin.to_wire()["media"]
    assert isinstance(media, dict) and "kind" not in media


def test_created_by_bot_string_false_is_false():
    fake = FakeTransport(
        rpcs={
            "ListGrokBotLibraryDocs": {"docs": [{"key": "k", "createdByBot": "false"}]}
        }
    )
    assert library.library_docs(fake, "bot")[0].created_by_bot is False


def test_docs_defaults_and_payload():
    fake = FakeTransport(
        rpcs={
            "ListGrokBotLibraryDocs": {
                "docs": [
                    {
                        "key": "k",
                        "provider": "notion",
                        "externalId": "x",
                        "url": "https://example.invalid/d",
                        "title": "T",
                        "createdByBot": True,
                        "lastAction": "edit",
                        "firstTouchedAtMs": "1",
                        "lastTouchedAtMs": "2",
                        "kind": "page",
                        "extra": 1,
                    },
                    {},
                    7,
                ]
            }
        }
    )
    docs = library.library_docs(fake, "bot")
    assert fake.calls[0][2] == {"agentId": "bot"}
    assert docs[0].created_by_bot and docs[0].last_touched_at_ms == 2
    assert docs[1] == library.LibraryDoc("", "", "", "", "", False, "", 0, 0, "")
    assert len(docs) == 2


def test_pins_set_and_merge_payloads():
    fake = FakeTransport(
        rpcs={
            "ListGrokBotLibraryPins": {"pins": [*WIRE, {"junk": 1}]},
            "SetGrokBotLibraryPin": {"pins": WIRE[3:4]},
            "MergeGrokBotLibraryPins": {"pins": WIRE},
        }
    )
    assert len(library.library_pins(fake, "bot")) == 5
    pin = library.Pin("doc", key="doc-1", pinned_at_ms=9)
    assert library.set_pin(fake, "bot", pin, False) == (pin,)
    assert fake.calls[1][2] == {
        "agentId": "bot",
        "pin": WIRE[3],
        "isPinned": False,
    }
    assert len(library.merge_pins(fake, "bot", [pin])) == 5
    assert fake.calls[2][2] == {"agentId": "bot", "pins": [WIRE[3]]}


def test_merge_not_found_is_empty_and_other_errors_propagate():
    fake = FakeTransport(
        rpcs={
            "MergeGrokBotLibraryPins": ConnectError(
                404, json.dumps({"code": "not_found"})
            )
        }
    )
    assert library.merge_pins(fake, "bot", []) == ()
    fake.rpcs["MergeGrokBotLibraryPins"] = ConnectError(
        403, json.dumps({"code": "permission_denied", "message": "no"})
    )
    with pytest.raises(ConnectError):
        library.merge_pins(fake, "bot", [])
