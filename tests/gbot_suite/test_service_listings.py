import pytest

from gbot.service import listings
from gbot.service.transport import FakeTransport
from groken.client import ConnectError


def test_targets_with_teams():
    fake = FakeTransport(
        {
            "getSkillPublishTargets": {
                "teams": [
                    {"teamId": "t1", "name": "Alpha"},
                    {"id": "t2"},
                    {"id": 7, "name": "Numeric"},
                    "t3",
                    {"name": "No id"},
                    42.5,
                ],
                "unavailableReason": "ignored",
                "unavailableReasonKind": "kind",
            }
        }
    )
    found = listings.publish_targets(fake)
    assert found.teams == (
        listings.Target("t1", "Alpha"),
        listings.Target("t2", "t2"),
        listings.Target("7", "Numeric"),
        listings.Target("t3", "t3"),
    )
    assert found.unavailable_reason == "ignored"
    assert found.unavailable_kind == "kind"
    assert fake.calls == [("command", "getSkillPublishTargets", {})]


def test_targets_with_only_a_reason():
    fake = FakeTransport(
        {
            "getSkillPublishTargets": {
                "teams": [],
                "unavailableReason": "Join a team to publish skills.",
                "unavailableReasonKind": "no_team",
            }
        }
    )
    assert listings.publish_targets(fake) == listings.PublishTargets(
        (), "Join a team to publish skills.", "no_team"
    )


@pytest.mark.parametrize("reply", [None, {}, [], "text", 3, {"teams": "odd"}])
def test_targets_odd_replies(reply):
    found = listings.publish_targets(FakeTransport({"getSkillPublishTargets": reply}))
    assert found.teams == ()
    assert found.unavailable_reason == ""


@pytest.mark.parametrize(
    "reply,expected",
    [
        (None, listings.ListingResult(True)),
        ({}, listings.ListingResult(True)),
        ("", listings.ListingResult(True)),
        ("Published", listings.ListingResult(True, "", "Published")),
        ([1, 2], listings.ListingResult(True)),
        (7, listings.ListingResult(True)),
        ({"status": "published"}, listings.ListingResult(True, "published")),
        ({"status": 3, "state": "synced"}, listings.ListingResult(True, "synced")),
        ({"outcome": "done", "kind": "k"}, listings.ListingResult(True, "done")),
        ({"kind": "k", "message": "Hi"}, listings.ListingResult(True, "k", "Hi")),
        ({"status": ["x"], "extra": 1}, listings.ListingResult(True)),
        ({"error": "Nope"}, listings.ListingResult(False, "", "Nope")),
        (
            {"status": "failed", "error": {"message": "Bad"}},
            listings.ListingResult(False, "failed", "Bad"),
        ),
        (
            {"ok": False, "message": "Refused"},
            listings.ListingResult(False, "", "Refused"),
        ),
        ({"message": 5, "error": ""}, listings.ListingResult(True)),
    ],
)
def test_listing_result(reply, expected):
    fake = FakeTransport({"publishSkill": reply})
    assert listings.publish_skill(fake, "w") == expected


def test_error_object_message_is_read():
    fake = FakeTransport({"publishSkill": {"error": {"message": "Bad"}}})
    assert not listings.publish_skill(fake, "w").ok


def test_requests_send_team_only_when_given():
    fake = FakeTransport(
        {
            name: {"status": "ok"}
            for name in (
                "publishSkill",
                "resyncPublishedSkill",
                "unpublishSkill",
                "unpublishPluginListing",
            )
        }
    )
    listings.publish_skill(fake, "w1")
    listings.publish_skill(fake, "w1", "team")
    listings.resync_skill(fake, "w1")
    listings.unpublish_skill(fake, "w1")
    listings.unpublish_plugin_listing(fake, "9")
    listings.unpublish_plugin_listing(fake, "9", "team")
    assert fake.calls == [
        ("command", "publishSkill", {"workflowId": "w1"}),
        ("command", "publishSkill", {"workflowId": "w1", "teamId": "team"}),
        ("command", "resyncPublishedSkill", {"workflowId": "w1"}),
        ("command", "unpublishSkill", {"workflowId": "w1"}),
        ("command", "unpublishPluginListing", {"pluginId": "9"}),
        ("command", "unpublishPluginListing", {"pluginId": "9", "teamId": "team"}),
    ]


@pytest.mark.parametrize(
    "reply,expected",
    [
        (True, True),
        (False, False),
        (None, False),
        ("true", False),
        (1, False),
        ({}, False),
    ],
)
def test_has_restorable_copy(reply, expected):
    fake = FakeTransport({"hasRestorablePluginListingCopy": reply})
    assert listings.has_restorable_copy(fake, "9") is expected
    assert fake.calls == [
        ("command", "hasRestorablePluginListingCopy", {"pluginId": "9"})
    ]


def test_errors_propagate_for_callers_to_show():
    body = '{"error":"publishSkill is not supported for Temporal agents"}'
    fake = FakeTransport({"publishSkill": ConnectError(400, body)})
    with pytest.raises(ConnectError):
        listings.publish_skill(fake, "w")


def test_demo_replies_cover_every_command():
    assert set(listings.DEMO_COMMANDS) == set(listings.COMMANDS)
