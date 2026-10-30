import json
from pathlib import Path

import pytest

from gbot.service import templates as t
from gbot.service.fake import load_fake
from gbot.service.models import Bot
from gbot.service.transport import FakeTransport
from groken.client import ConnectError


def transport():
    return FakeTransport(t.DEMO_COMMANDS, t.DEMO_RPCS)


def test_marketplace_paging():
    fake = transport()
    pages = iter(
        [
            {
                "featuredListings": [
                    {
                        "slug": "star",
                        "shareId": "share",
                        "name": "Star",
                        "description": "Desc",
                        "category": "Work",
                        "categories": ["Work"],
                        "creator": {"name": "Maker"},
                        "defaultAvatar": {"shape": "blob", "color": "blue"},
                    }
                ],
                "nextPageToken": "next",
                "allCategoriesOrder": ["Work"],
            },
            {"listings": [{"slug": "other"}], "allCategoriesOrder": ["Work", "Play"]},
        ]
    )
    fake.rpcs["ListPublicGrokBotMarketplaceListings"] = lambda _: next(pages)
    result = t.marketplace(fake, "Work")
    assert result.category_order == ("Work", "Play")
    assert result.featured_listings[0].creator_name == "Maker"
    assert result.featured_listings[0].default_avatar == {
        "shape": "blob",
        "color": "blue",
    }
    assert result.listings[0].slug == "other"
    assert [call[2] for call in fake.calls] == [
        {"category": "Work", "pageSize": 100, "pageToken": ""},
        {"category": "Work", "pageSize": 100, "pageToken": "next"},
    ]


def test_marketplace_page_limit():
    fake = FakeTransport(
        rpcs={"ListPublicGrokBotMarketplaceListings": {"nextPageToken": "again"}}
    )
    t.marketplace(fake)
    assert len(fake.calls) == 20


@pytest.mark.parametrize(
    "reply",
    [
        {},
        {"template": {"name": "A"}, "expectedActiveVersion": 0},
        {"template": {"name": "A"}, "expectedActiveVersion": -1},
    ],
)
def test_details_refuse(reply):
    with pytest.raises(ValueError, match="missing|active version"):
        t.details(
            FakeTransport(rpcs={"GetGrokBotTemplateImportDetails": reply}), "share"
        )


def test_backend_create_and_note():
    fake = transport()
    detail = t.details(fake, "demo-template")
    result = t.create_from_template(fake, detail, agent_id="reserved", language="en")
    assert result.bot.id == "reserved" and result.bot.raw["harness"] == "temporal"
    assert result.setup_handled_by_server and not result.note
    assert fake.calls[-1][2] == {
        "agentId": "reserved",
        "shareId": "demo-template",
        "expectedActiveVersion": 1,
        "setupDelegationSupported": True,
        "language": "en",
    }
    fake.rpcs["CreateGrokBotAgentFromTemplate"] = {
        "agent": {"agentId": "reserved", "name": "New", "harness": 2},
        "blobGetUrl": "https://never-fetch",
    }
    result = t.create_from_template(fake, detail, agent_id="reserved")
    assert result.note == "Finish this template's setup in the Grok Bot app"
    assert len(fake.calls) == 3


@pytest.mark.parametrize(
    "agent",
    [
        {"agentId": "wrong", "name": "A", "harness": 2},
        {"agentId": "reserved", "name": "A", "harness": 1},
        {},
    ],
)
def test_refuse_invalid_created_agent(agent):
    fake = transport()
    detail = t.details(fake, "demo-template")
    fake.rpcs["CreateGrokBotAgentFromTemplate"] = {"agent": agent}
    with pytest.raises(ValueError, match="agent id or harness"):
        t.create_from_template(fake, detail, agent_id="reserved")


def test_fallback_only_unimplemented():
    fake = transport()
    detail = t.details(fake, "demo-template")
    fake.rpcs["CreateGrokBotAgentFromTemplate"] = ConnectError(
        501, json.dumps({"code": "unimplemented"})
    )
    result = t.create_from_template(fake, detail, agent_id="reserved")
    assert not result.setup_handled_by_server and result.note
    assert fake.calls[-1] == (
        "command",
        "createAgentFromTemplate",
        {
            "shareId": "demo-template",
            "agentId": "reserved",
            "expectedActiveVersion": 1,
            "name": "Helper",
            "avatarShape": "blob",
            "avatarColor": "blue",
        },
    )
    for error in (
        ConnectError(404, "unknown"),
        ConnectError(500, "failed"),
        ConnectError(403, "unimplemented is unavailable"),
    ):
        fake.rpcs["CreateGrokBotAgentFromTemplate"] = error
        with pytest.raises(ConnectError):
            t.create_from_template(fake, detail)
        assert fake.calls[-1][0] == "rpc"


def test_read_only_routing_and_demo():
    fake = transport()
    for harness, kind in (("temporal", "rpc"), ("box", "command")):
        t.template_for_bot(fake, Bot("bot", "Bot", raw={"harness": harness}))
        assert fake.calls[-1][0] == kind
        assert fake.calls[-1][2] == {"sourceAgentId": "bot"}
        fake.commands["listAgents"] = [{"id": "bot", "name": "Bot", "harness": harness}]
        t.export_policy(fake)
        assert fake.calls[-1][0] == kind
    demo = load_fake()
    assert set(t.COMMANDS) <= demo.transport.commands.keys()
    assert set(t.RPCS) <= demo.transport.rpcs.keys()
    entries = json.loads(Path("docs/parity.json").read_text(encoding="utf-8"))[
        "entries"
    ]
    assert all(
        e["status"] == "done" for e in entries if e["name"] in {*t.COMMANDS, *t.RPCS}
    )
