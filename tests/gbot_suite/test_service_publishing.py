import pytest

from gbot.service import publishing as p
from gbot.service.models import Bot
from gbot.service.transport import FakeTransport
from groken.client import ConnectError

TEMPLATE = {
    "shareId": "share",
    "name": "Helper",
    "description": "Desc",
    "published": True,
    "activeVersion": 3,
    "visibility": "GROK_BOT_TEMPLATE_VISIBILITY_PUBLIC",
    "sourceAgentId": "bot",
    "createdAtMs": "1700000000000",
    "updatedAtMs": "1700000001000",
}


def transport(**rpcs):
    return FakeTransport(
        {"listAgents": [{"id": "bot", "name": "Bot", "harness": "temporal"}]},
        {**p.DEMO_RPCS, **rpcs},
    )


def test_template_payloads():
    fake = transport(
        ActivateGrokBotTemplateVersion={"template": TEMPLATE},
        SetGrokBotTemplateVisibility={"template": TEMPLATE},
    )
    result = p.publish_template(fake, "share")
    assert result.active_version == 3 and result.created_at_ms == 1700000000000
    p.publish_template(fake, "share", 2)
    p.set_template_visibility(fake, "share", "public")
    p.set_template_visibility(fake, "share", "team")
    p.delete_template(fake, "share")
    assert [(n, a) for _, n, a in fake.calls] == [
        ("ActivateGrokBotTemplateVersion", {"shareId": "share"}),
        ("ActivateGrokBotTemplateVersion", {"shareId": "share", "version": 2}),
        (
            "SetGrokBotTemplateVisibility",
            {"shareId": "share", "visibility": "GROK_BOT_TEMPLATE_VISIBILITY_PUBLIC"},
        ),
        (
            "SetGrokBotTemplateVisibility",
            {"shareId": "share", "visibility": "GROK_BOT_TEMPLATE_VISIBILITY_TEAM"},
        ),
        ("DeleteGrokBotTemplate", {"shareId": "share"}),
    ]
    with pytest.raises(ValueError):
        p.set_template_visibility(fake, "share", "private")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("GROK_BOT_TEMPLATE_VISIBILITY_TEAM", "team"),
        ("public", "public"),
        (1, "public"),
        ("2", "team"),
        (0, "unknown"),
        (9, "unknown"),
        ("GROK_BOT_TEMPLATE_VISIBILITY_UNSPECIFIED", "unknown"),
        (None, "unknown"),
        (True, "unknown"),
    ],
)
def test_visibility_forms(raw, expected):
    found = p._template({"shareId": "s", "visibility": raw})
    assert found is not None and found.visibility == expected


def test_odd_template_shapes():
    assert p._template({}) is None and p._template("x") is None
    odd = p._template({"shareId": "s", "activeVersion": "x", "createdAtMs": [1]})
    assert odd is not None
    assert odd.active_version is None and odd.created_at_ms is None and odd.name == ""
    fake = transport(ActivateGrokBotTemplateVersion={})
    assert p.publish_template(fake, "s").share_id == "s"


def test_bot_template_and_policy():
    bot = Bot.from_row({"id": "bot", "name": "Bot", "harness": "temporal"})
    assert bot is not None
    fake = transport(
        GetGrokBotTemplateForSourceAgent={"template": TEMPLATE},
        GetGrokBotTemplateExportPolicy={"exportPolicy": "team_only"},
    )
    template, policy = p.bot_template(fake, bot)
    assert template is not None and template.share_id == "share"
    assert policy == "team_only"
    fake.rpcs["GetGrokBotTemplateForSourceAgent"] = {}
    fake.rpcs["GetGrokBotTemplateExportPolicy"] = {"exportPolicy": "weird"}
    assert p.bot_template(fake, bot) == (None, "unknown")


@pytest.mark.parametrize("policy", ["all", "team_only", "none", "unknown"])
def test_every_policy_has_a_sentence(policy):
    assert p.policy_sentence(policy).endswith(".")
    assert len({p.policy_sentence(x) for x in ("all", "team_only", "none")}) == 3


