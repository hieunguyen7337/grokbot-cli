"""Thread and activity panels for the selected bot."""

from collections.abc import Callable, Sequence
from time import time

from gbot.output import terminal_safe
from gbot.service import tasks as service
from gbot.tui.model import age_text
from gbot.tui.panels import ListPanel, PanelAction, PanelRow
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashCommand, SlashContext


def _mutate(
    ctx: SlashContext,
    call: Callable[[], object],
    after: Callable[[], object] | None = None,
) -> None:
    if ctx.app.read_only:
        ctx.app.notify("Read-only mode", markup=False)
        return

    def worker() -> None:
        try:
            call()
            ctx.app.call_from_thread(ctx.app.bot_error, ctx.bot_id)
            ctx.app.call_from_thread(ctx.app.user_acted)
            if after:
                ctx.app.call_from_thread(after)
        except Exception as error:  # noqa: BLE001 - worker boundary
            ctx.app.call_from_thread(ctx.app.bot_error, ctx.bot_id, error)

    ctx.app.run_worker(worker, thread=True, exit_on_error=False)


def _panel(
    ctx: SlashContext, title: str, load: Callable[[], Sequence[PanelRow]], **kwargs
) -> ListPanel:
    def guarded() -> Sequence[PanelRow]:
        try:
            rows = load()
            ctx.app.call_from_thread(ctx.app.bot_error, ctx.bot_id)
            return rows
        except Exception as error:
            ctx.app.call_from_thread(ctx.app.bot_error, ctx.bot_id, error)
            raise

    panel = ListPanel(title, guarded, **kwargs)
    ctx.app.push_screen(panel)
    return panel


def threads(ctx: SlashContext, args: str) -> None:
    assert ctx.bot_id is not None
    bot_id = ctx.bot_id
    found: dict[str, service.AgentTask] = {}

    def load() -> list[PanelRow]:
        items = service.tasks(ctx.service.transport, bot_id)
        found.clear()
        found.update((t.id, t) for t in items)
        items.sort(
            key=lambda t: (
                0 if t.pinned_at_ms is not None else 2 if t.status == "done" else 1,
                -(t.updated_at_ms or 0),
            )
        )
        return [
            PanelRow(
                t.id,
                terminal_safe(t.name or t.id),
                terminal_safe(t.unread_preview or t.description or ""),
                " ".join(
                    s
                    for s, yes in (
                        ("pinned", t.pinned_at_ms is not None),
                        ("unread", bool(t.unread_entry_id)),
                        ("done", t.status == "done"),
                    )
                    if yes
                ),
                "warn"
                if t.unread_entry_id
                else "ok"
                if t.pinned_at_ms is not None
                else "muted"
                if t.status == "done"
                else "",
            )
            for t in items
        ]

    def select(row: PanelRow) -> None:
        task = found[row.key]
        ctx.app.push_screen(
            SessionScreen(
                bot_id,
                bot_name=terminal_safe(ctx.app.state.bots[bot_id].name),
                session_id=service.thread_session(task.id, ctx.session_id),
            )
        )
        if task.unread_entry_id and not ctx.app.read_only:
            _mutate(
                ctx,
                lambda: service.mark_read(
                    ctx.service.transport, bot_id, task.id, task.unread_entry_id or ""
                ),
            )

    def pin(row: PanelRow) -> None:
        task = found[row.key]
        _mutate(
            ctx,
            lambda: service.set_pinned(
                ctx.service.transport, bot_id, task.id, task.pinned_at_ms is None
            ),
            panel.reload,
        )

    def done(row: PanelRow) -> None:
        if ctx.app.read_only:
            ctx.app.notify("Read-only mode", markup=False)
            return
        task = found[row.key]

        def finished() -> None:
            if isinstance(ctx.screen, SessionScreen) and (
                ctx.screen.session_id == service.thread_session(task.id, None)
                or (ctx.screen.session_id or "").startswith(
                    service.thread_session(task.id, None) + ":"
                )
            ):
                ctx.app.pop_screen()
                ctx.app.pop_screen()
            else:
                panel.reload()

        panel.invoke(
            PanelAction(
                "d",
                "Mark done",
                lambda: _mutate(
                    ctx,
                    lambda: service.mark_done(ctx.service.transport, bot_id, task.id),
                    finished,
                ),
                confirm=f'Mark "{terminal_safe(task.name or task.id)}" done? The thread closes.',
            )
        )

    panel = _panel(
        ctx,
        "Threads",
        load,
        on_select=select,
        actions=(
            PanelAction("p", "Pin/unpin", pin),
            PanelAction("d", "Mark done", done),
        ),
    )


