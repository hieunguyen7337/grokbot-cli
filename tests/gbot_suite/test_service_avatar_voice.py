import base64
import struct

import pytest

from gbot.service import avatar_voice as av
from gbot.service.fake import load_fake
from gbot.service.models import Bot
from gbot.service.transport import FakeTransport


def png(width=1, height=1):
    data = bytearray(av._PNG)
    data[16:24] = struct.pack(">II", width, height)
    return bytes(data)


def test_avatar_decode_and_none():
    transport = FakeTransport(av.DEMO_COMMANDS)
    assert av.avatar(transport, "bot") is None
    transport.commands["getAgentAvatar"] = {
        "dataUrl": "data:image/png;base64," + base64.b64encode(png()).decode()
    }
    assert av.avatar(transport, "bot") == av.Avatar(png(), "image/png")
    transport.commands["getAgentAvatar"] = {"dataUrl": "https://example/image"}
    with pytest.raises(ValueError, match="data URL"):
        av.avatar(transport, "bot")
    transport.commands["getAgentAvatar"] = {"dataUrl": "data:image/png;base64,???"}
    with pytest.raises(ValueError):
        av.avatar(transport, "bot")


@pytest.mark.parametrize(
    "data,message",
    [
        (b"jpeg", "PNG"),
        (png()[:24], "PNG"),
        (png() + bytes(2 * 1024 * 1024), "2 MiB"),
        (png(1025), "resize it to 1024 px or less"),
        (png(1, 1025), "1024"),
        (png(0), "dimensions"),
    ],
    ids=("signature", "truncated", "size", "width", "height", "zero"),
)
def test_png_refusals(data, message):
    with pytest.raises(ValueError, match=message):
        av.check_png(data)


def test_set_clear_and_generate():
    transport = FakeTransport(av.DEMO_COMMANDS)
    assert av.check_png(png(1024, 1024)) == (1024, 1024)
    bot = Bot("bot", "Bot", raw={"harness": "temporal"})
    av.set_avatar(transport, bot, png())
    assert transport.calls[-1] == (
        "command",
        "setAgentAvatarBytes",
        {"id": "bot", "pngBase64": base64.b64encode(png()).decode()},
    )
    av.set_avatar(transport, bot, None)
    assert transport.calls[-1][2] == {"id": "bot", "pngBase64": None}
    image = av.generate_avatar(transport, "A star")
    assert image.data == av._PNG and image.mime_type == "image/png"
    assert transport.calls[-1][2] == {"description": "A star"}
    with pytest.raises(ValueError, match="empty"):
        av.generate_avatar(transport, " ")
    with pytest.raises(ValueError, match="PNG"):
        av.set_avatar(transport, bot, b"jpeg")


@pytest.mark.parametrize(
    "value,expected",
    [(None, 1), ("bad", 1), ("nan", 1), ("inf", 1), (1.4, 1.5), (0.6, 0.5), (10, 2)],
)
def test_speed(value, expected):
    assert av.normalize_speed(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "auto"),
        ("", "auto"),
        ("unknown", "auto"),
        ("en-US", "en"),
        ("pt", "auto"),
        ("PT_br", "pt-BR"),
        ("ar-EG", "ar-EG"),
    ],
)
def test_language(value, expected):
    assert av.normalize_language(value) == expected


@pytest.mark.parametrize(
    "harness,kind,name",
    [("temporal", "rpc", "SetGrokBotAgentVoice"), ("box", "command", "setAgentVoice")],
)
def test_voice_payloads(harness, kind, name):
    transport = FakeTransport(av.DEMO_COMMANDS, av.DEMO_RPCS)
    bot = Bot("bot", "Bot", raw={"harness": harness})
    av.set_voice(transport, bot, voice_id="ara", speed=1.4, language="bad")
    assert transport.calls[-1] == (
        kind,
        name,
        {"id": "bot", "voiceId": "ara", "voiceSpeed": 1.5, "voiceLanguage": "auto"},
    )
    av.set_voice(transport, bot, voice_id=None)
    assert transport.calls[-1][2] == {
        "id": "bot",
        "voiceId": "" if harness == "temporal" else None,
    }
    av.set_voice(transport, bot, speed=2)
    assert transport.calls[-1][2] == {"id": "bot", "voiceSpeed": 2}
    with pytest.raises(ValueError, match="Nothing to change"):
        av.set_voice(transport, bot)
    with pytest.raises(ValueError, match="Unknown voice"):
        av.set_voice(transport, bot, voice_id="unknown")


def test_demo_and_parity():
    import json
    from pathlib import Path

    fake = load_fake()
    assert set(av.COMMANDS) <= fake.transport.commands.keys()
    assert set(av.RPCS) <= fake.transport.rpcs.keys()
    entries = json.loads(Path("docs/parity.json").read_text(encoding="utf-8"))[
        "entries"
    ]
    assert all(
        e["status"] == "done" for e in entries if e["name"] in {*av.COMMANDS, *av.RPCS}
    )
