import json

import pytest

from gbot.protocol import USED_COMMANDS
from gbot.service import cloud_agents as service
from gbot.service.fake import load_fake
from gbot.service.transport import FakeTransport
from groken.client import ConnectError

SECRET = "sk-test-value-5f1e"


def sent(fake, name):
    return [args for _, called, args in fake.calls if called == name]


def test_commands_are_declared_and_demo_replies_load():
    assert len(service.COMMANDS) == 12
    assert {key: USED_COMMANDS[key] for key in service.COMMANDS} == service.COMMANDS
    assert "createCloudAgentAppsGateTicket" not in USED_COMMANDS
    fake = load_fake().transport
    state = service.apps(fake)
    assert state.kind == "on" and [app.slug for app in state.apps] == [
        "landing",
        "dashboard",
    ]


def test_info_shapes_and_null():
    fake = FakeTransport(
        {
            "getCloudAgentInfo": {
                "bcId": "bc-1",
                "status": 7,
                "state": "RUNNING",
                "name": "Site",
                "branch": "main",
                "repository": "https://user:token@github.com/o/r.git?x=1#y",
                "createdAtMs": "1800000000000",
                "files": [{}, {}],
                "artifacts": {},
                "zeta": 1,
                "alpha": None,
            }
        }
    )
    found = service.info(fake, "bc-1", include_files=True)
    assert sent(fake, "getCloudAgentInfo") == [
        {"bcId": "bc-1", "includeFiles": True, "includeArtifacts": False}
    ]
    assert found == service.CloudAgentInfo(
        "bc-1", "RUNNING", "Site", "main", "github.com/o/r.git", 1800000000000, 2, 0,
        ("alpha", "zeta"),
    )  # fmt: skip
    assert found is not None
    assert ("Created", "2027-01-15 08:00 UTC") in found.fields
    fake.commands["getCloudAgentInfo"] = {"title": "T", "createdAt": 5, "extra": []}
    found = service.info(fake, "bc-2")
    assert found is not None
    assert (found.bc_id, found.title, found.created_at, found.extra) == (
        "bc-2",
        "T",
        5,
        ("extra",),
    )
    assert (found.status, found.repo, found.file_count) == ("", "", 0)
    for reply in (None, [], "odd"):
        fake.commands["getCloudAgentInfo"] = reply
        assert service.info(fake, "bc-3") is None
    assert service.NOT_FOUND == "No cloud agent with that id."


@pytest.mark.parametrize(
    "reply,expected",
    [
        (
            {"messages": [{"role": "user", "text": "hi"}, {"type": "bot", "content": "yo"}]},
            [("user", "hi"), ("bot", "yo")],
        ),
        (
            {"conversation": [{"role": "assistant", "content": [{"text": "a"}, "b", 3, {"x": 1}]}]},
            [("assistant", "ab")],
        ),
        ({"turns": [{"text": "see https://x.invalid/t?k=1 now"}, "odd"]}, [("unknown", "see [link hidden] now")]),
        ({"conversation": {"messages": [{"role": "user", "text": "nested"}]}}, []),
        ({"messages": {"x": 1}, "turns": [{"text": "hi"}]}, [("unknown", "hi")]),
        ({"turns": "odd", "messages": None}, []),
        ({}, []),
        (None, []),
    ],
)  # fmt: skip
def test_conversation_shapes(reply, expected):
    fake = FakeTransport({"getCloudAgentConversation": reply})
    messages = service.conversation(fake, "bc-1")
    assert [(m.role, m.text) for m in messages] == expected
    assert sent(fake, "getCloudAgentConversation") == [{"bcId": "bc-1"}]


def test_stop_payload():
    fake = FakeTransport({"stopCloudAgent": None})
    assert service.stop(fake, "bc-1") is None
    assert fake.calls == [("command", "stopCloudAgent", {"bcId": "bc-1"})]


@pytest.mark.parametrize(
    "reply,kind,count,sentence",
    [
        ({"kind": "off"}, "off", 0, "Cloud-agent apps are off for this account."),
        ({"kind": "OFF", "apps": [{"slug": "x"}]}, "off", 1, service.APPS_OFF),
        ({"kind": "on", "apps": [{"slug": "a"}]}, "on", 1, ""),
        ({"kind": "on"}, "on", 0, "No published apps."),
        ({"apps": []}, "on", 0, "No published apps."),
        ({"publishedApps": [{}, "odd"]}, "on", 1, ""),
        ({"kind": "gated"}, "unknown", 0, service.APPS_UNKNOWN),
        ({}, "unknown", 0, service.APPS_UNKNOWN),
        ([], "unknown", 0, service.APPS_UNKNOWN),
    ],
)
def test_app_states(reply, kind, count, sentence):
    fake = FakeTransport({"listCloudAgentPublishedApps": reply})
    state = service.apps(fake)
    assert (state.kind, len(state.apps), state.sentence) == (kind, count, sentence)
    assert fake.calls == [("command", "listCloudAgentPublishedApps", {})]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("GROK_BOT_PUBLISH_VISIBILITY_PUBLIC", "public"),
        ("CLOUD_AGENT_APP_VISIBILITY_TEAM", "team"),
        ("private", "private"),
        ("Team", "team"),
        (1, "private"),
        (3, "public"),
        ("2", "team"),
        (9, "unknown"),
        ("secret", "unknown"),
        (None, "unknown"),
        (True, "unknown"),
    ],
)
def test_visibility_enum_forms(value, expected):
    fake = FakeTransport(
        {
            "listCloudAgentPublishedApps": {
                "apps": [
                    {
                        "bcId": "bc",
                        "slug": "s",
                        "apex": "a",
                        "visibility": value,
                        "url": "https://s.a/?ticket=t",
                    }
                ]
            }
        }
    )
    app = service.apps(fake).apps[0]
    assert app.visibility == expected
    assert "ticket" not in repr(app)


