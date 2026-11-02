import json

from gbot import cli, context
from gbot.service.search import DEMO_RPCS
from gbot.service.transport import FakeTransport


def test_places_area_json(monkeypatch, capsys):
    fake = FakeTransport(rpcs=DEMO_RPCS)
    monkeypatch.setattr(context, "manager_factory", lambda: fake)

    class Backend:
        def unary(self, service, name, payload):
            return fake.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    assert (
        cli.main(
            [
                "search",
                "places",
                "bot",
                "entry",
                "2",
                "--south-west",
                "1,2",
                "--north-east",
                "3,4",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["outcome"] == "empty"
    assert fake.calls == [
        (
            "rpc",
            "SearchGrokBotPlacesArea",
            {
                "agentId": "bot",
                "entryId": "entry",
                "sessionId": "",
                "language": "",
                "cardIndex": 2,
                "area": {
                    "southWest": {"latitude": 1.0, "longitude": 2.0},
                    "northEast": {"latitude": 3.0, "longitude": 4.0},
                },
            },
        )
    ]
