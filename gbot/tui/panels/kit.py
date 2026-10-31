"""Service-independent list, detail and form screens."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import ClassVar, Literal, cast

from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Input, Select, Static, Switch, TextArea

from gbot.output import terminal_safe
from gbot.service.errors import refusal
from gbot.tui.screens.confirm import ConfirmScreen


def _error_text(error: BaseException) -> str:
    # A server refusal reads as its own sentence, not as the transport's error text.
    notice = refusal(error)
    return notice.message if notice else str(error)


@dataclass(frozen=True)
class PanelRow:
    key: str
    label: str
    detail: str = ""
    status: str = ""
    tone: Literal["", "ok", "warn", "error", "muted"] = ""


@dataclass(frozen=True)
class PanelAction:
    key: str
    label: str
    run: Callable[..., object]
    confirm: str | None = None


@dataclass(frozen=True)
class Detail:
    fields: Sequence[tuple[str, str]]
    body: str = ""
    actions: Sequence[PanelAction] = ()


@dataclass(frozen=True)
class FormField:
    name: str
    label: str
    kind: Literal["text", "password", "choice", "toggle", "multiline"] = "text"
    value: str | bool = ""
    choices: Sequence[str] = ()
    required: bool = False
    validate: Callable[[str], str | None] | None = None
    hint: str = ""


class _Panel(Screen):
    DEFAULT_CSS = """
    _Panel { layout: vertical; border: round $accent; padding: 0 1; }
    _Panel .panel-title { height: 1; text-style: bold; }
    _Panel .panel-content { height: 1fr; }
    _Panel .panel-footer { height: 1; color: $text-muted; }
    _Panel Static { height: auto; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True)
    ]

    def __init__(self, title: str) -> None:
        super().__init__()
        self.heading = title

    def action_back(self) -> None:
        self.app.pop_screen()

    def bot_name(self) -> str:
        from gbot.tui.app import GbotApp
        from gbot.tui.screens.home import HomeScreen
        from gbot.tui.screens.session import SessionScreen

        app = cast(GbotApp, self.app)
        for screen in reversed(app.screen_stack):
            if isinstance(screen, SessionScreen):
                return screen.bot_name
            if isinstance(screen, HomeScreen):
                bot = app.state.bots.get(screen.bot_list.selected_id or "")
                return bot.name if bot else ""
        return ""

    def invoke(self, action: PanelAction, *args: object) -> None:
        def execute(confirmed: bool | None) -> None:
            if confirmed:
                action.run(*args)

        if action.confirm:
            name = self.bot_name()
            self.app.push_screen(
                ConfirmScreen(
                    action.label, f"{action.confirm}\n{name}".strip(), action.label
                ),
                execute,
            )
        else:
            execute(True)


