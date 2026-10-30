"""Actions on messages currently displayed in a session."""

from collections.abc import Callable
from typing import Literal

from gbot.output import terminal_safe
from gbot.service import reactions
from gbot.service.models import Entry
from gbot.tui.panels.kit import FormField, FormPanel, ListPanel, PanelRow
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.widgets.transcript import Transcript

EMOJI = (
    "\N{THUMBS UP SIGN}",
    "\N{THUMBS DOWN SIGN}",
    "\N{HEAVY BLACK HEART}\N{VARIATION SELECTOR-16}",
    "\N{FACE WITH TEARS OF JOY}",
    "\N{PARTY POPPER}",
    "\N{THINKING FACE}",
    "\N{EYES}",
    "\N{WHITE HEAVY CHECK MARK}",
)


def _entries(ctx: SlashContext) -> list[Entry]:
    history = ctx.screen.query_one(Transcript)
    return [
        entry
        for widget in history.entries.values()
        if isinstance((entry := getattr(widget, "entry", None)), Entry)
    ]


def _mutable(ctx: SlashContext) -> bool:
    if ctx.app.read_only:
        ctx.app.notify("Read-only mode", markup=False)
        return False
    return True


def _newest(ctx: SlashContext) -> Entry | None:
    entries = [
        e
        for e in _entries(ctx)
        if e.role != "user" and e.kind in {"message", "send-message"}
    ]
    if not entries:
        ctx.app.notify("No bot message shown", markup=False)
        return None
    return entries[-1]


def _pick(ctx: SlashContext, callback: Callable[[Entry], None]) -> None:
    entries = list(reversed(_entries(ctx)[-30:]))
    by_id = {e.id: e for e in entries}
    bot = ctx.app.state.bots.get(ctx.bot_id or "")
    name = bot.name if bot else ctx.bot_id or ""
    rows = [
        PanelRow(
            e.id,
            f"{'you' if e.role == 'user' else terminal_safe(name)}: {terminal_safe(e.text).splitlines()[0] if e.text else ''}",
        )
        for e in entries
    ]

    def selected(row: PanelRow) -> None:
        ctx.app.pop_screen()
        # Register follow-up screen callbacks on the app, not the dismissed picker.
        ctx.app.call_later(callback, by_id[row.key])

    ctx.app.push_screen(ListPanel("Choose a message", lambda: rows, on_select=selected))


def _run(ctx: SlashContext, operation: Callable[[], None], notice: str) -> None:
    def worker() -> None:
        try:
            operation()
            ctx.app.call_from_thread(ctx.app.bot_error, ctx.bot_id)
            ctx.app.call_from_thread(ctx.app.user_acted)
            ctx.app.call_from_thread(ctx.app.notify, notice, markup=False)
        except Exception as error:  # noqa: BLE001 - worker boundary
            ctx.app.call_from_thread(ctx.app.bot_error, ctx.bot_id, error)

    ctx.app.run_worker(worker, thread=True, exit_on_error=False)


def _react(ctx: SlashContext, entry: Entry, emoji: str) -> None:
    removed = any(e == emoji and own for e, _, own in reactions.entry_reactions(entry))
    _run(
        ctx,
        lambda: reactions.react(
            ctx.service.transport, ctx.bot_id or "", entry.id, emoji, ctx.session_id
        ),
        "Removed reaction" if removed else "Reacted",
    )


