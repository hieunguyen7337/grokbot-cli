"""Confirmed voice preferences and text-only avatar management."""

from collections.abc import Callable, Sequence
from pathlib import Path

from textual import events
from textual.widgets import Static

from gbot.output import terminal_safe
from gbot.service import avatar_voice as service
from gbot.service import bots
from gbot.service.models import Bot
from gbot.tui.panels.kit import Detail, DetailPanel, FormField, FormPanel, PanelAction
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.attachments import file_path
from gbot.tui.slash.rooms import _refresh, _writable
from gbot.tui.widgets.transcript import file_size


def _worker(ctx: SlashContext, work: Callable[[], None]) -> None:
    def run() -> None:
        try:
            work()
        except Exception as error:  # noqa: BLE001 - worker boundary
            ctx.app.call_from_thread(ctx.app.service_error, error)

    ctx.app.run_worker(run, thread=True, exit_on_error=False)


def _confirm(
    ctx: SlashContext,
    title: str,
    work: Callable[[], object],
    done: Callable[[], object],
    details: str = "",
) -> None:
    if not _writable(ctx):
        return

    def confirmed(ok: bool | None) -> None:
        if not ok or not _writable(ctx):
            return

        def run() -> None:
            if ctx.app.read_only:
                raise ValueError("Read-only mode")
            work()

            def finished() -> None:
                done()

            ctx.app.call_from_thread(_refresh, ctx, finished)

        _worker(ctx, run)

    ctx.app.push_screen(ConfirmScreen(title, details, "Save"), confirmed)


class _Form(FormPanel):
    """Validate in the form worker, then let the caller review the result."""

    def __init__(
        self,
        ctx: SlashContext,
        title: str,
        fields: Sequence[FormField],
        prepare: Callable[[dict[str, str | bool]], None],
    ) -> None:
        self.ctx = ctx

        def submit(values: dict[str, str | bool]) -> None:
            if ctx.app.read_only:
                raise ValueError("Read-only mode")
            prepare(values)

        super().__init__(title, fields, submit)

    def action_submit(self) -> None:
        if _writable(self.ctx):
            super().action_submit()

    def _submit_done(self, message: str) -> None:
        pass

    def _submit_error(self, message: str) -> None:
        super()._submit_error(message)
        self.ctx.app.notify(terminal_safe(message), severity="error", markup=False)


class _Detail(DetailPanel):
    def on_mount(self) -> None:
        super().on_mount()
        self.query_one(".panel-footer", Static).update(
            " · ".join(f"{action.key} {action.label}" for action in self.detail.actions)
            + " · esc back"
        )

    def on_key(self, event: events.Key) -> None:
        action = next((a for a in self.detail.actions if a.key == event.key), None)
        if action:
            self.invoke(action)
            event.stop()
            event.prevent_default()
        else:
            super().on_key(event)


