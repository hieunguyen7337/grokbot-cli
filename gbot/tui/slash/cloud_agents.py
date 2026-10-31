"""Cloud agents, published cloud-agent apps, app secret names and publish proposals."""

from collections.abc import Callable

from rich.text import Text
from textual import events
from textual.widgets import Input, Select, Static

from gbot.output import terminal_safe
from gbot.service import cloud_agents as service
from gbot.service.errors import refusal
from gbot.tui.panels.kit import (
    Detail,
    FormField,
    FormPanel,
    ListPanel,
    PanelAction,
    PanelRow,
)
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.avatar_voice import _Detail, _Form
from gbot.tui.slash.rooms import _writable

GATE_NOTE = "The app gate opens in the Grok Bot app."
_CHOICES = ("private", "team", "public")


def _message(error: BaseException) -> str:
    found = refusal(error)
    return found.message if found else str(error)


def _notify_error(ctx: SlashContext, error: BaseException) -> None:
    found = refusal(error)
    ctx.app.notify(
        terminal_safe(found.message if found else str(error)),
        severity="warning" if found else "error",
        markup=False,
    )


def _worker(
    ctx: SlashContext, work: Callable[[], object], done: Callable[[object], object]
) -> None:
    def run() -> None:
        try:
            result = work()
        except Exception as error:  # noqa: BLE001 - worker boundary
            ctx.app.call_from_thread(_notify_error, ctx, error)
        else:
            ctx.app.call_from_thread(done, result)

    ctx.app.run_worker(run, thread=True, exit_on_error=False)


def _mutate(
    ctx: SlashContext,
    title: str,
    details: str,
    work: Callable[[], object],
    done: Callable[[object], object],
    label: str = "Continue",
) -> None:
    if not _writable(ctx):
        return

    def confirmed(ok: bool | None) -> None:
        if not ok or not _writable(ctx):
            return

        def run() -> object:
            if ctx.app.read_only:
                raise ValueError("Read-only mode")
            result = work()
            if isinstance(result, service.AppResult) and not result.ok:
                raise ValueError(result.message or "The change was refused.")
            return result

        _worker(ctx, run, done)

    ctx.app.push_screen(
        ConfirmScreen(terminal_safe(title), terminal_safe(details), label), confirmed
    )


def _bot_line(ctx: SlashContext) -> str:
    bot = ctx.app.state.bots.get(ctx.bot_id or "")
    return f"Bot: {bot.name}" if bot else ""


def _footer(panel: ListPanel, keys: list[tuple[str, str]]) -> None:
    panel.query_one(".panel-footer", Static).update(
        Text(
            " · ".join(("↑↓ select", *(f"{key} {label}" for key, label in keys)))
            + " · esc back"
        )
    )


class _AppForm(FormPanel):
    def __init__(self, panel: "AppsPanel", app: service.PublishedApp) -> None:
        self.panel, self.ctx, self.target = panel, panel.ctx, app
        super().__init__(
            f"Edit app {terminal_safe(app.slug)}",
            (
                FormField("slug", "Slug", value=app.slug, required=True),
                FormField("apex", "Apex", value=app.apex, required=True),
                FormField(
                    "visibility",
                    "Visibility",
                    "choice",
                    app.visibility,
                    _CHOICES,
                    required=True,
                ),
                FormField("mute", "Mute redeploy prompts", "toggle"),
                FormField("confirm", "Require confirmation for updates", "toggle"),
            ),
            self.save,
        )

    def action_submit(self) -> None:
        if not _writable(self.ctx):
            return
        slug = self.query_one("#form-0", Input).value.strip()
        visibility = self.query_one("#form-2", Select).value
        title = f"Update app {slug or self.target.slug}" + (
            f" as {visibility}?" if isinstance(visibility, str) else "?"
        )

        def confirmed(ok: bool | None) -> None:
            if ok and _writable(self.ctx):
                super(_AppForm, self).action_submit()

        self.ctx.app.push_screen(
            ConfirmScreen(
                terminal_safe(title),
                terminal_safe(_bot_line(self.ctx)),
                "Save",
            ),
            confirmed,
        )

    def save(self, values: dict[str, str | bool]) -> str:
        if self.ctx.app.read_only:
            raise ValueError("Read-only mode")
        try:
            result = service.update_app(
                self.ctx.service.transport,
                self.target.bc_id,
                str(values["slug"]).strip(),
                str(values["apex"]).strip(),
                str(values["visibility"]),
                mute_redeploy_prompts=values["mute"] is True,
                require_confirmation_for_updates=values["confirm"] is True,
            )
        except Exception as error:  # noqa: BLE001 - refusals become notices
            raise ValueError(_message(error)) from None
        if not result.ok:
            raise ValueError(result.message or "The change was refused.")
        return result.message or f"Updated app {values['slug']}."

    def _submit_done(self, message: str) -> None:
        super()._submit_done(message)
        self.panel.reload()

    def _submit_error(self, message: str) -> None:
        super()._submit_error(terminal_safe(message))
        self.ctx.app.notify(terminal_safe(message), severity="error", markup=False)


