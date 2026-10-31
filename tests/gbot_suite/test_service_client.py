from unittest.mock import Mock

import httpx
import pytest

from gbot.service import cards, client, conversation
from gbot.service.api import Service
from gbot.service.broker import BrokerTransport, CredentialBroker, GatewayConsumer
from gbot.service.errors import AsleepError, SignedOutError
from gbot.service.models import Action, Bot, TranscriptPage


def mint():
    return {
        "gatewayUrl": "https://offline.invalid",
        "gatewayToken": "fake",
        "networkToken": "fake",
        "podId": "p",
    }


def test_conversation_delegation(monkeypatch):
    service: Service = client.GbotService(CredentialBroker(mint))
    for method, function, args, kwargs, result in [
        ("roster", "roster", (), {}, []),
        (
            "open",
            "open_chat",
            ("b",),
            {"session_id": "s", "limit": 4},
            TranscriptPage(()),
        ),
        (
            "transcript",
            "transcript",
            ("b",),
            {"before_seq": 8, "limit": 3, "session_id": "s"},
            TranscriptPage(()),
        ),
        ("send", "send", ("b", "hi"), {"session_id": "s", "nonce": "n"}, object()),
    ]:
        mocked = Mock(return_value=result)
        monkeypatch.setattr(conversation, function, mocked)
        assert getattr(service, method)(*args, **kwargs) is result
        mocked.assert_called_once_with(service.transport, *args, **kwargs)
    assert isinstance(service.transport, BrokerTransport)
    assert not service.transport.background


def test_cards_and_background(monkeypatch):
    service = client.GbotService(CredentialBroker(mint))
    waiting = Bot.from_row({"id": "a", "name": "Alpha", "awaitingUserResponse": {}})
    idle = Bot.from_row({"id": "b", "name": "Beta"})
    assert waiting is not None and idle is not None
    roster = Mock(return_value=[waiting, idle])
    discover = Mock(return_value=([], ["warning"]))
    monkeypatch.setattr(conversation, "roster", roster)
    monkeypatch.setattr(cards, "discover", discover)
    assert service.pending() == ([], ["warning"])
    background = roster.call_args.args[0]
    assert background.background
    assert discover.call_args.args == (background, [dict(waiting.raw)])
    assert discover.call_args.kwargs == {"all_bots": True}
    service.pending(["b"])
    assert discover.call_args.args == (background, [dict(idle.raw)])
    card = Mock()
    action = Action("approve")
    for name, args in [("still_pending", (card,)), ("answer", (card, action))]:
        delegated = Mock(return_value=True)
        monkeypatch.setattr(cards, name, delegated)
        assert getattr(service, name)(*args) is True
        delegated.assert_called_once_with(service.transport, *args)
    state = Mock(side_effect=AsleepError())
    monkeypatch.setattr(conversation, "box_state", state)
    assert service.box_state("a") == "hibernated"
    state.assert_called_once_with(background, "a")


def test_connect_and_close(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=[])

    service = client.connect(mint=mint, http_transport=httpx.MockTransport(handle))
    assert service.roster() == []
    assert service.pending() == ([], [])
    hub = service.event_source()
    assert hub._transport is service._background_transport
    assert isinstance(hub._opener, GatewayConsumer)
    assert hub._opener.background
    consumers = [Mock(wraps=c.close) for c in service._consumers]
    for consumer, close in zip(service._consumers, consumers):
        monkeypatch.setattr(consumer, "close", close)
    service.close()
    service.close()
    assert len(requests) == 2
    for consumer in consumers:
        consumer.assert_called_once()


def test_connect_signed_out(monkeypatch):
    def missing():
        raise SystemExit("no tokens")

    monkeypatch.setattr(client, "default_mint", missing)
    with pytest.raises(SignedOutError):
        client.connect()