def react(ctx: SlashContext, args: str) -> None:
    if not _mutable(ctx):
        return
    if args:
        entry = _newest(ctx)
        if entry:
            _react(ctx, entry, args)
        return

    def choose(entry: Entry) -> None:
        rows = [PanelRow(e, e) for e in EMOJI] + [PanelRow("other", "Other…")]

        def selected(row: PanelRow) -> None:
            ctx.app.pop_screen()
            if row.key == "other":

                def submit(values: dict[str, str | bool]) -> str | None:
                    emoji = str(values["emoji"])
                    try:
                        reactions.react(
                            ctx.service.transport,
                            ctx.bot_id or "",
                            entry.id,
                            emoji,
                            ctx.session_id,
                        )
                    except Exception as error:
                        ctx.app.call_from_thread(ctx.app.bot_error, ctx.bot_id, error)
                        raise
                    ctx.app.call_from_thread(ctx.app.bot_error, ctx.bot_id)
                    ctx.app.call_from_thread(ctx.app.user_acted)
                    return (
                        "Removed reaction"
                        if any(
                            e == emoji and own
                            for e, _, own in reactions.entry_reactions(entry)
                        )
                        else "Reacted"
                    )

                ctx.app.push_screen(
                    FormPanel(
                        "Other reaction",
                        [FormField("emoji", "Emoji", required=True)],
                        submit,
                    )
                )
            else:
                _react(ctx, entry, row.key)

        ctx.app.push_screen(
            ListPanel("Choose a reaction", lambda: rows, on_select=selected)
        )

    _pick(ctx, choose)


def feedback(ctx: SlashContext, args: str) -> None:
    if not _mutable(ctx):
        return
    entry = _newest(ctx)
    if not entry:
        return
    if args:
        if args not in ("up", "down"):
            ctx.app.notify("Use /feedback up or /feedback down", markup=False)
            return
        action: Literal["up", "down"] = "up" if args == "up" else "down"
        _run(
            ctx,
            lambda: reactions.vote(
                ctx.service.transport,
                ctx.bot_id or "",
                entry.id,
                action,
                session_id=ctx.session_id,
            ),
            "Feedback sent",
        )
        return
    fields = [
        FormField(
            "vote",
            "Feedback",
            kind="choice",
            value="Helpful",
            choices=("Helpful", "Not helpful"),
        )
    ]
    fields.extend(
        FormField(key, label, kind="toggle")
        for key, label in zip(
            reactions.FEEDBACK_CATEGORIES, reactions.FEEDBACK_LABELS, strict=True
        )
    )
    fields.append(FormField("comment", "Comment", kind="multiline"))

    def submit(values: dict[str, str | bool]) -> str | None:
        try:
            action: Literal["up", "down"] = (
                "up" if values["vote"] == "Helpful" else "down"
            )
            reactions.vote(
                ctx.service.transport,
                ctx.bot_id or "",
                entry.id,
                action,
                session_id=ctx.session_id,
            )
            categories = [key for key in reactions.FEEDBACK_CATEGORIES if values[key]]
            comment = str(values["comment"])
            if categories or comment:
                reactions.vote(
                    ctx.service.transport,
                    ctx.bot_id or "",
                    entry.id,
                    "submit",
                    session_id=ctx.session_id,
                    categories=categories,
                    comment=comment,
                )
            ctx.app.call_from_thread(ctx.app.bot_error, ctx.bot_id)
            ctx.app.call_from_thread(ctx.app.user_acted)
            return "Feedback sent"
        except Exception as error:
            # Raising keeps the form open with the error, so the comment is not lost.
            ctx.app.call_from_thread(ctx.app.bot_error, ctx.bot_id, error)
            raise

    ctx.app.push_screen(FormPanel("Feedback", fields, submit))


def thread(ctx: SlashContext, args: str) -> None:
    if not _mutable(ctx):
        return

    def confirm(entry_id: str) -> None:
        def done(ok: bool | None) -> None:
            if ok:
                _run(
                    ctx,
                    lambda: reactions.thread_from(
                        ctx.service.transport, ctx.bot_id or "", entry_id
                    ),
                    "Thread started · /threads lists it",
                )

        ctx.app.push_screen(
            ConfirmScreen(
                "Start a thread from this message?",
                terminal_safe(entry_id),
                "Start thread",
            ),
            done,
        )

    if args:
        confirm(args)
    else:
        _pick(ctx, lambda entry: confirm(entry.id))


COMMANDS = (
    SlashCommand(
        "react",
        "React to a message",
        react,
        scope="session",
        args="[emoji]",
        needs_bot=True,
    ),
    SlashCommand(
        "feedback",
        "Give feedback",
        feedback,
        scope="session",
        args="[up|down]",
        needs_bot=True,
    ),
    SlashCommand(
        "thread",
        "Start a thread",
        thread,
        scope="session",
        args="[entry-id]",
        needs_bot=True,
    ),
)