class AppsPanel(ListPanel):
    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        self.state = service.AppsState("unknown")
        self.notice = ""
        super().__init__(
            "Published apps",
            self.load_apps,
            empty=service.NO_APPS,
            actions=(
                PanelAction("e", "Edit", self.edit),
                PanelAction("u", "Unpublish", self.unpublish),
            ),
        )

    def load_apps(self) -> list[PanelRow]:
        try:
            self.state = service.apps(self.ctx.service.transport)
        except Exception as error:
            found = refusal(error)
            if found is None:
                raise
            self.state = service.AppsState("refused")
            self.empty = found.message
            return []
        self.empty = self.state.sentence or service.NO_APPS
        return [
            PanelRow(
                str(index),
                app.slug or "(no slug)",
                " · ".join(part for part in (app.apex, app.visibility) if part),
            )
            for index, app in enumerate(self.state.apps)
        ]

    def _draw(self) -> None:
        super()._draw()
        widget = self.query_one("#panel-rows", Static)
        content = widget.content
        text = content.copy() if isinstance(content, Text) else Text(str(content))
        text.append(("\n" if self.visible_rows else "\n\n") + GATE_NOTE, style="dim")
        widget.update(text)
        keys = [("e", "edit"), ("u", "unpublish")] if self.visible_rows else []
        _footer(self, [*keys, ("g", "reload")])

    def _app(self, row: PanelRow) -> service.PublishedApp | None:
        index = int(row.key)
        return self.state.apps[index] if index < len(self.state.apps) else None

    def on_key(self, event: events.Key) -> None:
        if event.key == "g":
            self.reload()
        elif event.key in {"e", "u"} and self.visible_rows:
            row = self.visible_rows[self.index]
            (self.edit if event.key == "e" else self.unpublish)(row)
        else:
            super().on_key(event)
            return
        event.stop()
        event.prevent_default()

    def edit(self, row: PanelRow) -> None:
        app = self._app(row)
        if app is None or not _writable(self.ctx):
            return
        if app.visibility not in _CHOICES:
            # The form cannot show an unknown visibility; saving would change it silently.
            self.ctx.app.notify(
                "This app's visibility is unknown; change it in the Grok Bot app.",
                severity="warning",
                markup=False,
            )
            return
        self.ctx.app.push_screen(_AppForm(self, app))

    def unpublish(self, row: PanelRow) -> None:
        app = self._app(row)
        if app is None:
            return
        _mutate(
            self.ctx,
            f"Unpublish {app.slug}?",
            "\n".join(
                part for part in (f"{app.slug}.{app.apex}", _bot_line(self.ctx)) if part
            ),
            lambda: service.unpublish_app(
                self.ctx.service.transport, app.bc_id, app.slug, app.apex
            ),
            lambda _: self.reload(),
            "Unpublish",
        )


class _AppSecretForm(FormPanel):
    def __init__(self, panel: "AppSecretsPanel", name: str = "") -> None:
        self.panel, self.ctx = panel, panel.ctx
        super().__init__(
            "Set app secret",
            (
                FormField("name", "Name", value=name, required=True),
                FormField("value", "Value", "password", required=True),
            ),
            self.save,
        )

    def action_submit(self) -> None:
        if not _writable(self.ctx):
            return
        name = self.query_one("#form-0", Input).value.strip()
        if not name or not self.query_one("#form-1", Input).value:
            super().action_submit()
            return

        def confirmed(ok: bool | None) -> None:
            if ok and _writable(self.ctx):
                super(_AppSecretForm, self).action_submit()
            else:
                self.query_one("#form-1", Input).value = ""

        self.ctx.app.push_screen(
            ConfirmScreen(
                terminal_safe(f"Save secret {name}?"),
                terminal_safe(
                    "\n".join(
                        part
                        for part in (
                            f"Cloud agent {self.panel.bc_id} in {self.panel.project_dir}",
                            _bot_line(self.ctx),
                        )
                        if part
                    )
                ),
                "Save",
            ),
            confirmed,
        )

    def save(self, values: dict[str, str | bool]) -> str:
        try:
            if self.ctx.app.read_only:
                raise ValueError("Read-only mode")
            name = str(values["name"]).strip()
            result = service.set_app_secrets(
                self.ctx.service.transport,
                self.panel.bc_id,
                self.panel.project_dir,
                {name: str(values["value"])},
            )
        finally:
            values.clear()
        told = ""
        try:
            service.tell_secrets_set(
                self.ctx.service.transport,
                self.panel.bc_id,
                self.panel.project_dir,
                result.saved,
                result.refused,
                result.apply_needed,
            )
        except Exception as error:
            found = refusal(error)
            if found is None:
                raise
            told = found.message
        return "\n".join(
            (
                *(f"Saved secret {item}." for item in result.saved),
                *(
                    f"{item.name}: {item.message or item.kind.replace('_', ' ')}"
                    for item in result.refused
                ),
                *(
                    ("Apply the secrets in the Grok Bot app to use them.",)
                    if result.apply_needed
                    else ()
                ),
                *((told,) if told else ()),
            )
        )

    def action_back(self) -> None:
        self.query_one("#form-1", Input).value = ""
        super().action_back()

    def _submit_done(self, message: str) -> None:
        super()._submit_done(message)
        self.panel.reload()

    def _submit_error(self, message: str) -> None:
        super()._submit_error(terminal_safe(message))
        self.ctx.app.notify(terminal_safe(message), severity="error", markup=False)


