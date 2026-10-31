"""Inspect gateway alerts and act on their advertised choices."""

import webbrowser
from collections.abc import Callable
from time import time
from urllib.parse import urlsplit

from textual import events

from gbot.output import terminal_safe
from gbot.service import runs, trays
from gbot.tui.model import age_text
from gbot.tui.panels import ListPanel, PanelAction, PanelRow
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashCommand, SlashContext


class _TraysPanel(ListPanel):
    def on_mount(self) -> None:
        from textual.widgets import Static

        super().on_mount()
        self.query_one(".panel-footer", Static).update(
            "up/down | esc back | f fresh | b back | o link | $ buy | a app | m model | d dismiss | c clear"
        )

    def on_key(self, event: events.Key) -> None:
        if event.key == "c" and not self.visible_rows:
            self.invoke(
                next(action for action in self.actions if action.key == "c"),
                PanelRow("", ""),
            )
            event.stop()
            event.prevent_default()
            return
        # Textual names the printable dollar key rather than passing its glyph.
        if event.key == "dollar_sign" and self.visible_rows:
            self.invoke(
                next(action for action in self.actions if action.key == "$"),
                self.visible_rows[self.index],
            )
            event.stop()
            event.prevent_default()
        else:
            super().on_key(event)


def show_trays(ctx: SlashContext, args: str) -> None:
    app = ctx.app
    selected: dict[str, trays.Tray] = {}
    session = ctx.screen if isinstance(ctx.screen, SessionScreen) else None

    def load() -> list[PanelRow]:
        loaded = trays.trays(ctx.service.transport)
        selected.clear()
        selected.update((tray.id, tray) for tray in loaded)
        rows = []
        for tray in loaded:
            if session is not None and tray.agent_id != session.bot_id:
                continue
            bot = app.state.bots.get(tray.agent_id)
            label = (
                tray.title
                if session is not None
                else f"{bot.name if bot else tray.agent_id}: {tray.title}"
            )
            detail = (tray.detail or "").partition("\n")[0]
            age = age_text(int(time() * 1000 - tray.created_at))
            rows.append(
                PanelRow(
                    tray.id,
                    terminal_safe(label),
                    terminal_safe(f"{detail} · {age}".strip(" ·")),
                    f"×{tray.count:g}" if tray.count > 1 else "",
                    "muted" if tray.severity == "info" else "error",
                )
            )
        return rows

    def notice(message: str) -> None:
        app.notify(terminal_safe(message), markup=False)

    def readonly() -> bool:
        if app.read_only:
            notice("Read-only mode")
            return True
        return False

    def change(tray: trays.Tray, operation: Callable[[], None]) -> None:
        if readonly():
            return

        def worker() -> None:
            try:
                operation()
                app.call_from_thread(app.bot_error, tray.agent_id)
                app.call_from_thread(app.user_acted)
                app.call_from_thread(app.refresh_trays)
                app.call_from_thread(panel.reload)
            except Exception as error:  # noqa: BLE001 - action worker boundary
                app.call_from_thread(app.bot_error, tray.agent_id, error)

        app.run_worker(worker, thread=True, exit_on_error=False)

    def act(row: PanelRow, key: str) -> None:
        if key in {"f", "b", "d", "c"} and readonly():
            return
        if key == "c":

            def confirmed(ok: bool | None) -> None:
                if not ok or readonly():
                    return

                def worker() -> None:
                    try:
                        trays.clear(ctx.service.transport)
                        app.call_from_thread(app.refresh_trays)
                        app.call_from_thread(panel.reload)
                    except Exception as error:  # noqa: BLE001 - action worker boundary
                        app.call_from_thread(
                            app.notify,
                            terminal_safe(str(error)),
                            severity="warning",
                            markup=False,
                        )

                app.run_worker(worker, thread=True, exit_on_error=False)

            app.push_screen(
                ConfirmScreen(
                    f"Clear all {len(selected)} alerts?",
                    "This clears the alerts of every bot, including any not listed here.",
                    "Clear all",
                ),
                confirmed,
            )
            return
        tray = selected[row.key]
        if key == "d":
            change(tray, lambda: trays.dismiss(ctx.service.transport, tray.id))
            return
        kinds, name = {
            "f": (("start-fresh",), "start fresh"),
            "b": (("roll-back",), "roll back"),
            "o": (("open-url", "upgrade", "upgradeChoice"), "open link"),
            "$": (("open-buy-credits",), "buy credits"),
            "a": (("dashboard-action",), "dashboard"),
            "m": (("switch-model",), "switch model"),
        }[key]
        action = next((a for a in tray.actions if a.kind in kinds), None)
        if action is None:
            notice(f"This alert has no {name} action")
            return
        if key in {"$", "a", "m"}:
            notice("Do this in the Grok Bot app")
            return
        if key == "o":
            url = action.url or ""
            try:
                https = url.startswith("https://") and bool(urlsplit(url).netloc)
            except ValueError:
                https = False
            if not https:
                notice("Only https links open")
                return

            def opened(ok: bool | None) -> None:
                if ok:
                    try:
                        webbrowser.open(url)
                    except Exception as error:  # noqa: BLE001 - browser boundary
                        app.bot_error(tray.agent_id, error)

            app.push_screen(
                ConfirmScreen(
                    "Open this link in your browser?", terminal_safe(url), "Open"
                ),
                opened,
            )
            return
        bot = app.state.bots.get(tray.agent_id)
        name = terminal_safe(bot.name if bot else tray.agent_id)
        target = action.session_id
        matching = (
            session is not None
            and session.bot_id == tray.agent_id
            and session.session_id == target
        )

        def operation() -> None:
            draft = None
            if key == "b" and matching:
                before = None
                while True:
                    page = ctx.service.transcript(
                        tray.agent_id, session_id=target, before_seq=before
                    )
                    users = [entry for entry in page.entries if entry.role == "user"]
                    if users:
                        draft = max(users, key=lambda entry: entry.seq).text
                        break
                    if page.next_before_seq is None or page.next_before_seq == before:
                        break
                    before = page.next_before_seq
            command = runs.start_fresh if key == "f" else runs.roll_back
            command(ctx.service.transport, tray.agent_id, target)
            trays.dismiss(ctx.service.transport, tray.id)
            if draft is not None and session is not None:
                app.call_from_thread(session.restore_draft, draft)
            message = (
                f"Started fresh with {name}"
                if key == "f"
                else "Rolled back"
                + ("" if matching else " · open the bot to edit your message")
            )
            app.call_from_thread(notice, message)

        def confirmed(ok: bool | None) -> None:
            if ok:
                change(tray, operation)

        description = (
            "the main chat" if target is None else f"session {terminal_safe(target)}"
        )
        app.push_screen(
            ConfirmScreen(
                f"Start fresh with {name}?"
                if key == "f"
                else f"Roll back {name}'s last turn?",
                f"The bot starts a new conversation in {description}. The app calls this Reset."
                if key == "f"
                else "Your last message comes back to the composer to edit. The app calls this Edit.",
                "Start fresh" if key == "f" else "Roll back",
            ),
            confirmed,
        )

    panel = _TraysPanel(
        "Alerts",
        load,
        empty="No alerts",
        actions=tuple(
            PanelAction(key, label, lambda row, key=key: act(row, key))
            for key, label in (
                ("f", "Fresh"),
                ("b", "Roll back"),
                ("o", "Open link"),
                ("$", "Buy credits"),
                ("a", "Dashboard"),
                ("m", "Model"),
                ("d", "Dismiss"),
                ("c", "Clear all"),
            )
        ),
    )
    app.push_screen(panel)


COMMANDS = (SlashCommand("trays", "Show alerts", show_trays),)
