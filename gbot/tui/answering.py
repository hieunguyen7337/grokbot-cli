"""Recheck and answer a card without blocking the UI or retrying a mutation."""

import asyncio

from textual.app import App

from gbot.output import terminal_safe
from gbot.service.api import Service
from gbot.service.cards import effect as card_effect
from gbot.service.cards import plan
from gbot.service.models import Action, AnswerResult, Card
from gbot.tui.screens.confirm import ConfirmScreen


async def answer_card(
    app: App,
    service: Service,
    card: Card,
    action: Action,
    *,
    confirm: bool,
    effect: str,
) -> AnswerResult | None:
    try:
        if not await asyncio.to_thread(service.still_pending, card):
            app.notify("This card was already answered")
            return None
        if confirm:
            method, payload = plan(card, action)
            wording = card_effect(card, action, method, payload)
            wording = {
                "sends it now": f"Sends this {'email' if card.type == 'email-draft' else 'message'} now",
                "discards it": "Discards this draft",
                "approved": "Approves this request",
                "always": "Always allows this tool",
                "allow-once": "Allows this tool once",
            }.get(wording or "", wording or "Submits this secret")
            result: asyncio.Future[bool | None] = (
                asyncio.get_running_loop().create_future()
            )

            def resolved(value: bool | None) -> None:
                if not result.done():
                    result.set_result(value)

            app.push_screen(
                ConfirmScreen(
                    f"{card.bot_name} · {card.session_id or 'main'}",
                    f"{wording}\n{card.summary}",
                    {
                        "approve": "Send" if card.draft is not None else "Approve",
                        "deny": "Discard",
                        "secret": "Submit",
                    }.get(action.kind, "Confirm"),
                ),
                resolved,
            )
            if await result is not True:
                return None
            # The dialog may have stayed open while the card was answered elsewhere.
            if not await asyncio.to_thread(service.still_pending, card):
                app.notify("This card was already answered")
                return None
        answer = await asyncio.to_thread(service.answer, card, action)
    except Exception as exc:  # noqa: BLE001 — a failed answer becomes a notice, never a crash
        if action.kind == "secret":
            message = "Secret was not submitted successfully; no value is displayed."
        elif isinstance(exc, ValueError):
            message = terminal_safe(str(exc))
        else:
            message = f"Could not answer: {terminal_safe(str(exc))}"
        app.notify(message, markup=False, severity="error")
        return None
    app.notify(terminal_safe(effect), markup=False)
    return answer
