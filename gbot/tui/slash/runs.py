"""Run-control actions for the selected bot and conversation."""

from gbot.output import terminal_safe
from gbot.service import runs
from gbot.service.models import Bot
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.slash import SlashCommand, SlashContext


def working(bot: Bot | None) -> bool:
    return bool(bot and (bot.running or bot.running_turn or bot.composing))


def stop(ctx: SlashContext, args: str = "") -> None:
    if ctx.bot_id is None:
        return
    bot = ctx.app.state.bots[ctx.bot_id]
    from gbot.tui.screens.home import HomeScreen

    sessions = (
        (bot.running_session_ids or (None,))
        if isinstance(ctx.screen, HomeScreen)
        else (ctx.session_id,)
    )

    def worker() -> None:
        try:
            stopped = False
            for session in sessions:
                stopped = (
                    runs.interrupt(ctx.service.transport, bot.id, session) or stopped
                )
            ctx.app.call_from_thread(ctx.app.bot_error, bot.id)
            ctx.app.call_from_thread(ctx.app.user_acted)
            name = terminal_safe(bot.name)
            notice = f"Stopped {name}" if stopped else f"{name} had nothing running"
            ctx.app.call_from_thread(ctx.app.notify, notice, markup=False)
        except Exception as error:  # noqa: BLE001 - worker boundary
            ctx.app.call_from_thread(ctx.app.bot_error, bot.id, error)

    ctx.app.run_worker(worker, thread=True, exit_on_error=False)


def fresh(ctx: SlashContext, args: str) -> None:
    if ctx.bot_id is None:
        return
    bot = ctx.app.state.bots[ctx.bot_id]
    name = terminal_safe(bot.name)
    session = (
        "the main chat"
        if ctx.session_id is None
        else f"session {terminal_safe(ctx.session_id)}"
    )

    def confirmed(ok: bool | None) -> None:
        if not ok:
            return

        def worker() -> None:
            try:
                runs.start_fresh(ctx.service.transport, bot.id, ctx.session_id)
                ctx.app.call_from_thread(ctx.app.bot_error, bot.id)
                ctx.app.call_from_thread(ctx.app.user_acted)
                ctx.app.call_from_thread(
                    ctx.app.notify, f"Started fresh with {name}", markup=False
                )
            except Exception as error:  # noqa: BLE001 - worker boundary
                ctx.app.call_from_thread(ctx.app.bot_error, bot.id, error)

        ctx.app.run_worker(worker, thread=True, exit_on_error=False)

    ctx.app.push_screen(
        ConfirmScreen(
            f"Start fresh with {name}?",
            f"The bot starts a new conversation in {session}. The app calls this Reset.",
            "Start fresh",
        ),
        confirmed,
    )


def rollback(ctx: SlashContext, args: str) -> None:
    from gbot.tui.screens.session import SessionScreen

    if ctx.bot_id is None or not isinstance(ctx.screen, SessionScreen):
        return
    bot = ctx.app.state.bots[ctx.bot_id]
    name = terminal_safe(bot.name)
    screen = ctx.screen

    def confirmed(ok: bool | None) -> None:
        if not ok:
            return

        def worker() -> None:
            try:
                before = None
                draft = None
                while True:
                    page = ctx.service.transcript(
                        bot.id, session_id=ctx.session_id, before_seq=before
                    )
                    users = [entry for entry in page.entries if entry.role == "user"]
                    if users:
                        draft = max(users, key=lambda entry: entry.seq).text
                        break
                    if page.next_before_seq is None or page.next_before_seq == before:
                        break
                    before = page.next_before_seq
                runs.roll_back(ctx.service.transport, bot.id, ctx.session_id)
                if draft is not None:
                    ctx.app.call_from_thread(screen.restore_draft, draft)
                ctx.app.call_from_thread(ctx.app.bot_error, bot.id)
                ctx.app.call_from_thread(ctx.app.user_acted)
                ctx.app.call_from_thread(ctx.app.notify, "Rolled back", markup=False)
            except Exception as error:  # noqa: BLE001 - worker boundary
                ctx.app.call_from_thread(ctx.app.bot_error, bot.id, error)

        ctx.app.run_worker(worker, thread=True, exit_on_error=False)

    ctx.app.push_screen(
        ConfirmScreen(
            f"Roll back {name}'s last turn?",
            "Your last message comes back to the composer to edit. The app calls this Edit.",
            "Roll back",
        ),
        confirmed,
    )


COMMANDS = (
    SlashCommand("interrupt", "Stop the bot", stop, needs_bot=True),
    SlashCommand("fresh", "Start a fresh conversation", fresh, needs_bot=True),
    SlashCommand(
        "rollback", "Roll back the last turn", rollback, scope="session", needs_bot=True
    ),
)
