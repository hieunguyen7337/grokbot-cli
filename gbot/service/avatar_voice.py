"""Avatar bytes and voice preferences for owned bots."""

import base64
import math
import struct
from dataclasses import dataclass

from .models import Bot, _record
from .transport import Transport

COMMANDS = dict.fromkeys(
    (
        "getAgentAvatar",
        "setAgentAvatarBytes",
        "generateAgentAvatarImage",
        "setAgentVoice",
    ),
    "object",
)
RPCS = ("SetGrokBotAgentVoice",)
VOICES = tuple(
    (name, name.capitalize())
    for name in [
        "altair",
        "ara",
        "atlas",
        "aurora",
        "carina",
        "castor",
        "celeste",
        "cosmo",
        "eve",
        "helios",
        "helix",
        "iris",
        "kepler",
        "leo",
        "liora",
        "lumen",
        "luna",
        "lux",
        "naksh",
        "orion",
        "perseus",
        "rex",
        "rigel",
        "sal",
        "sirius",
        "ursa",
        "zagan",
        "zenith",
    ]
)
SPEEDS = (0.5, 0.75, 1, 1.25, 1.5, 2)
LANGUAGES = (
    "auto",
    "en",
    "ar-EG",
    "ar-SA",
    "ar-AE",
    "bn",
    "ca",
    "zh",
    "da",
    "nl",
    "fi",
    "fr",
    "de",
    "hi",
    "hu",
    "id",
    "it",
    "ja",
    "ko",
    "pl",
    "pt-BR",
    "pt-PT",
    "ru",
    "es-MX",
    "es-ES",
    "sv",
    "th",
    "tr",
    "vi",
)
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9XkAAAAASUVORK5CYII="
)
DEMO_COMMANDS = {
    "getAgentAvatar": {"dataUrl": None, "version": None},
    "setAgentAvatarBytes": None,
    "generateAgentAvatarImage": {
        "imageBase64": base64.b64encode(_PNG).decode(),
        "mimeType": "image/png",
    },
    "setAgentVoice": None,
}
DEMO_RPCS = {"SetGrokBotAgentVoice": {}}


@dataclass(frozen=True)
class Avatar:
    data: bytes
    mime_type: str


@dataclass(frozen=True)
class GeneratedImage(Avatar):
    pass


def avatar(transport: Transport, bot_id: str) -> Avatar | None:
    url = _record(transport.command("getAgentAvatar", {"id": bot_id})).get("dataUrl")
    if url is None or url == "":
        return None
    if not isinstance(url, str) or not url.startswith("data:") or ";base64," not in url:
        raise ValueError("Invalid avatar data URL.")
    header, encoded = url.split(";base64,", 1)
    return Avatar(base64.b64decode(encoded, validate=True), header[5:])


def check_png(data: bytes) -> tuple[int, int]:
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("Avatar exceeds 2 MiB; export a smaller PNG.")
    if (
        len(data) < 33
        or data[:8] != b"\x89PNG\r\n\x1a\n"
        or data[8:16] != b"\x00\x00\x00\rIHDR"
    ):
        raise ValueError("Invalid PNG; export the image as a PNG.")
    width, height = struct.unpack(">II", data[16:24])
    if not width or not height or max(width, height) > 1024:
        raise ValueError(
            "Invalid avatar dimensions; resize it to 1024 px or less on each side."
        )
    return width, height


def set_avatar(transport: Transport, bot: Bot, png: bytes | None) -> None:
    if png is not None:
        check_png(png)
    transport.command(
        "setAgentAvatarBytes",
        {
            "id": bot.id,
            "pngBase64": base64.b64encode(png).decode() if png is not None else None,
        },
    )


def generate_avatar(transport: Transport, description: str) -> GeneratedImage:
    if not description.strip():
        raise ValueError("Avatar description must not be empty.")
    reply = _record(
        transport.command("generateAgentAvatarImage", {"description": description})
    )
    encoded, mime = reply.get("imageBase64"), reply.get("mimeType")
    if not isinstance(encoded, str) or not isinstance(mime, str):
        raise TypeError("Invalid generated image.")
    return GeneratedImage(base64.b64decode(encoded, validate=True), mime)


def normalize_speed(value: object) -> float:
    try:
        number = float(str(value))
    except (ValueError, TypeError):
        return 1
    return (
        min(SPEEDS, key=lambda option: abs(option - number))
        if math.isfinite(number)
        else 1
    )


def normalize_language(value: object) -> str:
    if not isinstance(value, str):
        return "auto"
    locale = value.strip().replace("_", "-").casefold()
    exact = [item for item in LANGUAGES if item.casefold() == locale]
    matches = exact or [
        item for item in LANGUAGES if item.split("-")[0] == locale.split("-")[0]
    ]
    return matches[0] if len(matches) == 1 else "auto"


class _Unset:
    pass


_UNSET = _Unset()


def set_voice(
    transport: Transport,
    bot: Bot,
    *,
    voice_id: str | None | _Unset = _UNSET,
    speed: object = None,
    language: str | None = None,
) -> None:
    fields: dict[str, object] = {"id": bot.id}
    temporal = bot.raw.get("harness") == "temporal"
    if not isinstance(voice_id, _Unset):
        if voice_id is not None and voice_id not in dict(VOICES):
            raise ValueError("Unknown voice id; use gbot voice --list.")
        fields["voiceId"] = (voice_id or "") if temporal else voice_id
    if speed is not None:
        fields["voiceSpeed"] = normalize_speed(speed)
    if language is not None:
        fields["voiceLanguage"] = normalize_language(language)
    if len(fields) == 1:
        raise ValueError("Nothing to change")
    if temporal:
        transport.rpc("SetGrokBotAgentVoice", fields)
    else:
        transport.command("setAgentVoice", fields)