def voice(ctx: SlashContext, args: str) -> None:
    bot = ctx.app.state.bots[ctx.bot_id or ""]

    def load() -> None:
        row = (
            bots.server_bots(ctx.service.transport).get(bot.id)
            if bot.raw.get("harness") == "temporal"
            else None
        )
        voice_id = row.voice_id if row else bot.raw.get("voiceId")
        speed = service.normalize_speed(
            row.voice_speed if row else bot.raw.get("voiceSpeed")
        )
        language = service.normalize_language(
            row.voice_language if row else bot.raw.get("voiceLanguage")
        )
        voice_id = str(voice_id) if voice_id else None
        labels: dict[str, str | None] = {label: key for key, label in service.VOICES}
        current = dict(service.VOICES).get(str(voice_id), str(voice_id or "Default"))
        labels[current] = voice_id
        initial = {
            "voice_id": current,
            "speed": f"{speed:g}x",
            "language": "Automatic" if language == "auto" else language,
        }

        def prepare(values: dict[str, str | bool]) -> None:
            changes = {
                key: value for key, value in values.items() if value != initial[key]
            }
            if not changes:
                ctx.app.call_from_thread(
                    ctx.app.notify, "Nothing to change", markup=False
                )
                return
            payload = {}
            if "voice_id" in changes:
                payload["voice_id"] = labels[str(changes["voice_id"])]
            if "speed" in changes:
                payload["speed"] = str(changes["speed"]).removesuffix("x")
            if "language" in changes:
                payload["language"] = (
                    "auto"
                    if changes["language"] == "Automatic"
                    else str(changes["language"])
                )

            def review() -> None:
                _confirm(
                    ctx,
                    f"Change {terminal_safe(bot.name)}'s voice?",
                    lambda: service.set_voice(ctx.service.transport, bot, **payload),
                    lambda: ctx.app.pop_screen(),
                    "\n".join(f"{key}: {value}" for key, value in changes.items()),
                )

            ctx.app.call_from_thread(review)

        form = _Form(
            ctx,
            f"{terminal_safe(bot.name)} voice",
            (
                FormField(
                    "voice_id",
                    "Voice",
                    "choice",
                    current,
                    tuple(labels),
                    hint="Voice previews play in the Grok Bot app",
                ),
                FormField(
                    "speed",
                    "Speed",
                    "choice",
                    initial["speed"],
                    tuple(f"{s:g}x" for s in service.SPEEDS),
                ),
                FormField(
                    "language",
                    "Language",
                    "choice",
                    initial["language"],
                    tuple(
                        "Automatic" if item == "auto" else item
                        for item in service.LANGUAGES
                    ),
                ),
            ),
            prepare,
        )
        ctx.app.call_from_thread(ctx.app.push_screen, form)

    _worker(ctx, load)


def avatar(ctx: SlashContext, args: str) -> None:
    bot = ctx.app.state.bots[ctx.bot_id or ""]
    ctx.app.push_screen(_AvatarPanel(ctx, bot))


