"""Stage local files and browse files in the loaded conversation."""

import webbrowser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from textual import events

from gbot.output import terminal_safe
from gbot.service import attachments
from gbot.service.attachments import FileRef
from gbot.service.models import Entry
from gbot.tui.panels import (
    Detail,
    DetailPanel,
    FormField,
    FormPanel,
    ListPanel,
    PanelAction,
    PanelRow,
)
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.widgets.transcript import Transcript, file_size


def file_path(value: str) -> Path:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if value.startswith("file://"):
        value = unquote(value[7:])
        if len(value) > 2 and value[0] == "/" and value[2] == ":":
            value = value[1:]
    return Path(value).expanduser()


def attach(ctx: SlashContext, args: str) -> None:
    if not isinstance(ctx.screen, SessionScreen):
        return
    if ctx.app.read_only:
        ctx.app.notify("Read-only mode", markup=False)
        return
    screen = ctx.screen

    def stage(value: str) -> None:
        path = file_path(value)
        if not path.is_file():
            ctx.app.notify(f"No such file: {terminal_safe(str(path))}", markup=False)
            return
        screen.stage_file(path)

    if args:
        stage(args)
    else:

        def submit(values: dict[str, str | bool]) -> None:
            ctx.app.call_from_thread(stage, str(values["path"]))

        ctx.app.push_screen(
            FormPanel(
                "Attach file", (FormField("path", "Path", required=True),), submit
            )
        )


def detach(ctx: SlashContext, args: str) -> None:
    if not isinstance(ctx.screen, SessionScreen):
        return
    screen = ctx.screen
    name = args.strip().strip("\"'")
    removed = [item for item in screen.attachments if not name or item.name == name]
    screen.attachments[:] = [item for item in screen.attachments if item not in removed]
    screen.refresh_attachments()
    ctx.app.notify(
        "Removed " + " · ".join(terminal_safe(item.name) for item in removed)
        if removed
        else "Nothing attached",
        markup=False,
    )


class _FileDetail(DetailPanel):
    def on_key(self, event: events.Key) -> None:
        action = next((a for a in self.detail.actions if a.key == event.key), None)
        if action:
            self.invoke(action)
            event.stop()
            event.prevent_default()
        else:
            super().on_key(event)


def show_files(ctx: SlashContext, args: str) -> None:
    if not isinstance(ctx.screen, SessionScreen) or ctx.bot_id is None:
        return
    app, screen, bot_id = ctx.app, ctx.screen, ctx.bot_id
    files: dict[str, FileRef] = {}
    rows = []
    entries = [
        entry
        for widget in screen.query_one(Transcript).entries.values()
        if isinstance(entry := getattr(widget, "entry", None), Entry)
    ]
    for entry in sorted(entries, key=lambda entry: entry.seq, reverse=True):
        for file in attachments.entry_files(entry):
            key = str(len(rows))
            files[key] = file
            owner = (
                "you"
                if entry.is_user or entry.kind == "user-attachment"
                else screen.bot_name
            )
            rows.append(
                PanelRow(
                    key,
                    file.name,
                    f"{owner} · {file_size(file.size)}",
                    "link" if file.remote_url else "",
                )
            )

    def notice(message: str) -> None:
        app.notify(terminal_safe(message), markup=False)

    def save(file: FileRef) -> None:
        if app.read_only:
            notice("Read-only mode")
            return
        if file.path is None:
            notice("This file is a remote link")
            return
        folder = Path.home() / "Downloads"

        def confirmed(ok: bool | None) -> None:
            if not ok:
                return
            if app.read_only:
                notice("Read-only mode")
                return

            def worker() -> None:
                try:
                    path = attachments.download(
                        ctx.service.transport,
                        bot_id,
                        file.path or "",
                        folder,
                        name=file.name,
                    )
                    app.call_from_thread(notice, f"Saved to {path}")
                except Exception as error:  # noqa: BLE001 - download worker boundary
                    app.call_from_thread(app.bot_error, bot_id, error)

            app.run_worker(worker, thread=True, exit_on_error=False)

        app.push_screen(
            ConfirmScreen(
                f"Save {terminal_safe(file.name)} to {terminal_safe(str(folder))}?",
                "",
                "Save",
            ),
            confirmed,
        )

    def open_link(file: FileRef) -> None:
        url = file.remote_url or ""
        try:
            https = url.startswith("https://") and bool(urlsplit(url).netloc)
        except ValueError:
            https = False
        if not https:
            notice("Only https links open")
            return

        def confirmed(ok: bool | None) -> None:
            if ok:
                try:
                    webbrowser.open(url)
                except Exception as error:  # noqa: BLE001 - browser boundary
                    app.bot_error(bot_id, error)

        app.push_screen(
            ConfirmScreen(
                "Open this link in your browser?", terminal_safe(url), "Open"
            ),
            confirmed,
        )

    def preview(row: PanelRow) -> None:
        file = files[row.key]
        if file.path is None:
            open_link(file)
            return

        def worker() -> None:
            try:
                result = attachments.read_text(
                    ctx.service.transport, bot_id, file.path or ""
                )
                body = (
                    result.text + ("\n(truncated)" if result.truncated else "")
                    if result and result.kind == "text"
                    else f"Binary file · {file_size(result.bytes if result else file.size)} · s to save"
                )
                detail = Detail(
                    (), body, (PanelAction("s", "Save", lambda: save(file)),)
                )
                app.call_from_thread(
                    app.push_screen, _FileDetail(file.name, lambda: detail)
                )
            except Exception as error:  # noqa: BLE001 - preview worker boundary
                app.call_from_thread(app.bot_error, bot_id, error)

        app.run_worker(worker, thread=True, exit_on_error=False)

    app.push_screen(
        ListPanel(
            "Files",
            lambda: rows,
            on_select=preview,
            empty="No files in the loaded messages · pgup loads earlier ones",
            actions=(
                PanelAction("s", "Save", lambda row: save(files[row.key])),
                PanelAction("o", "Open link", lambda row: open_link(files[row.key])),
            ),
        )
    )


COMMANDS = (
    SlashCommand(
        "attach",
        "Attach a file",
        attach,
        scope="session",
        args="[path]",
        needs_bot=True,
    ),
    SlashCommand(
        "detach",
        "Remove staged files",
        detach,
        scope="session",
        args="[name]",
        needs_bot=True,
    ),
    SlashCommand(
        "files", "Show conversation files", show_files, scope="session", needs_bot=True
    ),
)
