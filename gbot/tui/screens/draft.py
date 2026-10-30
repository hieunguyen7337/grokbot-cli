"""Edit a draft locally; saving does not send it."""

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static, TextArea

from gbot.output import terminal_safe
from gbot.service.models import Card


class DraftEditor(ModalScreen[dict[str, object] | None]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", priority=True)
    ]
    DEFAULT_CSS = """
    DraftEditor { align: center middle; background: $background 80%; }
    DraftEditor > VerticalScroll { width: 76; height: 95%; border: round $accent;
        padding: 1 2; }
    DraftEditor Static { height: auto; }
    DraftEditor Input { margin-bottom: 1; }
    DraftEditor TextArea { height: 8; min-height: 4; }
    DraftEditor Horizontal { height: auto; margin-top: 1; }
    """

    def __init__(self, card: Card) -> None:
        super().__init__()
        self.card = card

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(Text(terminal_safe(f"Edit {self.card.bot_name} draft")))
            keys = (
                (("from", "From"), ("to", "To"), ("cc", "Cc"), ("subject", "Subject"))
                if self.card.type == "email-draft"
                else (("target", "Target"),)
            )
            for key, label in keys:
                yield Static(Text(label))
                yield Input(
                    self._shown(key),
                    id=f"draft-{key}",
                    disabled=key in {"from", "target"},
                )
            yield Static(Text("Body"))
            yield TextArea(self._shown("body"), id="draft-body")
            with Horizontal():
                yield Button("Cancel", id="draft-cancel")
                yield Button("Save", id="draft-save")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id != "draft-save":
            self.dismiss(None)
            return
        # Fields are shown escaped, so only an edited field takes the shown text; the rest keep their original.
        draft = dict(self.card.draft or {})
        if self.card.type == "email-draft":
            for key in ("to", "cc"):
                value = self.query_one(f"#draft-{key}", Input).value
                if value != self._shown(key):
                    draft[key] = [
                        part.strip() for part in value.split(",") if part.strip()
                    ]
            subject = self.query_one("#draft-subject", Input).value
            if subject != self._shown("subject"):
                draft["subject"] = subject
        body = self.query_one("#draft-body", TextArea).text
        if body != self._shown("body"):
            draft["body"] = body
        self.dismiss(draft)

    def _shown(self, key: str) -> str:
        value = (self.card.draft or {}).get(key, "")
        text = (
            ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)
        )
        return terminal_safe(text)