def test_update_and_unpublish_payloads_and_results():
    fake = FakeTransport(
        {
            "updateCloudAgentPublishApp": {"state": "UPDATED", "url": "https://x"},
            "unpublishCloudAgentPublishApp": {
                "ok": False,
                "error": {"message": "Not yours: https://a.invalid/x"},
            },
        }
    )
    result = service.update_app(
        fake,
        "bc",
        "s",
        "a",
        "GROK_BOT_PUBLISH_VISIBILITY_TEAM",
        mute_redeploy_prompts=True,
    )
    assert result == service.AppResult(True, "updated", "")
    assert sent(fake, "updateCloudAgentPublishApp") == [
        {
            "bcId": "bc",
            "slug": "s",
            "apex": "a",
            "visibility": "team",
            "muteRedeployPrompts": True,
            "requireConfirmationForUpdates": False,
        }
    ]
    result = service.unpublish_app(fake, "bc", "s", "a")
    assert result == service.AppResult(False, "error", "Not yours: [link hidden]")
    assert sent(fake, "unpublishCloudAgentPublishApp") == [
        {"bcId": "bc", "slug": "s", "apex": "a"}
    ]
    with pytest.raises(ValueError, match="Visibility"):
        service.update_app(fake, "bc", "s", "a", "everyone")
    assert len(sent(fake, "updateCloudAgentPublishApp")) == 1
    fake.commands["unpublishCloudAgentPublishApp"] = None
    assert service.unpublish_app(fake, "bc", "s", "a") == service.AppResult(
        True, "ok", ""
    )


@pytest.mark.parametrize(
    "reply,names",
    [
        ({"secrets": [{"name": "A", "value": SECRET}, {"name": "B"}, {"value": SECRET}]}, ("A", "B")),
        ({"secrets": ["A", "A", 3]}, ("A",)),
        ({"secrets": {"A": SECRET, "B": None}}, ("A", "B")),
        ({"names": ["A", "B"]}, ("A", "B")),
        ({"A": SECRET, "B": SECRET}, ("A", "B")),
        ({"secrets": None}, ()),
        ({"count": 2, "nested": {"A": SECRET}}, ()),
        ({"status": "ok"}, ()),
        ({"status": SECRET, "DEMO_KEY": SECRET}, ("DEMO_KEY",)),
        ({"secrets": [{"name": "https://x.invalid/?ticket=t"}]}, ("[link hidden]",)),
        ({}, ()),
        (None, ()),
    ],
)  # fmt: skip
def test_secret_names_drop_values(reply, names):
    fake = FakeTransport({"getCloudAgentAppSecrets": reply})
    found = service.app_secret_names(fake, "bc", "/app")
    assert found == names
    assert SECRET not in repr(found)
    assert sent(fake, "getCloudAgentAppSecrets") == [
        {"bcId": "bc", "projectDir": "/app"}
    ]


def test_set_then_tell_with_refusals():
    fake = FakeTransport(
        {
            "setCloudAgentAppSecrets": {
                "refused": [
                    {
                        "name": "B",
                        "kind": "not_owned",
                        "message": "Owned by another app",
                        "permanent": True,
                    },
                    {
                        "name": "C",
                        "kind": "GROK_BOT_APP_SECRET_REFUSAL_KIND_HOST_ERROR",
                    },
                    {"name": "D", "kind": 99},
                ],
                "applyNeeded": True,
            },
            "tellCloudAgentAppSecretsSet": {},
        }
    )
    result = service.set_app_secrets(
        fake,
        "bc",
        "/app",
        {"A": SECRET, "B": "value-b", "C": "value-c", "D": "value-d"},
    )
    assert result.saved == ("A",)
    assert [(r.name, r.kind, r.permanent) for r in result.refused] == [
        ("B", "not_owned", True),
        ("C", "host_error", False),
        ("D", "unknown", False),
    ]
    assert result.apply_needed
    assert SECRET not in repr(result)
    service.tell_secrets_set(
        fake, "bc", "/app", result.saved, result.refused[:1], result.apply_needed
    )
    set_call, tell_call = fake.calls
    assert set_call[1] == "setCloudAgentAppSecrets"
    assert set_call[2]["bcId"] == "bc" and set_call[2]["projectDir"] == "/app"
    assert tell_call == (
        "command",
        "tellCloudAgentAppSecretsSet",
        {
            "bcId": "bc",
            "projectDir": "/app",
            "names": ["A"],
            "refused": [
                {
                    "name": "B",
                    "kind": "not_owned",
                    "message": "Owned by another app",
                    "permanent": True,
                }
            ],
            "applyNeeded": True,
        },
    )
    fake.commands["setCloudAgentAppSecrets"] = {"saved": [{"name": "A"}, "X"]}
    assert service.set_app_secrets(fake, "bc", "/app", {"A": SECRET}) == (
        service.SetResult(("A",), (), False)
    )


