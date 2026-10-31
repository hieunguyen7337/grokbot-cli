"""Bot skills and the shared skill catalog."""

from collections.abc import Callable, Mapping

from rich.text import Text
from textual import events
from textual.message import Message
from textual.widgets import Input, Static

from gbot.output import terminal_safe
from gbot.service import workflows as service
from gbot.service.events import Other
from gbot.tui.app import ServiceEvent
from gbot.tui.panels.kit import Detail, FormField, ListPanel, PanelAction, PanelRow
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.attachments import file_path
from gbot.tui.slash.avatar_voice import _confirm, _Detail, _Form
from gbot.tui.slash.rooms import _writable
from gbot.tui.slash.templates import _TemplatesPanel


class _Skills(_TemplatesPanel):
    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        self.bot = ctx.app.state.bots[ctx.bot_id or ""]
        self.skills: dict[str, service.Skill] = {}
        super().__init__(
            f"{self.bot.name} skills",
            self.load_skills,
            on_select=self.open_skill,
            empty="No skills · n new · i import · c catalog",
        )

    def on_mount(self) -> None:
        self.ctx.app.message_signal.subscribe(self, self.changed)
        super().on_mount()

    def on_unmount(self) -> None:
        self.ctx.app.message_signal.unsubscribe(self)

    def changed(self, message: Message) -> None:
        if not isinstance(message, ServiceEvent) or not isinstance(
            message.event, Other
        ):
            return
        event = message.event
        if (
            event.channel in {"workflows", "bot-skills"}
            and isinstance(event.payload, Mapping)
            and event.payload.get("agentId") == self.bot.id
        ):
            self.reload()

    def load_skills(self) -> list[PanelRow]:
        try:
            items = service.skills(self.ctx.service.transport, self.bot.id)
        except Exception as error:
            self.ctx.app.call_from_thread(self.ctx.app.service_error, error)
            raise
        self.skills = {item.id: item for item in items}
        rows = []
        for title, group in (
            ("Yours", [item for item in items if item.editable and not item.schedule]),
            ("Scheduled", [item for item in items if item.schedule]),
            (
                "Managed",
                [item for item in items if not item.editable and not item.schedule],
            ),
        ):
            if group:
                rows.append(PanelRow(f"heading:{title}", title))
                rows.extend(
                    PanelRow(
                        item.id,
                        item.name,
                        f"{item.source} · {item.schedule_description or item.schedule or 'Unscheduled'}"
                        + (
                            " (paused)"
                            if item.schedule and not item.schedule_enabled
                            else ""
                        ),
                    )
                    for item in group
                )
        return rows

    def skill_actions(self, skill: service.Skill) -> list[PanelAction]:
        actions = []
        if skill.editable:
            actions.extend(
                (
                    PanelAction("e", "Edit", lambda: self.form(skill)),
                    PanelAction("x", "Delete", lambda: self.delete_skill(skill)),
                )
            )
        if skill.schedule:
            actions.append(PanelAction("R", "Run now", lambda: self.run_now(skill)))
        return actions

    def _draw(self) -> None:
        super()._draw()
        selected = self.visible_rows[self.index] if self.visible_rows else None
        skill = self.skills.get(selected.key) if selected else None
        actions = self.skill_actions(skill) if skill else []
        self.query_one(".panel-footer", Static).update(
            "↑↓ select · enter open · n New · i Import · c Catalog"
            + "".join(f" · {action.key} {action.label}" for action in actions)
            + " · esc back"
        )

    def on_key(self, event: events.Key) -> None:
        handlers: dict[str, Callable[..., object]] = {
            "n": lambda: self.form(),
            "i": self.import_skill,
            "c": lambda: skill_catalog(self.ctx, ""),
        }
        if self.visible_rows:
            skill = self.skills.get(self.visible_rows[self.index].key)
            if skill:
                handlers.update(
                    {action.key: action.run for action in self.skill_actions(skill)}
                )
        if event.key in handlers:
            handlers[event.key]()
            event.stop()
            event.prevent_default()
        else:
            super().on_key(event)

    def open_skill(self, row: PanelRow) -> None:
        skill = self.skills.get(row.key)
        if skill is None:
            return
        self.ctx.app.push_screen(
            _Detail(
                skill.name,
                lambda: Detail(
                    (
                        ("Source", skill.source),
                        (
                            "Schedule",
                            skill.schedule_description
                            or skill.schedule
                            or "Unscheduled",
                        ),
                        ("Last run", str(skill.last_run_at_ms or "Never")),
                        ("Next run", str(skill.next_run_at_ms or "None")),
                    ),
                    body=f"{skill.description}\n\n{skill.body}",
                    actions=self.skill_actions(skill),
                ),
            )
        )

    def return_to_list(self) -> None:
        while self.ctx.app.screen is not self:
            self.ctx.app.pop_screen()
        self.reload()

    def form(self, skill: service.Skill | None = None) -> None:
        if not _writable(self.ctx):
            return
        if skill is not None and not skill.editable:
            return

        def prepare(values: dict[str, str | bool]) -> None:
            name, description, body, schedule = (
                str(values[key]) for key in ("name", "description", "body", "schedule")
            )

            def save() -> None:
                if skill:
                    service.update(
                        self.ctx.service.transport,
                        self.bot.id,
                        skill,
                        name=name,
                        description=description,
                        body=body,
                        schedule=schedule.strip() or None,
                    )
                else:
                    service.create(
                        self.ctx.service.transport,
                        self.bot.id,
                        name=name,
                        description=description,
                        body=body,
                        schedule=schedule.strip() or None,
                    )

            self.ctx.app.call_from_thread(
                _confirm,
                self.ctx,
                f"Save skill {terminal_safe(name)}?",
                save,
                self.return_to_list,
            )

        self.ctx.app.push_screen(
            _Form(
                self.ctx,
                "Edit skill" if skill else "New skill",
                (
                    FormField(
                        "name", "Name", value=skill.name if skill else "", required=True
                    ),
                    FormField(
                        "description",
                        "Description",
                        value=skill.description if skill else "",
                        required=True,
                    ),
                    FormField(
                        "body",
                        "Body",
                        "multiline",
                        skill.body if skill else "",
                        required=True,
                    ),
                    FormField(
                        "schedule",
                        "Schedule",
                        value=skill.schedule or "" if skill else "",
                        hint="Leave blank for an unscheduled skill",
                    ),
                ),
                prepare,
            )
        )

    def delete_skill(self, skill: service.Skill) -> None:
        _confirm(
            self.ctx,
            f"Delete skill {terminal_safe(skill.name)}?",
            lambda: service.delete(self.ctx.service.transport, self.bot.id, skill),
            self.return_to_list,
        )

    def run_now(self, skill: service.Skill) -> None:
        _confirm(
            self.ctx,
            f"Run skill {terminal_safe(skill.name)} now?",
            lambda: service.run_now(self.ctx.service.transport, self.bot.id, skill),
            self.return_to_list,
        )

    def import_skill(self) -> None:
        if not _writable(self.ctx):
            return

        def prepare(values: dict[str, str | bool]) -> None:
            value = str(values["location"]).strip()

            def save() -> None:
                if value.lower().startswith(("http://", "https://")):
                    count, rows = service.import_url(
                        self.ctx.service.transport, self.bot.id, value
                    )
                else:
                    count, rows = service.import_text(
                        self.ctx.service.transport,
                        self.bot.id,
                        file_path(value).read_text(encoding="utf-8"),
                    )
                self.ctx.app.call_from_thread(
                    self.ctx.app.notify,
                    f"Workflows: {len(rows) - count} → {len(rows)} ({count:+d})",
                    markup=False,
                )

            self.ctx.app.call_from_thread(
                _confirm,
                self.ctx,
                "Import skill?",
                save,
                self.return_to_list,
                terminal_safe(value),
            )

        self.ctx.app.push_screen(
            _Form(
                self.ctx,
                "Import skill",
                (FormField("location", "URL or file path", required=True),),
                prepare,
            )
        )