class _AvatarPanel(_Detail):
    def __init__(self, ctx: SlashContext, bot: Bot) -> None:
        self.ctx, self.bot = ctx, bot
        self.image: service.Avatar | None = None
        self.generated: service.GeneratedImage | None = None
        super().__init__(f"{terminal_safe(bot.name)} avatar", self.content)

    def content(self) -> Detail:
        bot = self.ctx.app.state.bots.get(self.bot.id, self.bot)
        image = "none"
        if self.image:
            dimensions = "unknown dimensions"
            if self.image.mime_type == "image/png":
                try:
                    width, height = service.check_png(self.image.data)
                    dimensions = f"{width}x{height}"
                except ValueError:
                    # The server may hold an image larger than gbot uploads.
                    pass
            image = f"{self.image.mime_type} · {dimensions} · {file_size(len(self.image.data))}"
        return Detail(
            (
                ("Shape", str(bot.raw.get("avatarShape") or "blob")),
                ("Color", bot.avatar_color or "blue"),
            ),
            body=f"Image: {image}",
            actions=(
                PanelAction("f", "From file", self.from_file),
                PanelAction("g", "Generate", self.generate),
                PanelAction("s", "Save image", self.save),
                PanelAction("c", "Clear image", self.clear),
                PanelAction("k", "Shape and color", self.shape),
            ),
        )

    def on_mount(self) -> None:
        super().on_mount()
        self.reload()

    def reload(self) -> None:
        def load() -> None:
            image = service.avatar(self.ctx.service.transport, self.bot.id)
            self.ctx.app.call_from_thread(self.loaded, image)

        _worker(self.ctx, load)

    def loaded(self, image: service.Avatar | None) -> None:
        self.image = image
        self.detail = self.content()
        self._draw()

    def upload(self, data: bytes, title: str) -> None:
        def done() -> None:
            if self.ctx.app.screen is not self:
                self.ctx.app.pop_screen()
            self.loaded(service.Avatar(data, "image/png"))

        _confirm(
            self.ctx,
            title,
            lambda: service.set_avatar(self.ctx.service.transport, self.bot, data),
            done,
        )

    def from_file(self) -> None:
        if not _writable(self.ctx):
            return

        def prepare(values: dict[str, str | bool]) -> None:
            path = file_path(str(values["path"]))
            data = path.read_bytes()
            service.check_png(data)
            self.ctx.app.call_from_thread(
                self.upload,
                data,
                f"Use {terminal_safe(path.name)} as {terminal_safe(self.bot.name)}'s avatar?",
            )

        self.ctx.app.push_screen(
            _Form(
                self.ctx,
                "Avatar from file",
                (FormField("path", "Path", required=True),),
                prepare,
            )
        )

    def generate(self) -> None:
        if not _writable(self.ctx):
            return

        def prepare(values: dict[str, str | bool]) -> None:
            self.ctx.app.call_from_thread(
                self.ctx.app.notify, "Generating…", markup=False
            )
            image = service.generate_avatar(
                self.ctx.service.transport, str(values["description"])
            )
            self.generated = image
            try:
                width, height = service.check_png(image.data)
            except ValueError:
                self.ctx.app.call_from_thread(self.generated_warning)
                return
            self.ctx.app.call_from_thread(
                self.upload,
                image.data,
                f"Use the generated image ({terminal_safe(image.mime_type)} · {width}x{height}) as {terminal_safe(self.bot.name)}'s avatar?",
            )

        self.ctx.app.push_screen(
            _Form(
                self.ctx,
                "Generate avatar",
                (FormField("description", "Describe the image", required=True),),
                prepare,
            )
        )

    def generated_warning(self) -> None:
        self.ctx.app.pop_screen()
        self.ctx.app.notify(
            "The generated image is not a PNG gbot can upload",
            severity="warning",
            markup=False,
        )

    def save(self) -> None:
        if not _writable(self.ctx):
            return
        image = self.generated or self.image
        if image is None:
            self.ctx.app.notify("No image to save", markup=False)
            return
        extension = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
        }.get(image.mime_type, ".bin")
        folder = Path.home() / "Downloads"
        path, number = folder / f"avatar{extension}", 1
        while path.exists():
            path, number = folder / f"avatar ({number}){extension}", number + 1
        name = path.name

        def write() -> None:
            folder.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(image.data)

        _confirm(
            self.ctx,
            f"Save {name} to {terminal_safe(str(folder))}?",
            write,
            lambda: self.ctx.app.notify(
                f"Saved to {terminal_safe(str(path))}", markup=False
            ),
        )

    def clear(self) -> None:
        _confirm(
            self.ctx,
            f"Remove {terminal_safe(self.bot.name)}'s avatar image?",
            lambda: service.set_avatar(self.ctx.service.transport, self.bot, None),
            lambda: self.loaded(None),
        )

    def shape(self) -> None:
        if not _writable(self.ctx):
            return
        bot = self.ctx.app.state.bots.get(self.bot.id, self.bot)
        initial = {
            "shape": str(bot.raw.get("avatarShape") or "blob"),
            "color": bot.avatar_color or "blue",
        }

        def prepare(values: dict[str, str | bool]) -> None:
            changes = {
                key: str(value)
                for key, value in values.items()
                if value != initial[key]
            }
            if not changes:
                self.ctx.app.call_from_thread(
                    self.ctx.app.notify, "Nothing to change", markup=False
                )
                return

            def review() -> None:
                def done() -> None:
                    self.ctx.app.pop_screen()
                    self.detail = self.content()
                    self._draw()

                _confirm(
                    self.ctx,
                    f"Change {terminal_safe(bot.name)}'s avatar?",
                    lambda: bots.update(self.ctx.service.transport, bot, **changes),
                    done,
                    "\n".join(f"{key}: {value}" for key, value in changes.items()),
                )

            self.ctx.app.call_from_thread(review)

        self.ctx.app.push_screen(
            _Form(
                self.ctx,
                "Shape and color",
                (
                    FormField(
                        "shape", "Shape", "choice", initial["shape"], bots.SHAPES
                    ),
                    FormField(
                        "color", "Color", "choice", initial["color"], bots.COLORS
                    ),
                ),
                prepare,
            )
        )


COMMANDS = (
    SlashCommand(
        "voice", "Change voice preferences", voice, scope="session", needs_bot=True
    ),
    SlashCommand("avatar", "Manage avatar", avatar, scope="session", needs_bot=True),
)