class ListPanel(_Panel):
    def __init__(
        self,
        title: str,
        load: Callable[[], Sequence[PanelRow]],
        *,
        on_select: Callable[[PanelRow], None] | None = None,
        empty: str = "Nothing here",
        actions: Sequence[PanelAction] = (),
        filterable: bool = False,
    ) -> None:
        super().__init__(title)
        self.load, self.on_select, self.empty, self.actions, self.filterable = (
            load,
            on_select,
            empty,
            actions,
            filterable,
        )
        self.rows: list[PanelRow] = []
        self.index = 0
        self.selected_key: str | None = None
        self.error = ""

    def compose(self) -> ComposeResult:
        yield Static(Text(terminal_safe(self.heading)), classes="panel-title")
        if self.filterable:
            yield Input(placeholder="Filter", id="panel-filter")
        with VerticalScroll(classes="panel-content"):
            yield Static("Loading…", id="panel-rows", markup=False)
        from gbot.tui.app import GbotApp

        separator = cast(GbotApp, self.app).symbols.separator
        yield Static(
            f"↑↓ select {separator} enter open {separator} esc back"
            + "".join(f" {separator} {a.key} {a.label}" for a in self.actions),
            classes="panel-footer",
            markup=False,
        )

    def on_mount(self) -> None:
        self.reload()

    def reload(self) -> None:
        if self.visible_rows:
            self.selected_key = self.visible_rows[self.index].key
        self.query_one("#panel-rows", Static).update("Loading…")
        self._load()

    @work(thread=True, exit_on_error=False, exclusive=True)
    def _load(self) -> None:
        try:
            rows = list(self.load())
        except Exception as error:  # noqa: BLE001 - panel boundary
            self.app.call_from_thread(
                self._loaded, [], terminal_safe(_error_text(error)).split("\n", 1)[0]
            )
        else:
            self.app.call_from_thread(self._loaded, rows, "")

    def _loaded(self, rows: list[PanelRow], error: str) -> None:
        self.rows, self.error = rows, error
        self.index = next(
            (
                i
                for i, row in enumerate(self.visible_rows)
                if row.key == self.selected_key
            ),
            0,
        )
        self._draw()

    @property
    def visible_rows(self) -> list[PanelRow]:
        value = (
            self.query_one("#panel-filter", Input).value.casefold()
            if self.is_mounted and self.filterable
            else ""
        )
        return [row for row in self.rows if value in row.label.casefold()]

    def _draw(self) -> None:
        rows = self.visible_rows
        self.index = min(self.index, max(0, len(rows) - 1))
        result = Text()
        if self.error:
            result.append(f"{self.error} · r retry")
        elif not rows:
            result.append(terminal_safe(self.empty))
        else:
            for i, row in enumerate(rows):
                result.append(
                    f"{'>' if i == self.index else ' '} {terminal_safe(row.label)}"
                )
                if row.detail:
                    result.append(f"  {terminal_safe(row.detail)}", style="dim")
                if row.status:
                    styles = {
                        "ok": "green",
                        "warn": "yellow",
                        "error": "red",
                        "muted": "dim",
                    }
                    result.append(
                        f"  {terminal_safe(row.status)}", style=styles.get(row.tone, "")
                    )
                result.append("\n")
        self.query_one("#panel-rows", Static).update(result)

    def on_input_changed(self, event: Input.Changed) -> None:
        self.index = 0
        self._draw()

    def on_key(self, event: events.Key) -> None:
        if isinstance(self.focused, Input) and event.key not in {
            "escape",
            "down",
            "up",
            "enter",
        }:
            return
        rows = self.visible_rows
        if event.key == "/" and self.filterable:
            self.query_one("#panel-filter", Input).focus()
        elif event.key in {"up", "down"} and rows:
            self.index = (self.index + (1 if event.key == "down" else -1)) % len(rows)
            self._draw()
        elif event.key == "enter" and rows and self.on_select:
            self.on_select(rows[self.index])
        elif event.key == "r" and self.error:
            self.reload()
        else:
            action = next((a for a in self.actions if a.key == event.key), None)
            if not action or not rows:
                return
            self.invoke(action, rows[self.index])
        event.stop()
        event.prevent_default()


class DetailPanel(_Panel):
    def __init__(self, title: str, load: Callable[[], Detail]) -> None:
        super().__init__(title)
        self.load = load
        self.detail = Detail(())
        self.index = 0

    def compose(self) -> ComposeResult:
        yield Static(Text(terminal_safe(self.heading)), classes="panel-title")
        with VerticalScroll(classes="panel-content"):
            yield Static("Loading…", id="detail-content", markup=False)
        yield Static(
            "↑↓ select · enter open · esc back", classes="panel-footer", markup=False
        )

    def on_mount(self) -> None:
        try:
            self.detail = self.load()
            self._draw()
        except Exception as error:  # noqa: BLE001 - panel boundary
            self.query_one("#detail-content", Static).update(
                Text(terminal_safe(_error_text(error)))
            )

    def _draw(self) -> None:
        width = max((len(label) for label, _ in self.detail.fields), default=0)
        lines = [
            f"{terminal_safe(label):<{width}}  {terminal_safe(value)}"
            for label, value in self.detail.fields
        ]
        lines.extend(["", terminal_safe(self.detail.body), ""])
        lines.extend(
            f"{'>' if i == self.index else ' '} {i + 1}. {terminal_safe(action.label)}"
            for i, action in enumerate(self.detail.actions)
        )
        self.query_one("#detail-content", Static).update(Text("\n".join(lines)))

    def on_key(self, event: events.Key) -> None:
        actions = self.detail.actions
        if not actions:
            return
        if event.key in {"up", "down"}:
            self.index = (self.index + (1 if event.key == "down" else -1)) % len(
                actions
            )
            self._draw()
        elif event.key == "enter":
            self.invoke(actions[self.index])
        elif (
            event.key in "123456789"
            and len(event.key) == 1
            and int(event.key) <= len(actions)
        ):
            self.invoke(actions[int(event.key) - 1])
        else:
            return
        event.stop()
        event.prevent_default()