class _Catalog(ListPanel):
    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        self.entries: dict[str, service.CatalogSkill] = {}
        super().__init__(
            "Skill catalog",
            self.load_catalog,
            on_select=self.open_skill,
            filterable=True,
        )

    def on_mount(self) -> None:
        super().on_mount()
        if self.ctx.bot_id:
            self.query_one(".panel-footer", Static).update(
                "↑↓ select · enter open · / filter · a Add skill · esc back"
            )

    def load_catalog(self) -> list[PanelRow]:
        try:
            entries = service.catalog(self.ctx.service.transport)
        except Exception as error:
            self.ctx.app.call_from_thread(self.ctx.app.service_error, error)
            raise
        self.entries = {entry.id: entry for entry in entries}
        return [PanelRow(entry.id, entry.name, entry.publisher) for entry in entries]

    @property
    def visible_rows(self) -> list[PanelRow]:
        value = (
            self.query_one("#panel-filter", Input).value.casefold()
            if self.is_mounted
            else ""
        )
        matches = [
            row
            for row in self.rows
            if value
            in f"{row.label} {row.detail} {self.entries[row.key].description}".casefold()
        ]
        rows = matches[:200]
        if len(matches) > 200:
            rows.append(PanelRow("more:", f"{len(matches) - 200} more; type to narrow"))
        return rows

    def _draw(self) -> None:
        super()._draw()
        widget = self.query_one("#panel-rows", Static)
        if (
            isinstance(widget.content, Text)
            and self.visible_rows
            and self.visible_rows[-1].key == "more:"
        ):
            text = widget.content.copy()
            start = text.plain.rfind("\n", 0, len(text.plain) - 1) + 1
            text.stylize("dim", start, len(text))
            widget.update(text)

    def add(self, entry: service.CatalogSkill) -> None:
        bot = self.ctx.app.state.bots.get(self.ctx.bot_id or "")
        if bot:

            def save() -> None:
                count, rows = service.install(self.ctx.service.transport, bot.id, entry)
                self.ctx.app.call_from_thread(
                    self.ctx.app.notify,
                    f"Workflows: {len(rows) - count} → {len(rows)} ({count:+d})",
                    markup=False,
                )

            _confirm(
                self.ctx,
                f"Add skill {terminal_safe(entry.name)} to {terminal_safe(bot.name)}?",
                save,
                self.reload,
            )

    def open_skill(self, row: PanelRow) -> None:
        entry = self.entries.get(row.key)
        if entry:
            actions = (
                (PanelAction("a", "Add skill", lambda: self.add(entry)),)
                if self.ctx.bot_id
                else ()
            )
            self.ctx.app.push_screen(
                _Detail(
                    entry.name,
                    lambda: Detail(
                        (("Publisher", entry.publisher),), entry.description, actions
                    ),
                )
            )

    def on_key(self, event: events.Key) -> None:
        if event.key in {"up", "down"}:
            self.set_focus(None)
        if (
            event.key == "a"
            and not isinstance(self.focused, Input)
            and self.ctx.bot_id
            and self.visible_rows
        ):
            entry = self.entries.get(self.visible_rows[self.index].key)
            if entry:
                self.add(entry)
                event.stop()
                event.prevent_default()
                return
        super().on_key(event)


def skills(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(_Skills(ctx))


def skill_catalog(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(_Catalog(ctx))


COMMANDS = (
    SlashCommand(
        "skills", "Read and manage bot skills", skills, scope="session", needs_bot=True
    ),
    SlashCommand("skill-catalog", "Browse the skill catalog", skill_catalog),
)