def test_set_payload_and_redaction():
    seen = []

    def record(args):
        seen.append(json.loads(json.dumps(args)))
        return {}

    fake = FakeTransport({"setCloudAgentAppSecrets": record})
    service.set_app_secrets(fake, "bc", "/app", {"A": SECRET})
    assert seen == [
        {
            "bcId": "bc",
            "projectDir": "/app",
            "secrets": [{"name": "A", "value": SECRET}],
        }
    ]
    # The transport keeps the request it was given; the service does not edit it after the call.
    assert fake.calls[0][2]["secrets"] == [{"name": "A", "value": SECRET}]
    for error in (
        ConnectError(500, "boom " + SECRET),
        RuntimeError("echo " + SECRET),
        ConnectError(
            403, json.dumps({"code": "permission_denied", "message": "No " + SECRET})
        ),
    ):
        fake.commands["setCloudAgentAppSecrets"] = error
        with pytest.raises(ValueError) as caught:
            service.set_app_secrets(fake, "bc", "/app", {"A": SECRET})
        assert SECRET not in str(caught.value)
        assert caught.value.__cause__ is None
    assert str(caught.value) == "No [redacted]"


def test_proposals_confirm_and_dismiss():
    fake = FakeTransport(
        {
            "getCloudAgentPublishProposals": {
                "items": [
                    {"id": "p1", "slug": "s", "visibility": "GROK_BOT_X_PUBLIC", "title": "T"},
                    {"proposalId": "p2", "visibility": 2, "summary": "at https://x.invalid"},
                    "odd",
                ]
            },
            "confirmCloudAgentPublishProposal": {"status": "published"},
            "dismissCloudAgentPublishProposal": {},
        }
    )  # fmt: skip
    rows = service.proposals(fake, "bc")
    assert rows == (
        service.Proposal("p1", "s", "public", "T"),
        service.Proposal("p2", "", "team", "at [link hidden]"),
    )
    fake.commands["getCloudAgentPublishProposals"] = {}
    assert service.proposals(fake, "bc") == ()
    result = service.confirm_proposal(fake, "gw", "bc", "p1", "s", "public", True)
    assert result.state == "published"
    service.dismiss_proposal(fake, "bc", "p1")
    service.dismiss_proposal(fake, "bc", "p1", bot_id="gw")
    assert sent(fake, "getCloudAgentPublishProposals") == [{"bcId": "bc"}] * 2
    assert sent(fake, "confirmCloudAgentPublishProposal") == [
        {
            "agentId": "gw",
            "bcId": "bc",
            "proposalId": "p1",
            "slug": "s",
            "visibility": "public",
            "requireConfirmationForUpdates": True,
        }
    ]
    assert sent(fake, "dismissCloudAgentPublishProposal") == [
        {"bcId": "bc", "proposalId": "p1"},
        {"bcId": "bc", "proposalId": "p1", "agentId": "gw"},
    ]


@pytest.mark.parametrize(
    "reply,ok",
    [
        ({"state": "FAILED", "message": "Slug taken"}, False),
        ({"state": "GROK_BOT_CLOUD_APP_UPDATE_STATE_REJECTED"}, False),
        ({"ok": True, "state": "error"}, False),
        ({"ok": True, "state": "UPDATED"}, True),
        ({"state": "updated"}, True),
        ({"error": {"message": "No"}}, False),
    ],
)  # fmt: skip
def test_failed_state_is_not_success(reply, ok):
    fake = FakeTransport({"updateCloudAgentPublishApp": reply})
    assert service.update_app(fake, "bc", "s", "a", "team").ok is ok


def test_created_at_out_of_range_is_unknown():
    fake = FakeTransport({"getCloudAgentInfo": {"bcId": "b", "createdAt": -(10**14)}})
    found = service.info(fake, "b")
    assert found is not None
    assert ("Created", "unknown") in found.fields


def test_app_identity_fields_hide_links():
    reply = {
        "kind": "on",
        "apps": [
            {"slug": "https://x.invalid/?ticket=t", "apex": "a", "visibility": "team"}
        ],
    }
    fake = FakeTransport({"listCloudAgentPublishedApps": reply})
    app = service.apps(fake).apps[0]
    assert app.slug == "[link hidden]"
    assert "ticket" not in repr(app)