class AppSecretsPanel(ListPanel):
    def __init__(self, ctx: SlashContext, bc_id: str, project_dir: str) -> None:
        self.ctx, self.bc_id, self.project_dir = ctx, bc_id, project_dir
        super().__init__(
            f"App secrets in {terminal_safe(project_dir)}",
            self.load_names,
            empty="No app secrets.",
            actions=(PanelAction("n", "Set", self.set_secret),),
        )

    def load_names(self) -> list[PanelRow]:
        try:
            names = service.app_secret_names(
                self.ctx.service.transport, self.bc_id, self.project_dir
            )
        except Exception as error:
            found = refusal(error)
            if found is None:
                raise
            self.empty = found.message
            return []
        self.empty = "No app secrets."
        return [PanelRow(name, name) for name in names]

    def _draw(self) -> None:
        super()._draw()
        _footer(self, [("n", "set"), ("g", "reload")])

    def on_key(self, event: events.Key) -> None:
        if event.key == "g":
            self.reload()
        elif event.key == "n":
            rows = self.visible_rows
            self.set_secret(rows[self.index] if rows else None)
        else:
            super().on_key(event)
            return
        event.stop()
        event.prevent_default()

    def set_secret(self, row: PanelRow | None = None) -> None:
        if _writable(self.ctx):
            self.ctx.app.push_screen(_AppSecretForm(self, row.key if row else ""))