class FormPanel(_Panel):
    BINDINGS: ClassVar[list[BindingType]] = [
        *_Panel.BINDINGS,
        Binding("ctrl+s", "submit", "Save", priority=True),
    ]

    def __init__(
        self,
        title: str,
        fields: Sequence[FormField],
        submit: Callable[[dict[str, str | bool]], str | None],
        *,
        confirm: str | None = None,
        submit_label: str = "Save",
    ) -> None:
        super().__init__(title)
        self.fields, self.submit, self.confirm, self.submit_label = (
            fields,
            submit,
            confirm,
            submit_label,
        )

    def compose(self) -> ComposeResult:
        yield Static(Text(terminal_safe(self.heading)), classes="panel-title")
        with VerticalScroll(classes="panel-content"):
            for i, field in enumerate(self.fields):
                yield Static(
                    Text(terminal_safe(field.label + (" *" if field.required else "")))
                )
                if field.kind == "choice":
                    yield Select(
                        [(terminal_safe(v), v) for v in field.choices],
                        value=field.value
                        if field.value in field.choices
                        else Select.BLANK,
                        id=f"form-{i}",
                    )
                elif field.kind == "toggle":
                    yield Switch(value=bool(field.value), id=f"form-{i}")
                elif field.kind == "multiline":
                    yield TextArea(str(field.value), id=f"form-{i}")
                else:
                    yield Input(
                        value=str(field.value),
                        password=field.kind == "password",
                        id=f"form-{i}",
                    )
                yield Static(Text(terminal_safe(field.hint)), id=f"form-error-{i}")
            yield Static("", id="form-notice", markup=False)
        yield Static(
            f"tab next · ctrl+s {terminal_safe(self.submit_label)} · esc back",
            classes="panel-footer",
            markup=False,
        )

    def on_mount(self) -> None:
        if self.fields:
            self.query_one("#form-0").focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        index = int(cast(str, event.input.id).removeprefix("form-"))
        if index + 1 < len(self.fields):
            self.query_one(f"#form-{index + 1}").focus()
        else:
            self.action_submit()

    def action_submit(self) -> None:
        values: dict[str, str | bool] = {}
        first_bad: int | None = None
        secrets = [
            self.query_one(f"#form-{i}", Input).value
            for i, field in enumerate(self.fields)
            if field.kind == "password"
        ]
        for i, field in enumerate(self.fields):
            widget = self.query_one(f"#form-{i}")
            if isinstance(widget, Input):
                value: str | bool = widget.value
                if field.kind == "password":
                    widget.value = ""
            elif isinstance(widget, TextArea):
                value = widget.text
            elif isinstance(widget, Switch):
                value = widget.value
            else:
                selected = cast(Select, widget).value
                value = selected if isinstance(selected, str) else ""
            values[field.name] = value
            error = (
                "Required"
                if field.required
                and (not value or (isinstance(value, str) and not value.strip()))
                else None
            )
            if not error and field.validate and isinstance(value, str):
                error = field.validate(value)
            for secret in secrets:
                if secret and error:
                    error = error.replace(secret, "[redacted]")
            self.query_one(f"#form-error-{i}", Static).update(
                Text(terminal_safe(error or field.hint))
            )
            if error and first_bad is None:
                first_bad = i
        if first_bad is not None:
            self.query_one(f"#form-{first_bad}").focus()
            return

        def confirmed(result: bool | None) -> None:
            if result:
                self._submit(values, secrets)

        if self.confirm:
            details = f"{self.confirm}\n{self.bot_name()}".strip()
            self.app.push_screen(
                ConfirmScreen(self.heading, details, self.submit_label), confirmed
            )
        else:
            confirmed(True)

    @work(thread=True, exit_on_error=False)
    def _submit(self, values: dict[str, str | bool], secrets: list[str]) -> None:
        try:
            result = self.submit(values)
        except Exception as error:  # noqa: BLE001 - panel boundary
            message = _error_text(error)
            for secret in secrets:
                if secret:
                    message = message.replace(secret, "[redacted]")
            self.app.call_from_thread(
                self._submit_error, terminal_safe(message).split("\n", 1)[0]
            )
        else:
            message = result or ""
            for secret in secrets:
                if secret:
                    message = message.replace(secret, "[redacted]")
            self.app.call_from_thread(self._submit_done, terminal_safe(message))

    def _submit_error(self, message: str) -> None:
        self.query_one("#form-notice", Static).update(Text(message))

    def _submit_done(self, message: str) -> None:
        if message:
            self.app.notify(message, markup=False)
        self.app.pop_screen()
