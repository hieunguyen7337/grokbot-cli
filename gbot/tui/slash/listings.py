"""Publish a bot's skills and take plugin listings down."""

from collections.abc import Callable

from rich.text import Text
from textual import events
from textual.widgets import Static

from gbot.output import terminal_safe
from gbot.service import listings as service
from gbot.service import plugins as plugin_service
from gbot.service import workflows
from gbot.service.errors import refusal
from gbot.tui.panels.kit import ListPanel, PanelRow
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.rooms import _writable

Key = tuple[str, str, Callable[[], None]]


def _notice(ctx: SlashContext, error: Exception) -> None:
    # A refusal (a team-only call on a personal account, a bot the gateway does not serve) is a sentence,
    # not a failure.
    notice = refusal(error)
    ctx.app.notify(
        terminal_safe(notice.message if notice else str(error)),
        severity="warning" if notice else "error",
        markup=False,
    )


def _worker(
    ctx: SlashContext, work: Callable[[], object], done: Callable[[object], object]
) -> None:
    def run() -> None:
        try:
            result = work()
        except Exception as error:  # noqa: BLE001 - worker boundary
            ctx.app.call_from_thread(_notice, ctx, error)
        else:
            ctx.app.call_from_thread(done, result)

    ctx.app.run_worker(run, thread=True, exit_on_error=False)


def _confirm(
    ctx: SlashContext,
    title: str,
    details: str,
    label: str,
    work: Callable[[], object],
    done: Callable[[object], object],
) -> None:
    if not _writable(ctx):
        return

    def confirmed(ok: bool | None) -> None:
        if not ok or not _writable(ctx):
            return

        def run() -> object:
            if ctx.app.read_only:
                raise ValueError("Read-only mode")
            return work()

        _worker(ctx, run, done)

    ctx.app.push_screen(ConfirmScreen(terminal_safe(title), details, label), confirmed)


class _Listings(ListPanel):
    """A list whose keys depend on the selected row and on what the server offers."""

    def __init__(
        self, ctx: SlashContext, title: str, empty: str, header: str = ""
    ) -> None:
        self.ctx = ctx
        self.bot = ctx.app.state.bots[ctx.bot_id or ""]
        self.header = header
        super().__init__(f"{self.bot.name} {title}", self.rows_for, empty=empty)

    def rows_for(self) -> list[PanelRow]:
        raise NotImplementedError

    def keys(self, row: PanelRow | None) -> list[Key]:
        raise NotImplementedError

    def selected(self) -> PanelRow | None:
        rows = self.visible_rows
        return rows[self.index] if rows and not self.error else None

    def _draw(self) -> None:
        super()._draw()
        widget = self.query_one("#panel-rows", Static)
        content = widget.content
        if self.header and isinstance(content, Text):
            widget.update(
                Text(terminal_safe(self.header) + "\n\n", style="dim") + content
            )
        self.query_one(".panel-footer", Static).update(
            "↑↓ select"
            + "".join(
                f" · {key} {label}" for key, label, _ in self.keys(self.selected())
            )
            + " · esc back"
        )

    def on_key(self, event: events.Key) -> None:
        handler = next(
            (run for key, _, run in self.keys(self.selected()) if key == event.key),
            None,
        )
        if handler is None:
            super().on_key(event)
            return
        handler()
        event.stop()
        event.prevent_default()

    def done(self, result: object) -> None:
        if isinstance(result, service.ListingResult) and not result.ok:
            self.ctx.app.notify(
                terminal_safe(result.message or "The server did not accept this."),
                severity="warning",
                markup=False,
            )
        else:
            text = (
                " · ".join(
                    part
                    for part in (
                        getattr(result, "state", ""),
                        getattr(result, "message", ""),
                    )
                    if part
                )
                or "Done"
            )
            self.ctx.app.notify(terminal_safe(text), markup=False)
        self.reload()