def background(ctx: SlashContext, args: str) -> None:
    assert ctx.bot_id is not None

    def load() -> list[PanelRow]:
        return [
            PanelRow(
                t.id,
                terminal_safe(t.label or t.id),
                terminal_safe(
                    f"{t.kind or ''} · running for {age_text(int(time() * 1000) - (t.started_at_ms or 0))} · {t.detail or ''}"
                ),
            )
            for t in service.background(ctx.service.transport, ctx.bot_id or "")
        ]

    _panel(ctx, "Background", load)


def subagents(ctx: SlashContext, args: str) -> None:
    def load() -> list[PanelRow]:
        return [
            PanelRow(
                t.id,
                terminal_safe(t.title or t.id),
                terminal_safe(t.type or ""),
                terminal_safe(t.status or ""),
                "warn"
                if t.status == "running"
                else "ok"
                if t.status == "done"
                else "error"
                if t.status in ("error", "aborted")
                else "",
            )
            for t in service.subagents(ctx.service.transport, ctx.bot_id or "")
        ]

    _panel(ctx, "Subagents", load)


def outline(ctx: SlashContext, args: str) -> None:
    def load() -> list[PanelRow]:
        rows = []
        for t in service.outline(ctx.service.transport, ctx.bot_id or ""):
            label = (
                f"{t.name or ''}: {t.summary or ''}"
                if t.kind == "tool-call"
                else t.text or ""
            )
            detail = (
                f"thinking · {age_text(t.duration_ms)}"
                if t.kind == "thinking" and t.duration_ms is not None
                else t.kind or ""
            )
            rows.append(
                PanelRow(
                    t.id,
                    terminal_safe(label),
                    terminal_safe(detail),
                    terminal_safe(t.status or ""),
                )
            )
        return rows

    _panel(ctx, "Outline", load, filterable=True)


def suggestions(ctx: SlashContext, args: str) -> None:
    assert ctx.bot_id is not None
    bot = ctx.app.state.bots[ctx.bot_id]
    found = {s.id: s for s in service.suggestions(bot)}

    def dismiss(row: PanelRow, acted: bool) -> None:
        if ctx.app.read_only:
            ctx.app.notify("Read-only mode", markup=False)
            return
        item = found[row.key]
        if acted:
            ctx.app.pop_screen()
            if isinstance(ctx.screen, SessionScreen):
                ctx.screen.restore_draft(terminal_safe(item.prompt or ""))
            else:
                screen = SessionScreen(bot.id, bot_name=terminal_safe(bot.name))
                ctx.app.push_screen(screen, callback=None)
                ctx.app.call_after_refresh(
                    screen.restore_draft, terminal_safe(item.prompt or "")
                )

        def removed() -> None:
            found.pop(row.key, None)
            if panel.is_mounted:
                panel.reload()

        _mutate(
            ctx,
            lambda: service.dismiss_suggestions(
                ctx.service.transport, bot.id, [item.id], "acted" if acted else "hidden"
            ),
            removed,
        )

    panel = _panel(
        ctx,
        "Suggestions",
        lambda: [
            PanelRow(
                s.id, terminal_safe(s.title or s.id), terminal_safe(s.detail or "")
            )
            for s in found.values()
        ],
        on_select=lambda row: dismiss(row, True),
        actions=(PanelAction("h", "Hide", lambda row: dismiss(row, False)),),
        empty="No suggestions",
    )


def _unread(ctx: SlashContext, unread: bool) -> None:
    assert ctx.bot_id is not None
    bot = ctx.app.state.bots[ctx.bot_id]
    _mutate(
        ctx,
        lambda: service.set_unread(ctx.service.transport, bot.id, unread),
        lambda: ctx.app.notify(
            f"Marked {terminal_safe(bot.name)} {'unread' if unread else 'read'}",
            markup=False,
        ),
    )


def read(ctx: SlashContext, args: str) -> None:
    _unread(ctx, False)


def unread(ctx: SlashContext, args: str) -> None:
    _unread(ctx, True)


COMMANDS = tuple(
    SlashCommand(name, summary, handler, needs_bot=True)
    for name, summary, handler in (
        ("threads", "Show task threads", threads),
        ("background", "Show background work", background),
        ("subagents", "Show subagents", subagents),
        ("outline", "Show conversation outline", outline),
        ("suggestions", "Show suggestions", suggestions),
        ("read", "Mark bot read", read),
        ("unread", "Mark bot unread", unread),
    )
)