def test_overview_refusal_still_succeeds():
    bot = Bot.from_row({"id": "bot", "name": "Bot", "harness": "temporal"})
    assert bot is not None
    refusal = ConnectError(403, '{"code": "permission_denied", "message": "No teams."}')
    fake = transport(
        GetGrokBotTemplateForSourceAgent=refusal,
        GetGrokBotTemplateExportPolicy={"exportPolicy": "all"},
    )
    view = p.overview(fake, bot)
    assert view.template is None and view.policy == "all"
    assert view.notes == ("No teams.",)
    fake.rpcs["GetGrokBotTemplateExportPolicy"] = ConnectError(500, "boom")
    with pytest.raises(ConnectError):
        p.overview(fake, bot)


@pytest.mark.parametrize(
    "raw,outcome",
    [
        ("GROK_BOT_PUBLISH_AGENT_OUTCOME_PUBLISHED", "published"),
        ("GROK_BOT_PUBLISH_AGENT_OUTCOME_ALREADY_PUBLISHED", "already_published"),
        ("not_shared", "not_shared"),
        (4, "unsupported_harness"),
        (0, "unknown"),
        ("GROK_BOT_PUBLISH_AGENT_OUTCOME_UNSPECIFIED", "unknown"),
        ("surprise", "unknown"),
        (None, "unknown"),
    ],
)
def test_publish_outcomes(raw, outcome):
    fake = transport(
        PublishGrokBotAgent={"outcome": raw, "agent": {"publishedAt": "1800"}}
    )
    result = p.publish_bot(fake, "bot")
    assert result.outcome == outcome
    assert result.published_at_ms == 1800
    assert fake.calls == [("rpc", "PublishGrokBotAgent", {"agentId": "bot"})]
    assert result.sentence == p.outcome_sentence(outcome)


@pytest.mark.parametrize(
    "raw,outcome",
    [
        ("GROK_BOT_UNPUBLISH_AGENT_OUTCOME_UNPUBLISHED", "unpublished"),
        ("GROK_BOT_UNPUBLISH_AGENT_OUTCOME_NOT_PUBLISHED", "not_published"),
        ("GROK_BOT_UNPUBLISH_AGENT_OUTCOME_NOT_SHARED", "not_shared"),
        (4, "unsupported_harness"),
        ("???", "unknown"),
    ],
)
def test_unpublish_outcomes(raw, outcome):
    fake = transport(UnpublishGrokBotAgent={"outcome": raw})
    assert p.unpublish_bot(fake, "bot") == p.PublishResult(outcome, None)
    assert fake.calls == [("rpc", "UnpublishGrokBotAgent", {"agentId": "bot"})]


def test_outcome_sentences():
    for name in {*p.PUBLISH_OUTCOMES, *p.UNPUBLISH_OUTCOMES, "unknown"} - {
        "unspecified"
    }:
        assert p.outcome_sentence(name).endswith(".")
    assert "Share the bot first" in p.outcome_sentence("not_shared")


def test_listing_state():
    def state(**raw):
        bot = Bot.from_row({"id": "b", "name": "B", **raw})
        assert bot is not None
        return p.listing_state(bot)

    assert state() == ("unknown", None)
    assert state(publishedAtMs="1700") == ("published", 1700)
    assert state(publishedAtMs=None) == ("unpublished", None)
    assert state(publishedAt=0) == ("unpublished", None)
    assert state(publishedAtMs="abc") == ("unknown", None)


@pytest.mark.parametrize("reply", [None, [], "ok", 3, {"agent": "odd"}])
def test_odd_publish_replies_read_as_unknown(reply):
    fake = transport(PublishGrokBotAgent=reply, UnpublishGrokBotAgent=reply)
    assert p.publish_bot(fake, "bot") == p.PublishResult("unknown", None)
    assert p.unpublish_bot(fake, "bot") == p.PublishResult("unknown", None)


def test_refusal_message_is_passed_through_untouched():
    fake = transport(
        PublishGrokBotAgent=ConnectError(
            403, '{"code": "failed_precondition", "message": "Sharing is disabled."}'
        )
    )
    with pytest.raises(ConnectError):
        p.publish_bot(fake, "bot")
