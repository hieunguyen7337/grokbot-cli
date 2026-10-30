"""Every symbol the TUI draws, with a plain-ASCII twin for `--ascii` and terminals without the glyphs."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Glyphs:
    working: tuple[str, ...]  # animation frames for a working bot
    idle: str
    user: str  # a user prompt line in a session
    bot: str  # a bot message line
    tool: str  # a dimmed tool or progress line under a bot step
    dot: str  # the connection state dot
    ellipsis: str
    arrow: str
    separator: str
    pin: str


UNICODE = Glyphs(
    working=("✻", "✽", "✶", "✳", "✢", "·"),
    idle="∙",
    user=">",
    bot="⏺",
    tool="⎿",
    dot="●",
    ellipsis="…",
    arrow="→",
    separator="·",
    pin="▸",
)

ASCII = Glyphs(
    working=("*", "+", "x", "+"),
    idle=".",
    user=">",
    bot="*",
    tool="|_",
    dot="o",
    ellipsis="...",
    arrow="->",
    separator="-",
    pin=">",
)


def glyphs(ascii_only: bool = False) -> Glyphs:
    return ASCII if ascii_only else UNICODE
