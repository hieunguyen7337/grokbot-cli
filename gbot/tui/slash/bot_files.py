"""A bot's files, user-store files and library documents."""

import webbrowser
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from textual import events
from textual.widgets import Static

from gbot.output import terminal_safe
from gbot.service import bot_files as files_service
from gbot.service import library as library_service
from gbot.service.errors import refusal
from gbot.tui.panels.kit import FormField, ListPanel, PanelRow
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.avatar_voice import _Form
from gbot.tui.slash.rooms import _writable


def _size(count: int) -> str:
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{count} B"


def _when(ms: int) -> str:
    if ms <= 0:
        return "unknown"
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d %H:%M")


def _worker(
    ctx: SlashContext, work: Callable[[], object], done: Callable[[object], object]
) -> None:
    def run() -> None:
        try:
            result = work()
        except Exception as error:  # noqa: BLE001 - worker boundary
            refused = refusal(error)
            ctx.app.call_from_thread(
                ctx.app.notify,
                terminal_safe(refused.message if refused else str(error)),
                severity="warning" if refused else "error",
                markup=False,
            )
        else:
            ctx.app.call_from_thread(done, result)

    ctx.app.run_worker(run, thread=True, exit_on_error=False)


def _mutate(
    ctx: SlashContext,
    title: str,
    confirm_label: str,
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

    ctx.app.push_screen(
        ConfirmScreen(terminal_safe(title), "", confirm_label), confirmed
    )


class _KeyedPanel(ListPanel):
    """A list panel whose keys depend on what was loaded."""

    def hints(self) -> tuple[tuple[str, str], ...]:
        return ()

    def _footer(self) -> None:
        self.query_one(".panel-footer", Static).update(
            " · ".join(
                [
                    "↑↓ select",
                    *(f"{key} {label}" for key, label in self.hints()),
                    "esc back",
                ]
            )
        )

    def _loaded(self, rows: list[PanelRow], error: str) -> None:
        super()._loaded(rows, error)
        self._footer()

    def key_action(self, key: str) -> bool:
        return False

    def on_key(self, event: events.Key) -> None:
        if self.key_action(event.key):
            event.stop()
            event.prevent_default()
            return
        super().on_key(event)
        self._footer()


class BotFilesPanel(_KeyedPanel):
    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        self.bot = ctx.app.state.bots[ctx.bot_id or ""]
        self.listing = files_service.AgentFiles((), 0, False)
        super().__init__(
            f"{terminal_safe(self.bot.name)} files",
            self.collect,
            empty="This bot has no files.",
        )

    def collect(self) -> list[PanelRow]:
        transport = self.ctx.service.transport
        rows: list[PanelRow] = []
        notices: list[str] = []
        try:
            listing = files_service.agent_files(transport, self.bot.id)
        except Exception as error:
            refused = refusal(error)
            if refused is None:
                raise
            listing = files_service.AgentFiles((), 0, False)
            notices.append(refused.message)
        try:
            store = files_service.user_store_files(transport, self.bot.id)
        except Exception as error:
            refused = refusal(error)
            if refused is None:
                raise
            store = ()
            notices.append(refused.message)
        self.listing = listing
        rows.extend(
            PanelRow(
                "file:" + f.name,
                f.name,
                f"{_size(f.size_bytes)} · updated {_when(f.updated_at_ms)}",
            )
            for f in listing.files
        )
        rows.extend(
            PanelRow(
                "store:" + f.path,
                f.name or f.path,
                f"{_size(f.size_bytes)} · updated {_when(f.updated_at_ms)}",
                "user store",
                "muted",
            )
            for f in store
        )
        rows.extend(PanelRow("notice:" + n, n, tone="muted") for n in notices)
        if listing.files or store:
            rows.append(
                PanelRow(
                    "total:",
                    f"Total {_size(listing.total_bytes)}"
                    + ("" if listing.can_edit else " · read only"),
                    tone="muted",
                )
            )
        return rows

    def selected(self) -> PanelRow | None:
        rows = self.visible_rows
        return rows[self.index] if rows else None

    def can_delete(self, row: PanelRow | None) -> bool:
        if row is None:
            return False
        if row.key.startswith("store:"):
            return True
        return row.key.startswith("file:") and self.listing.can_edit

    def hints(self) -> tuple[tuple[str, str], ...]:
        row = self.selected()
        return (
            *((("u", "upload"),) if self.listing.can_edit else ()),
            *((("x", "delete"),) if self.can_delete(row) else ()),
            ("g", "reload"),
        )

    def key_action(self, key: str) -> bool:
        if key == "g":
            self.reload()
        elif key == "u" and self.listing.can_edit:
            self.upload()
        elif key == "x" and self.can_delete(self.selected()):
            self.delete(self.selected())
        else:
            return False
        return True

    def upload(self) -> None:
        if not _writable(self.ctx):
            return

        def prepare(values: dict[str, str | bool]) -> None:
            path = Path(str(values["path"]).strip()).expanduser()
            if not path.is_file():
                raise ValueError("Not a file")
            size = path.stat().st_size

            def review() -> None:
                self.ctx.app.pop_screen()
                _mutate(
                    self.ctx,
                    f"Upload {path.name} ({_size(size)}) to {self.bot.name}?",
                    "Upload",
                    lambda: files_service.upload_file(
                        self.ctx.service.transport, self.bot.id, path
                    ),
                    lambda _: self.reload(),
                )

            self.ctx.app.call_from_thread(review)

        self.ctx.app.push_screen(
            _Form(
                self.ctx,
                "Upload a file",
                (FormField("path", "File path", required=True),),
                prepare,
            )
        )

    def delete(self, row: PanelRow | None) -> None:
        if row is None or not row.key.startswith(("file:", "store:")):
            return
        user_store = row.key.startswith("store:")
        target = row.key.split(":", 1)[1]
        transport = self.ctx.service.transport
        _mutate(
            self.ctx,
            f"Delete {target} from {self.bot.name}?",
            "Delete",
            (
                (
                    lambda: files_service.delete_user_store_file(
                        transport, self.bot.id, target
                    )
                )
                if user_store
                else (
                    lambda: files_service.delete_agent_file(
                        transport, self.bot.id, target
                    )
                )
            ),
            lambda _: self.reload(),
        )


class LibraryPanel(_KeyedPanel):
    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        self.bot = ctx.app.state.bots[ctx.bot_id or ""]
        self.docs: dict[str, library_service.LibraryDoc] = {}
        self.pins: dict[str, library_service.Pin] = {}
        super().__init__(
            f"{terminal_safe(self.bot.name)} library",
            self.collect,
            empty="This bot has no library documents.",
        )

    def collect(self) -> list[PanelRow]:
        transport = self.ctx.service.transport
        notices: list[str] = []
        try:
            docs = library_service.library_docs(transport, self.bot.id)
        except Exception as error:
            refused = refusal(error)
            if refused is None:
                raise
            docs = ()
            notices.append(refused.message)
        try:
            pins = library_service.library_pins(transport, self.bot.id)
        except Exception as error:
            refused = refusal(error)
            if refused is None:
                raise
            pins = ()
            notices.append(refused.message)
        doc_pins = {p.key: p for p in pins if p.kind == "doc"}
        self.docs = {d.key: d for d in docs}
        self.pins = doc_pins
        rows = [
            PanelRow(
                "doc:" + d.key,
                d.title or d.external_id or d.key,
                f"{d.provider} · {d.kind} · touched {_when(d.last_touched_at_ms)}",
                "pinned" if d.key in doc_pins else "",
                "ok",
            )
            for d in docs
        ]
        others = [p for p in pins if p.kind != "doc" or p.key not in self.docs]
        rows.extend(
            PanelRow(
                f"pin:{i}",
                p.key or p.name or p.canvas_id or p.document_id or p.kind,
                p.kind,
                "pinned",
                "muted",
            )
            for i, p in enumerate(others)
        )
        rows.extend(PanelRow("notice:" + n, n, tone="muted") for n in notices)
        return rows

    def selected_doc(self) -> library_service.LibraryDoc | None:
        rows = self.visible_rows
        row = rows[self.index] if rows else None
        if row is None or not row.key.startswith("doc:"):
            return None
        return self.docs.get(row.key[4:])

    def hints(self) -> tuple[tuple[str, str], ...]:
        doc = self.selected_doc()
        return (
            *((("p", "unpin" if doc.key in self.pins else "pin"),) if doc else ()),
            *((("o", "open"),) if doc and doc.url else ()),
            ("g", "reload"),
        )

    def key_action(self, key: str) -> bool:
        doc = self.selected_doc()
        if key == "g":
            self.reload()
        elif key == "p" and doc is not None:
            self.toggle_pin(doc)
        elif key == "o" and doc is not None and doc.url:
            self.open_url(doc.url)
        else:
            return False
        return True

    def toggle_pin(self, doc: library_service.LibraryDoc) -> None:
        existing = self.pins.get(doc.key)
        pin = existing or library_service.Pin(
            "doc", key=doc.key, pinned_at_ms=int(datetime.now(UTC).timestamp() * 1000)
        )
        pinned = existing is None
        name = doc.title or doc.external_id or doc.key
        _mutate(
            self.ctx,
            f"{'Pin' if pinned else 'Unpin'} {name} for {self.bot.name}?",
            "Pin" if pinned else "Unpin",
            lambda: library_service.set_pin(
                self.ctx.service.transport, self.bot.id, pin, pinned
            ),
            lambda _: self.reload(),
        )

    def open_url(self, url: str) -> None:
        try:
            https = url.startswith("https://") and bool(urlsplit(url).netloc)
        except ValueError:
            https = False
        if not https:
            self.ctx.app.notify("Only https links open", markup=False)
            return

        def opened() -> object:
            try:
                launched = webbrowser.open(url)
            except Exception:  # noqa: BLE001 - browser errors may embed the link
                launched = False
            if not launched:
                raise ValueError("Could not open a browser for the document.")
            return None

        _worker(
            self.ctx,
            opened,
            lambda _: self.ctx.app.notify("Opened the document.", markup=False),
        )


def bot_files(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(BotFilesPanel(ctx))


def library(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(LibraryPanel(ctx))


COMMANDS = (
    SlashCommand(
        "bot-files",
        "Manage the bot's files",
        bot_files,
        scope="session",
        needs_bot=True,
    ),
    SlashCommand(
        "library",
        "Browse the bot's library and pins",
        library,
        scope="session",
        needs_bot=True,
    ),
)
