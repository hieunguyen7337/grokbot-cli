"""The home view's event store, independent of Textual."""

from dataclasses import dataclass, field

from gbot.service import events
from gbot.service.models import Bot, Card, ConnectionStatus


@dataclass
class AppState:
    bots: dict[str, Bot] = field(default_factory=dict)
    cards: dict[str, list[Card]] = field(default_factory=dict)
    status: ConnectionStatus = ConnectionStatus.CONNECTING
    connection: events.ConnectionChanged = field(
        default_factory=lambda: events.ConnectionChanged(ConnectionStatus.CONNECTING)
    )
    errors: dict[str, str] = field(default_factory=dict)

    def apply(self, event: events.Event) -> set[str]:
        if isinstance(event, events.RosterReplaced):
            self.bots = {bot.id: bot for bot in event.bots}
            self.cards = {
                key: value for key, value in self.cards.items() if key in self.bots
            }
            self.errors = {
                key: value for key, value in self.errors.items() if key in self.bots
            }
            return {"roster"}
        if isinstance(event, events.BotChanged):
            self.bots[event.bot.id] = event.bot
            return {"roster"}
        if isinstance(event, events.BotOverlay) and event.bot_id in self.bots:
            self.bots[event.bot_id] = self.bots[event.bot_id].with_overlay(event.fields)
            return {"roster"}
        if isinstance(event, events.ConnectionChanged):
            self.status = event.status
            self.connection = event
            return {"status"}
        if isinstance(event, events.RosterResync):
            ids = [event.bot_id] if event.bot_id else self.bots
            return {f"cards:{bot_id}" for bot_id in ids}
        if isinstance(event, (events.EntryAdded, events.EntryChanged)):
            bot = self.bots.get(event.entry.bot_id)
            if event.entry.card_type or (bot and bot.awaiting):
                return {f"cards:{event.entry.bot_id}"}
        return set()