class CloudAgentPanel(_Detail):
    def __init__(self, ctx: SlashContext, bc_id: str) -> None:
        self.ctx, self.bc_id = ctx, bc_id
        self.bot_id = ctx.bot_id or ""
        self.info: service.CloudAgentInfo | None = None
        self.messages: tuple[service.Message, ...] = ()
        self.proposals: tuple[service.Proposal, ...] = ()
        self.notes: tuple[str, ...] = ()
        self.selected = 0
        super().__init__(f"Cloud agent {terminal_safe(bc_id)}", self.content)

    def on_mount(self) -> None:
        super().on_mount()
        self.reload()

    def content(self) -> Detail:
        actions = []
        if self.info is not None:
            actions.append(PanelAction("s", "Stop", self.stop_agent))
        if self.proposals:
            actions.extend(
                (
                    PanelAction("c", "Confirm proposal", self.confirm_proposal),
                    PanelAction("d", "Dismiss proposal", self.dismiss_proposal),
                )
            )
        actions.extend(
            (
                PanelAction("k", "App secrets", self.app_secrets),
                PanelAction("g", "Reload", self.reload),
            )
        )
        lines = [*self.notes]
        if self.messages:
            lines.extend(("", "Conversation"))
            lines.extend(f"{m.role}: {m.text}" for m in self.messages[-20:])
        elif not self.notes:
            lines.append("No messages.")
        if self.proposals:
            lines.extend(("", "Publish proposals"))
            lines.extend(
                f"{'>' if i == self.selected else ' '} {p.slug} · {p.visibility}"
                + (f" · {p.summary}" if p.summary else "")
                for i, p in enumerate(self.proposals)
            )
        elif not self.notes:
            lines.append("No publish proposals.")
        return Detail(
            self.info.fields if self.info else (("Cloud agent", self.bc_id),),
            body="\n".join(lines).strip("\n"),
            actions=tuple(actions),
        )

    def loaded(self, value: object) -> None:
        if isinstance(value, tuple) and len(value) == 4:
            self.info, self.messages, self.proposals, self.notes = value
        self.selected = min(self.selected, max(0, len(self.proposals) - 1))
        self.detail = self.content()
        self.index = 0
        self._draw()
        self.query_one(".panel-footer", Static).update(
            " · ".join(f"{a.key} {a.label}" for a in self.detail.actions)
            + " · esc back"
        )

    def reload(self) -> None:
        transport, bc_id = self.ctx.service.transport, self.bc_id

        def load() -> object:
            notes: list[str] = []

            def part(work: Callable[[], object], default: object) -> object:
                try:
                    return work()
                except Exception as error:
                    found = refusal(error)
                    if found is None:
                        raise
                    notes.append(found.message)
                    return default

            found = part(
                lambda: (
                    service.info(
                        transport, bc_id, include_files=True, include_artifacts=True
                    )
                    or service.NOT_FOUND
                ),
                None,
            )
            if found == service.NOT_FOUND:
                notes.append(service.NOT_FOUND)
                found = None
            messages = part(lambda: service.conversation(transport, bc_id), ())
            rows = part(lambda: service.proposals(transport, bc_id), ())
            return found, messages, rows, tuple(dict.fromkeys(notes))

        _worker(self.ctx, load, self.loaded)

    def on_key(self, event: events.Key) -> None:
        if event.key in {"up", "down"} and self.proposals:
            step = 1 if event.key == "down" else -1
            self.selected = (self.selected + step) % len(self.proposals)
            self.detail = self.content()
            self._draw()
            event.stop()
            event.prevent_default()
        else:
            super().on_key(event)

    def _done(self, value: object) -> None:
        if isinstance(value, service.AppResult) and value.message:
            self.ctx.app.notify(terminal_safe(value.message), markup=False)
        self.reload()

    def stop_agent(self) -> None:
        _mutate(
            self.ctx,
            f"Stop cloud agent {self.bc_id}?",
            _bot_line(self.ctx),
            lambda: service.stop(self.ctx.service.transport, self.bc_id),
            self._done,
            "Stop",
        )

    def _proposal(self) -> service.Proposal | None:
        return (
            self.proposals[self.selected]
            if self.selected < len(self.proposals)
            else None
        )

    def confirm_proposal(self) -> None:
        proposal = self._proposal()
        if proposal is None:
            return
        _mutate(
            self.ctx,
            f"Publish {proposal.slug} as {proposal.visibility}?",
            "\n".join(
                part
                for part in (f"Cloud agent {self.bc_id}", _bot_line(self.ctx))
                if part
            ),
            lambda: service.confirm_proposal(
                self.ctx.service.transport,
                self.bot_id,
                self.bc_id,
                proposal.proposal_id,
                proposal.slug,
                proposal.visibility,
            ),
            self._done,
            "Publish",
        )

    def dismiss_proposal(self) -> None:
        proposal = self._proposal()
        if proposal is None:
            return
        _mutate(
            self.ctx,
            f"Dismiss the proposal to publish {proposal.slug}?",
            "\n".join(
                part
                for part in (f"Cloud agent {self.bc_id}", _bot_line(self.ctx))
                if part
            ),
            lambda: service.dismiss_proposal(
                self.ctx.service.transport,
                self.bc_id,
                proposal.proposal_id,
                self.bot_id or None,
            ),
            self._done,
            "Dismiss",
        )

    def app_secrets(self) -> None:
        def prepare(values: dict[str, str | bool]) -> None:
            project_dir = str(values["project_dir"]).strip()

            def opened() -> None:
                self.ctx.app.pop_screen()
                self.ctx.app.push_screen(
                    AppSecretsPanel(self.ctx, self.bc_id, project_dir)
                )

            self.ctx.app.call_from_thread(opened)

        self.ctx.app.push_screen(
            _Form(
                self.ctx,
                "App secrets",
                (
                    FormField(
                        "project_dir",
                        "Project directory",
                        required=True,
                        hint="The app's directory on the cloud agent",
                    ),
                ),
                prepare,
            )
        )


def apps(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(AppsPanel(ctx))


def cloud_agent(ctx: SlashContext, args: str) -> None:
    bc_id = args.strip()
    if not bc_id or len(bc_id.split()) != 1:
        raise ValueError("Usage: /cloud-agent BC_ID")
    ctx.app.push_screen(CloudAgentPanel(ctx, bc_id))


COMMANDS = (
    SlashCommand("apps", "Published cloud-agent apps", apps),
    SlashCommand(
        "cloud-agent",
        "Read, stop and publish a cloud agent",
        cloud_agent,
        scope="session",
        args="BC_ID",
        needs_bot=True,
    ),
)
