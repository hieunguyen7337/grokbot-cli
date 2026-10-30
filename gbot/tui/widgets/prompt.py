"""A service-free permission prompt for pending cards."""

from dataclasses import dataclass

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Input, Static

from gbot.output import terminal_safe
from gbot.service.models import Action, Card
from gbot.tui.glyphs import glyphs
from gbot.tui.screens.draft import DraftEditor


@dataclass(frozen=True)
class _Choice:
    label: str
    action: Action | None
    confirm: bool = False
    effect: str = ""


class CardPrompt(VerticalScroll, can_focus=True):
    DEFAULT_CSS = """
    CardPrompt { height: auto; max-height: 100%; border: round $accent; padding: 0 1; }
    CardPrompt Static { height: auto; }
    CardPrompt #prompt-choices { margin-top: 1; }
    CardPrompt #prompt-hint { color: $text-muted; }
    CardPrompt Input { height: 3; }
    """

    class Chosen(Message):
        def __init__(
            self, card: Card, action: Action, confirm: bool, effect: str
        ) -> None:
            super().__init__()
            self.card, self.action, self.confirm, self.effect = (
                card,
                action,
                confirm,
                effect,
            )

    class Later(Message):
        def __init__(self, card: Card) -> None:
            super().__init__()
            self.card = card

    def __init__(self, card: Card, *, ascii_only: bool = False) -> None:
        super().__init__()
        self.card = card
        self.symbols = glyphs(ascii_only)
        self.pointer = 0
        self.expanded = False
        # A card whose allowed actions match no choice here is answered in the app.
        self.choices = self._choices() or [_Choice("Later", None)]
        self.app_only = all(choice.label == "Later" for choice in self.choices)

    def _choices(self) -> list[_Choice]:
        card = self.card
        if not card.allowed_actions:
            return [_Choice("Later", None)]
        if card.draft is not None:
            choices = [
                _Choice("Send", Action("approve"), True, "Sent"),
                _Choice("Discard", Action("deny"), True, "Discarded"),
                _Choice("Edit", None),
            ]
            return [
                choice
                for choice in choices
                if (choice.action.kind if choice.action else "approve")
                in card.allowed_actions
            ]
        if card.type == "local-tool-permission":
            return [
                _Choice("Allow once", Action("approve"), True, "Allowed once"),
                _Choice(
                    "Always allow",
                    Action("approve", always=True),
                    True,
                    "Always allowed",
                ),
                _Choice("Deny", Action("deny"), effect="Denied"),
                _Choice(
                    "Never allow", Action("deny", never=True), effect="Never allowed"
                ),
            ]
        if card.type == "widget":
            return [
                *[
                    _Choice(
                        option,
                        Action("respond", value=option),
                        effect=f"Answered {option}",
                    )
                    for option in card.options or []
                ],
                _Choice("Dismiss", Action("dismiss"), effect="Dismissed"),
            ]
        if card.type in {"user-form", "secret-request"}:
            choices = [
                _Choice(
                    "Submit",
                    Action("secret" if card.type == "secret-request" else "respond"),
                    card.type == "secret-request",
                    "Secret submitted"
                    if card.type == "secret-request"
                    else "Submitted",
                )
            ]
            if "dismiss" in card.allowed_actions:
                choices.append(
                    _Choice("Dismiss", Action("dismiss"), effect="Dismissed")
                )
            return choices
        return [
            choice
            for choice in [
                _Choice("Approve", Action("approve"), True, "Approved"),
                _Choice("Deny", Action("deny"), effect="Denied"),
            ]
            if choice.action and choice.action.kind in card.allowed_actions
        ]

    def compose(self) -> ComposeResult:
        yield Static(Text(terminal_safe(f"{self.card.bot_name} · {self.card.type}")))
        yield Static(Text(terminal_safe(self.card.summary)))
        yield Static(self._body(), id="prompt-body")
        if self.app_only:
            yield Static(Text("Answer this in the Grok Bot app"))
        elif self.card.type == "user-form":
            for index, field in enumerate(self.card.fields or []):
                label = str(field.get("label") or field.get("id") or "Field")
                yield Static(
                    Text(terminal_safe(label + (" *" if field.get("required") else "")))
                )
                yield Input(id=f"field-{index}")
        elif self.card.type == "secret-request":
            yield Input(password=True, id="secret-value")
        yield Static(self._choice_text(), id="prompt-choices")
        yield Static(Text("esc later · enter choose · 1-9 pick"), id="prompt-hint")

    def _body(self) -> Text:
        text = self.card.tool_text
        prefix = ""
        if self.card.draft is not None:
            body = str(self.card.draft.get("body", ""))
            if body and text.endswith(body):
                prefix, text = text[: -len(body)], body
        lines = terminal_safe(text).splitlines()
        if len(lines) > 8 and not self.expanded:
            lines = [*lines[:8], f"{self.symbols.ellipsis} e to expand"]
        elif len(lines) > 8:
            lines.append("e to collapse")
        return Text(terminal_safe(prefix) + "\n".join(lines))

    def _choice_text(self) -> Text:
        return Text(
            "\n".join(
                terminal_safe(
                    f"{self.symbols.pin if index == self.pointer else ' '} {index + 1}. {choice.label}"
                )
                for index, choice in enumerate(self.choices)
            )
        )

    def on_mount(self) -> None:
        self.focus()

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self.post_message(self.Later(self.card))
            return
        if isinstance(self.app.focused, Input) and event.key != "enter":
            return
        if event.key in {"up", "down"}:
            self.pointer = (self.pointer + (1 if event.key == "down" else -1)) % len(
                self.choices
            )
            self.query_one("#prompt-choices", Static).update(self._choice_text())
        elif event.key == "e":
            self.expanded = not self.expanded
            self.query_one("#prompt-body", Static).update(self._body())
        elif event.key == "enter":
            self.choose(self.pointer)
        elif event.key in "123456789" and len(event.key) == 1:
            self.choose(int(event.key) - 1)
        else:
            return
        event.stop()
        event.prevent_default()

    def choose(self, index: int) -> None:
        if not 0 <= index < len(self.choices):
            return
        choice = self.choices[index]
        action = choice.action
        if action is None:
            if choice.label == "Edit":
                self.app.push_screen(DraftEditor(self.card), self._edited)
            else:
                self.post_message(self.Later(self.card))
            return
        if action.kind == "secret":
            field = self.query_one("#secret-value", Input)
            action = Action("secret", secret=field.value)
            field.value = ""
        elif action.kind == "respond" and self.card.type == "user-form":
            values: list[tuple[str, str]] = []
            for field_index, spec in enumerate(self.card.fields or []):
                value = self.query_one(f"#field-{field_index}", Input).value
                if spec.get("required") and not value.strip():
                    self.app.notify("Fill all required fields", markup=False)
                    return
                values.append((str(spec.get("id") or ""), value))
            action = Action("respond", fields=tuple(values))
        self.post_message(self.Chosen(self.card, action, choice.confirm, choice.effect))

    def _edited(self, draft: dict[str, object] | None) -> None:
        if draft is not None:
            self.post_message(
                self.Chosen(self.card, Action("approve", draft=draft), True, "Sent")
            )
