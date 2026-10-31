"""Marketplace listing and template publishing for one bot."""

from collections.abc import Callable

from textual.widgets import Static

from gbot.output import terminal_safe
from gbot.service import publishing as service
from gbot.service.errors import refusal
from gbot.tui.panels.kit import Detail, FormField, PanelAction
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.avatar_voice import _Detail, _Form
from gbot.tui.slash.rooms import _writable
from gbot.tui.slash.teams import _mutate, _worker
from groken.client import ConnectError


def _plain(work: Callable[[], object]) -> Callable[[], object]:
    """Run a call and turn a server refusal into its readable message."""

    def run() -> object:
        try:
            return work()
        except ConnectError as error:
            refused = refusal(error)
            if refused is None:
                raise
            raise ValueError(refused.message) from error

    return run


class PublishPanel(_Detail):
    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        self.bot = ctx.app.state.bots[ctx.bot_id or ""]
        self.state = service.Overview(*service.listing_state(self.bot), None, "unknown")
        self.listing = ""
        self.last = ""
        super().__init__(f"Publish {terminal_safe(self.bot.name)}", self.content)

    def on_mount(self) -> None:
        super().on_mount()
        self.reload()

    @property
    def marketplace(self) -> str:
        return (
            self.state.listing
            if self.state.listing != "unknown"
            else (self.listing or "unknown")
        )

    def content(self) -> Detail:
        state, template, market = self.state, self.state.template, self.marketplace
        actions = []
        if market in {"unpublished", "unknown"}:
            actions.append(PanelAction("p", "List in the marketplace", self.list_bot))
        if market in {"published", "unknown"}:
            actions.append(PanelAction("u", "Take off the marketplace", self.unlist))
        fields = [("Marketplace", market)]
        if self.last:
            fields.append(("Last result", self.last))
        body = [service.policy_sentence(state.policy), *state.notes]
        if template is None:
            fields.append(("Template", "none"))
            body.append("This bot has no template.")
        else:
            fields.extend(
                (
                    ("Template", template.name or "unnamed"),
                    ("Share ID", template.share_id),
                    ("Published", "yes" if template.published else "no"),
                    (
                        "Active version",
                        str(template.active_version or "none"),
                    ),
                    ("Visibility", template.visibility),
                )
            )
            if state.policy != "none":
                actions.extend(
                    (
                        PanelAction("a", "Publish a template version", self.activate),
                        PanelAction("v", "Template visibility", self.visibility),
                        PanelAction("d", "Delete the template", self.delete),
                    )
                )
        actions.append(PanelAction("g", "Reload", self.reload))
        return Detail(tuple(fields), body="\n".join(body), actions=tuple(actions))

    def loaded(self, value: object) -> None:
        if isinstance(value, service.Overview):
            self.state = value
        self.detail = self.content()
        self.index = 0
        self._draw()
        self.query_one(".panel-footer", Static).update(
            " · ".join(f"{a.key} {a.label}" for a in self.detail.actions)
            + " · esc back"
        )

    def reload(self) -> None:
        _worker(
            self.ctx,
            lambda: service.overview(self.ctx.service.transport, self.bot),
            self.loaded,
        )

    def _listed(self, value: object) -> None:
        if isinstance(value, service.PublishResult):
            self.last = value.sentence
            if value.outcome in {"published", "already_published"}:
                self.listing = "published"
            elif value.outcome in {"unpublished", "not_published"}:
                self.listing = "unpublished"
        self.reload()

    def list_bot(self) -> None:
        _mutate(
            self.ctx,
            f"List {self.bot.name} in the Grok Bot marketplace?",
            _plain(
                lambda: service.publish_bot(self.ctx.service.transport, self.bot.id)
            ),
            self._listed,
        )

    def unlist(self) -> None:
        _mutate(
            self.ctx,
            f"Take {self.bot.name} off the Grok Bot marketplace?",
            _plain(
                lambda: service.unpublish_bot(self.ctx.service.transport, self.bot.id)
            ),
            self._listed,
        )

    def _changed(self, value: object) -> None:
        self.last = ""
        self.reload()

    def _form(
        self,
        title: str,
        fields: tuple[FormField, ...],
        review: Callable[[dict[str, str | bool]], tuple[str, Callable[[], object]]],
    ) -> None:
        if not _writable(self.ctx):
            return

        def prepare(values: dict[str, str | bool]) -> None:
            question, work = review(values)

            def confirm() -> None:
                self.ctx.app.pop_screen()
                _mutate(self.ctx, question, _plain(work), self._changed)

            self.ctx.app.call_from_thread(confirm)

        self.ctx.app.push_screen(_Form(self.ctx, title, fields, prepare))

    def activate(self) -> None:
        template = self.state.template
        if template is None:
            return

        def number(text: str) -> str | None:
            return (
                None
                if text.strip().isdecimal() and int(text) >= 1
                else ("Enter a version number")
            )

        def review(values: dict[str, str | bool]):
            version = int(str(values["version"]))
            return (
                f"Publish version {version} of {template.name}?",
                lambda: service.publish_template(
                    self.ctx.service.transport, template.share_id, version
                ),
            )

        self._form(
            "Publish a template version",
            (
                FormField(
                    "version",
                    "Version",
                    "text",
                    str(template.active_version or ""),
                    required=True,
                    validate=number,
                ),
            ),
            review,
        )

    def visibility(self) -> None:
        template = self.state.template
        if template is None:
            return
        choices = ("team",) if self.state.policy == "team_only" else ("public", "team")

        def review(values: dict[str, str | bool]):
            choice = str(values["visibility"])
            return (
                f"Make {template.name} visible to {choice}?",
                lambda: service.set_template_visibility(
                    self.ctx.service.transport, template.share_id, choice
                ),
            )

        self._form(
            "Template visibility",
            (
                FormField(
                    "visibility",
                    "Visible to",
                    "choice",
                    template.visibility if template.visibility in choices else "team",
                    choices,
                    required=True,
                ),
            ),
            review,
        )

    def delete(self) -> None:
        template = self.state.template
        if template is None:
            return
        name = template.name or template.share_id

        def review(values: dict[str, str | bool]):
            if str(values["name"]).strip() != name:
                raise ValueError("Type the template name exactly to delete it")
            return (
                f"Delete the template {name}?",
                lambda: service.delete_template(
                    self.ctx.service.transport, template.share_id
                ),
            )

        self._form(
            "Delete the template",
            (
                FormField(
                    "name",
                    "Template name",
                    "text",
                    "",
                    required=True,
                    hint=f"Type {name} to delete it",
                ),
            ),
            review,
        )


def publish(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(PublishPanel(ctx))


COMMANDS = (
    SlashCommand(
        "publish",
        "List this bot in the marketplace or publish its template",
        publish,
        scope="session",
        needs_bot=True,
    ),
)
