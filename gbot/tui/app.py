import asyncio
from time import monotonic
from typing import ClassVar

from textual.app import App
from textual.binding import Binding, BindingType
from textual.widgets import Input, TextArea

from gbot.service.api import Service
from gbot.service.models import Bot
from gbot.tui.glyphs import glyphs
from gbot.tui.screens.help import HelpScreen
from gbot.tui.screens.home import HomeScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.theme import GBOT_THEME, STYLES

# Printable shortcuts only act when no text input has focus. The guarded actions
# are distinct so check_action can let Input/TextArea receive the original key.
SHELL_BINDINGS = [
    Binding(key, f"stub('{action}')", description)
    for key, action, description in (
        ("up", "up", "Previous row"),
        ("down", "down", "Next row"),
        ("pageup", "page_up", "Previous page"),
        ("pagedown", "page_down", "Next page"),
        ("home", "first", "First row"),
        ("end", "last", "Last row"),
        ("alt+up", "previous_group", "Previous group"),
        ("alt+down", "next_group", "Next group"),
        ("ctrl+t", "pin", "Pin bot"),
        ("shift+up", "reorder_up", "Move bot up"),
        ("shift+down", "reorder_down", "Move bot down"),
        ("ctrl+s", "group_by", "Group by"),
        ("ctrl+f", "find", "Find"),
        ("ctrl+x", "interrupt", "Interrupt bot"),
    )
] + [
    Binding("[", "printable_stub('previous_group')", "Previous group"),
    Binding("]", "printable_stub('next_group')", "Next group"),
    Binding("space", "printable_stub('peek')", "Peek"),
    Binding("enter,right", "open", "Open bot"),
    *[
        Binding(str(n), f"printable_stub('answer_{n}')", f"Answer {n} in peek")
        for n in range(1, 10)
    ],
    *[Binding(f"alt+{n}", f"open_number({n})", f"Open bot {n}") for n in range(1, 10)],
    Binding("ctrl+p", "command_palette", "Command palette", priority=True),
    Binding("?", "help", "Keyboard help"),
    # Not a priority binding: dialogs and inputs handle escape first (a modal dismisses with its own result).
    Binding("escape", "escape", "Close or clear"),
    Binding(
        "ctrl+c", "request_exit", "Press twice within 2 seconds to exit", priority=True
    ),
]


class GbotApp(App[None]):
    TITLE = "Grok Bot"
    CSS = STYLES
    BINDINGS: ClassVar[list[BindingType]] = [*SHELL_BINDINGS]
    COMMAND_PALETTE_BINDING = "ctrl+p"
    ENABLE_COMMAND_PALETTE = True

    def __init__(
        self,
        service: Service,
        *,
        ascii_only: bool = False,
        bot: str | None = None,
        animate: bool = True,
    ) -> None:
        super().__init__()
        self.service = service
        self.ascii_only = ascii_only
        self.symbols = glyphs(ascii_only)
        self.initial_bot = bot
        self.animations_enabled = animate
        self.bots: list[Bot] = []
        self._exit_requested_at: float | None = None
        self.register_theme(GBOT_THEME)
        self.theme = "gbot"
        if not animate:
            self.animation_level = "none"

    async def on_mount(self) -> None:
        # Even the placeholder keeps service I/O off the UI thread.
        self.bots = await asyncio.to_thread(self.service.roster)
        await self.push_screen(HomeScreen(self.bots, self.symbols))
        if self.initial_bot:
            matches = [
                bot
                for bot in self.bots
                if bot.id == self.initial_bot
                or bot.name.casefold() == self.initial_bot.casefold()
            ]
            if len(matches) == 1:
                self.open_bot(matches[0])
            else:
                self.notify(f"Bot selector is unknown or ambiguous: {self.initial_bot}")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {"printable_stub", "help"} and isinstance(
            self.focused, (Input, TextArea)
        ):
            return False
        return super().check_action(action, parameters)

    def action_stub(self, action: str) -> None:
        self.notify(f"{action}: not built yet")

    def action_printable_stub(self, action: str) -> None:
        self.action_stub(action)

    def open_bot(self, bot: Bot) -> None:
        if isinstance(self.screen, HomeScreen):
            self.push_screen(SessionScreen(bot.id, bot_name=bot.name))

    def action_open(self) -> None:
        if self.bots:
            self.open_bot(self.bots[0])

    def action_open_number(self, number: int) -> None:
        if number <= len(self.bots):
            self.open_bot(self.bots[number - 1])

    def action_help(self) -> None:
        if not isinstance(self.screen, HelpScreen):
            self.push_screen(HelpScreen(SHELL_BINDINGS))

    def action_escape(self) -> None:
        if not isinstance(self.screen, HomeScreen):
            self.pop_screen()

    def action_request_exit(self) -> None:
        now = monotonic()
        if self._exit_requested_at is not None and now - self._exit_requested_at <= 2:
            self.exit()
        else:
            self._exit_requested_at = now
            self.notify("Press Ctrl+C again to exit", timeout=2)
