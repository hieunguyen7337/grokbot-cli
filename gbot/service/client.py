"""The real conversation service, with owned gateway consumers."""

import threading
from collections.abc import Callable, Mapping, Sequence

import httpx

from . import cards, conversation
from .attachments import Attachment
from .broker import BrokerTransport, CredentialBroker, GatewayConsumer, default_mint
from .errors import AsleepError
from .hub import EventHub
from .models import Action, AnswerResult, Bot, Card, SendResult, TranscriptPage
from .routing import Harness, Router
from .transport import Transport


class _OwnedTransport(BrokerTransport):
    def __init__(self, service: "GbotService", *, background: bool = False) -> None:
        super().__init__(service.broker, background=background)
        self._service = service

    def command(self, name: str, args: Mapping[str, object] | None = None) -> object:
        if getattr(self._local, "consumer", None) is None:
            self._local.consumer = self._service._consumer(
                "transport", background=self.background
            )
        return super().command(name, args)


class _RoutedTransport(Router, BrokerTransport):
    def __init__(
        self,
        inner: _OwnedTransport,
        harness: Harness,
        *,
        mirror: Transport | None = None,
    ) -> None:
        BrokerTransport.__init__(self, inner.broker, background=inner.background)
        Router.__init__(self, inner, harness, mirror=mirror)


class GbotService:
    def __init__(self, broker: CredentialBroker) -> None:
        self.broker = broker
        self._lock = threading.RLock()
        self._closed = False
        self._consumers: list[GatewayConsumer] = []
        self._hubs: list[EventHub] = []
        self.harness = Harness()
        background = _OwnedTransport(self, background=True)
        self.transport: Transport = _RoutedTransport(
            _OwnedTransport(self), self.harness, mirror=background
        )
        self._background_transport = _RoutedTransport(background, self.harness)

    def _consumer(self, name: str, *, background: bool) -> GatewayConsumer:
        with self._lock:
            if self._closed:
                raise RuntimeError("Service is closed.")
            consumer = self.broker.consumer(name, background=background)
            self._consumers.append(consumer)
            return consumer

    def roster(self) -> list[Bot]:
        return conversation.roster(self.transport)

    def open(
        self, bot_id: str, *, session_id: str | None = None, limit: int = 200
    ) -> TranscriptPage:
        return conversation.open_chat(
            self.transport, bot_id, session_id=session_id, limit=limit
        )

    def transcript(
        self,
        bot_id: str,
        *,
        before_seq: int | None = None,
        limit: int = 50,
        session_id: str | None = None,
    ) -> TranscriptPage:
        return conversation.transcript(
            self.transport,
            bot_id,
            before_seq=before_seq,
            limit=limit,
            session_id=session_id,
        )

    def send(
        self,
        bot_id: str,
        text: str,
        *,
        session_id: str | None = None,
        nonce: str | None = None,
        attachments: Sequence[Attachment] = (),
    ) -> SendResult:
        if not attachments:
            return conversation.send(
                self.transport, bot_id, text, session_id=session_id, nonce=nonce
            )
        return conversation.send(
            self.transport,
            bot_id,
            text,
            session_id=session_id,
            nonce=nonce,
            attachments=attachments,
        )

    def pending(
        self,
        bot_ids: Sequence[str] | None = None,
        *,
        bots: Sequence[Bot] | None = None,
        recent_pages: int | None = None,
    ) -> tuple[list[Card], list[str]]:
        if bots is None:
            bots = conversation.roster(self._background_transport)
        rows = [
            dict(bot.raw)
            for bot in bots
            if (bot.awaiting is not None if bot_ids is None else bot.id in bot_ids)
        ]
        return cards.discover(
            self._background_transport,
            rows,
            all_bots=True,
            recent_pages=recent_pages,
        )

    def still_pending(self, card: Card) -> bool:
        return cards.still_pending(self.transport, card)

    def answer(self, card: Card, action: Action) -> AnswerResult:
        return cards.answer(self.transport, card, action)

    def box_state(self, bot_id: str) -> str | None:
        try:
            return conversation.box_state(self._background_transport, bot_id)
        except AsleepError:
            return "hibernated"

    def event_source(self) -> EventHub:
        with self._lock:
            hub = EventHub(
                self._consumer("events", background=True), self._background_transport
            )
            self._hubs.append(hub)
            return hub

    def close(self) -> None:
        self.harness.drain()
        with self._lock:
            if self._closed:
                return
            self._closed = True
            hubs, consumers = list(self._hubs), list(self._consumers)
        for hub in hubs:
            hub.close()
        for consumer in consumers:
            consumer.close()


def connect(
    *,
    mint: Callable[[], Mapping[str, object]] | None = None,
    http_transport: httpx.BaseTransport | None = None,
) -> GbotService:
    broker = CredentialBroker(
        mint if mint is not None else default_mint, transport=http_transport
    )
    broker.current()
    return GbotService(broker)