class SkillPublishPanel(_Listings):
    def __init__(self, ctx: SlashContext) -> None:
        self.skills: dict[str, workflows.Skill] = {}
        self.targets = service.PublishTargets(())
        super().__init__(ctx, "skill publishing", "No skills of your own to publish")

    def rows_for(self) -> list[PanelRow]:
        transport = self.ctx.service.transport
        try:
            targets = service.publish_targets(transport)
            header = (
                "Targets: " + ", ".join(team.name for team in targets.teams)
                if targets.teams
                else targets.unavailable_reason or "No publish targets available"
            )
        except Exception as error:
            notice = refusal(error)
            if notice is None:
                raise
            targets, header = service.PublishTargets(()), notice.message
        items = [
            skill
            for skill in workflows.skills(transport, self.bot.id)
            if skill.editable
        ]
        self.targets, self.header = targets, header
        self.skills = {skill.id: skill for skill in items}
        return [PanelRow(skill.id, skill.name, skill.id) for skill in items]

    def keys(self, row: PanelRow | None) -> list[Key]:
        skill = self.skills.get(row.key) if row else None
        keys: list[Key] = []
        if skill is not None:
            if self.targets.teams:
                keys.append(("p", "Publish", lambda: self.publish(skill)))
            keys.append(("r", "Resync", lambda: self.resync(skill)))
            keys.append(("u", "Unpublish", lambda: self.unpublish(skill)))
        keys.append(("g", "Reload", self.reload))
        return keys

    def publish(self, skill: workflows.Skill) -> None:
        if not _writable(self.ctx) or not self.targets.teams:
            return
        if len(self.targets.teams) == 1:
            self.publish_to(skill, self.targets.teams[0])
            return
        teams = {team.team_id: team for team in self.targets.teams}

        def chosen(row: PanelRow) -> None:
            self.ctx.app.pop_screen()
            # The confirm's callback must run on the app, not on the chooser that just closed.
            self.ctx.app.call_later(self.publish_to, skill, teams[row.key])

        self.ctx.app.push_screen(
            ListPanel(
                f"Publish {skill.name} to",
                lambda: [
                    PanelRow(t.team_id, t.name, t.team_id) for t in teams.values()
                ],
                on_select=chosen,
            )
        )

    def publish_to(self, skill: workflows.Skill, team: service.Target) -> None:
        _confirm(
            self.ctx,
            f"Publish {skill.name} to {team.name}?",
            f"Bot: {self.bot.name}",
            "Publish",
            lambda: service.publish_skill(
                self.ctx.service.transport, skill.id, team.team_id
            ),
            self.done,
        )

    def resync(self, skill: workflows.Skill) -> None:
        _confirm(
            self.ctx,
            f"Resync {skill.name}?",
            f"Bot: {self.bot.name}",
            "Resync",
            lambda: service.resync_skill(self.ctx.service.transport, skill.id),
            self.done,
        )

    def unpublish(self, skill: workflows.Skill) -> None:
        _confirm(
            self.ctx,
            f"Unpublish {skill.name}?",
            f"Bot: {self.bot.name}",
            "Unpublish",
            lambda: service.unpublish_skill(self.ctx.service.transport, skill.id),
            self.done,
        )


class PluginListingPanel(_Listings):
    def __init__(self, ctx: SlashContext) -> None:
        self.plugins: dict[str, plugin_service.Plugin] = {}
        super().__init__(ctx, "plugin listings", "This bot has no plugins")

    def rows_for(self) -> list[PanelRow]:
        items = [
            plugin
            for plugin in plugin_service.bot_plugins(
                self.ctx.service.transport, self.bot.id
            )
            if not plugin.is_bot_skills
        ]
        self.plugins = {str(plugin.plugin_id): plugin for plugin in items}
        return [
            PanelRow(str(plugin.plugin_id), plugin.display_name, str(plugin.plugin_id))
            for plugin in items
        ]

    def keys(self, row: PanelRow | None) -> list[Key]:
        plugin = self.plugins.get(row.key) if row else None
        keys: list[Key] = []
        if plugin is not None:
            keys.append(("u", "Take listing down", lambda: self.take_down(plugin)))
        keys.append(("g", "Reload", self.reload))
        return keys

    def take_down(self, plugin: plugin_service.Plugin) -> None:
        if not _writable(self.ctx):
            return
        key, name = str(plugin.plugin_id), plugin.display_name

        def asked(restorable: object) -> None:
            _confirm(
                self.ctx,
                f"Remove the {name} listing? "
                + (
                    "A private copy stays."
                    if restorable
                    else "No private copy remains."
                ),
                f"Bot: {self.bot.name}",
                "Remove listing",
                lambda: service.unpublish_plugin_listing(
                    self.ctx.service.transport, key
                ),
                self.done,
            )

        _worker(
            self.ctx,
            lambda: service.has_restorable_copy(self.ctx.service.transport, key),
            asked,
        )


def skill_publish(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(SkillPublishPanel(ctx))


def plugin_listing(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(PluginListingPanel(ctx))


COMMANDS = (
    SlashCommand(
        "skill-publish",
        "Publish, resync or unpublish a skill",
        skill_publish,
        scope="session",
        needs_bot=True,
    ),
    SlashCommand(
        "plugin-listing",
        "Take a plugin listing down",
        plugin_listing,
        scope="session",
        needs_bot=True,
    ),
)
