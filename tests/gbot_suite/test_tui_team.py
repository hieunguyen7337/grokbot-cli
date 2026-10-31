import asyncio
from unittest.mock import Mock

from textual.widgets import Input, Static
from tui_snapshots import assert_snapshot

from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.panels.kit import FormPanel
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, commands, run
from gbot.tui.slash.team import (
    LinkPreviewPanel,
    MemoriesPanel,
    TeamBotPanel,
    TeamBotsPanel,
)
from groken.client import ConnectError

PENDING = "GROK_BOT_TEAM_REVIEW_ITEM_STATUS_PENDING"
APPROVED = "GROK_BOT_TEAM_REVIEW_ITEM_STATUS_APPROVED"
REFUSED = (
    '{"code": "permission_denied", "message": "Only a team manager can see this."}'
)

SUMMARY = {
    "summary": {
        "prose": "Handles billing questions for the team.",
        "generatedAtMs": "1800000000000",
        "memoryVersion": 3,
        "summaryModel": "demo",
    },
    "stale": False,
    "skills": [{"name": "triage"}],
    "learned": [
        {
            "factId": "f1",
            "text": "Prefers invoices in EUR",
            "learnedAtMs": "1800000000000",
        },
        {"factId": "f2", "text": "Works Tuesdays", "learnedAtMs": "1799913600000"},
    ],
    "memoryCount": 5,
}
ITEMS = {
    "items": [
        {
            "itemId": "item-1",
            "status": PENDING,
            "change": {
                "memory": {"action": "WRITE", "text": "Customer prefers email"},
                "summary": "Remember the email preference",
            },
        },
        {
            "itemId": "item-2",
            "status": PENDING,
            "change": {
                "skill": {"action": "ADD", "name": "refunds"},
                "summary": "Add a refunds skill",
            },
        },
    ]
}
APPROVED_ITEMS = {
    "items": [
        {
            "itemId": "item-0",
            "status": APPROVED,
            "change": {"memory": {"action": "FORGET"}, "summary": "Forget an old note"},
        }
    ]
}
MEMORIES = {
    "memories": [
        {
            "factId": "f1",
            "text": "Prefers invoices in EUR",
            "learnedAtMs": "1800000000000",
        },
        {"factId": "f2", "text": "Works Tuesdays", "learnedAtMs": "1799913600000"},
    ]
}


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def setup(app, pilot):
    await settle(app, pilot)
    screen = SessionScreen("demo-helper", bot_name="Helper")
    await app.push_screen(screen)
    await settle(app, pilot)
    return SlashContext(app, screen, screen.bot_id, None)


async def accept(app, pilot):
    await pilot.pause()
    assert isinstance(app.screen, ConfirmScreen)
    assert app.screen.focused is not None
    assert app.screen.focused.id == "cancel"
    await pilot.click("#confirm")
    await settle(app, pilot)


def calls(service, rpc):
    return [payload for _, name, payload in service.transport.calls if name == rpc]


def review_items(args):
    return ITEMS if args["statuses"] == [PENDING] else APPROVED_ITEMS


def keys(panel):
    return {action.key for action in panel.visible_actions()}


def shown(app) -> str:
    return str(app.screen.query_one("#panel-rows", Static).render())


def test_panel_snapshot_and_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["GetGrokBotTeamContextSummary"] = SUMMARY
        service.transport.rpcs["ListGrokBotTeamReviewItems"] = review_items
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            assert run(ctx, "/team") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, TeamBotPanel)
            assert panel.heading == "Helper in your team"
            labels = [row.label for row in panel.rows]
            assert labels[0] == "Summary"
            assert labels[1:3] == ["Prefers invoices in EUR", "Works Tuesdays"]
            assert labels[3:] == ["memory write", "skill add"]
            # Approve and reject apply only to a selected pending item.
            assert keys(panel) == {"h", "m", "g"}
            for _ in range(3):
                await pilot.press("down")
            assert keys(panel) == {"a", "r", "h", "m", "g"}
            await pilot.press("up")
            await pilot.press("up")
            await pilot.press("up")
            await assert_snapshot(app, pilot, "panel-team")

    asyncio.run(exercise())


def test_review_changes_confirm_and_cancel(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    notice = Mock()

    async def exercise():
        service = load_fake()
        service.transport.rpcs["GetGrokBotTeamContextSummary"] = SUMMARY
        service.transport.rpcs["ListGrokBotTeamReviewItems"] = review_items
        app = GbotApp(service, animate=False)
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/team")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, TeamBotPanel)
            for _ in range(3):
                await pilot.press("down")
            await pilot.press("a")
            assert isinstance(app.screen, ConfirmScreen)
            assert (
                isinstance(app.screen, ConfirmScreen)
                and app.screen.heading == "Approve this change to Helper?"
            )
            await pilot.press("enter")
            assert not calls(service, "ResolveGrokBotTeamReviewItem")
            await pilot.press("a")
            await accept(app, pilot)
            assert calls(service, "ResolveGrokBotTeamReviewItem")[-1] == {
                "agentId": "demo-helper",
                "itemId": "item-1",
                "decision": "GROK_BOT_TEAM_REVIEW_DECISION_APPROVE",
            }
            assert app.screen is panel
            await pilot.press("r")
            assert (
                isinstance(app.screen, ConfirmScreen)
                and app.screen.heading == "Reject this change to Helper?"
            )
            await accept(app, pilot)
            assert calls(service, "ResolveGrokBotTeamReviewItem")[-1]["decision"] == (
                "GROK_BOT_TEAM_REVIEW_DECISION_REJECT"
            )

    asyncio.run(exercise())


def test_history_toggle_and_refused_change(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    notice = Mock()

    async def exercise():
        service = load_fake()
        service.transport.rpcs["GetGrokBotTeamContextSummary"] = SUMMARY
        service.transport.rpcs["ListGrokBotTeamReviewItems"] = review_items
        app = GbotApp(service, animate=False)
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/team")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, TeamBotPanel)
            await pilot.press("h")
            await settle(app, pilot)
            assert panel.showing == "approved"
            assert calls(service, "ListGrokBotTeamReviewItems")[-1] == {
                "agentId": "demo-helper",
                "statuses": [APPROVED],
                "limit": 20,
            }
            assert [row.label for row in panel.rows] == ["memory forget"]
            assert keys(panel) == {"h", "m", "g"}
            assert "Pending" in [action.label for action in panel.visible_actions()]
            await pilot.press("h")
            await settle(app, pilot)
            assert panel.showing == "pending"
            service.transport.rpcs["ResolveGrokBotTeamReviewItem"] = ConnectError(
                403, REFUSED
            )
            panel.reject(panel.rows[3])
            await accept(app, pilot)
            assert notice.call_args.args[0] == "Only a team manager can see this."
            assert notice.call_args.kwargs == {"severity": "error", "markup": False}

    asyncio.run(exercise())


def test_refusals_are_plain_sentences(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        refused = ConnectError(403, REFUSED)
        service.transport.rpcs["GetGrokBotTeamContextSummary"] = refused
        service.transport.rpcs["ListGrokBotTeamReviewItems"] = refused
        service.transport.rpcs["ListGrokBotUserBotMemories"] = refused
        service.transport.rpcs["ListGrokBotTeamAgents"] = refused
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/team")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, TeamBotPanel)
            assert [(row.label, row.detail) for row in panel.rows] == [
                ("Summary", "Only a team manager can see this."),
                ("Review", "Only a team manager can see this."),
            ]
            assert keys(panel) == {"h", "m", "g"}
            await pilot.press("m")
            await settle(app, pilot)
            assert isinstance(app.screen, MemoriesPanel)
            assert app.screen.rows == []
            assert "Only a team manager can see this." in shown(app)
            await pilot.press("escape")
            run(ctx, "/team-bots")
            await settle(app, pilot)
            assert isinstance(app.screen, TeamBotsPanel)
            assert "Only a team manager can see this." in shown(app)
            assert "No team bots." not in shown(app)

    asyncio.run(exercise())


def test_team_bots_list_and_empty_state(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            assert run(ctx, "/team-bots") is None
            await settle(app, pilot)
            assert "No team bots." in shown(app)
            await pilot.press("escape")
            service.transport.rpcs["ListGrokBotTeamAgents"] = {
                "entries": [
                    {
                        "agent": {"agentId": "ops", "name": "Ops"},
                        "userTurns": 4,
                        "teammateTurns": 2,
                        "lastTurnAtMs": "86400000",
                    }
                ]
            }
            run(ctx, "/team-bots")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, TeamBotsPanel)
            assert panel.rows[0].label == "Ops"
            assert panel.rows[0].detail == "4 user turns · 2 teammate turns"
            assert panel.rows[0].status == "last turn 1970-01-02"
            assert calls(service, "ListGrokBotTeamAgents")[-1] == {}

    asyncio.run(exercise())


def test_memories_multi_select_and_promote(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    notice = Mock()

    async def exercise():
        service = load_fake()
        service.transport.rpcs["GetGrokBotTeamContextSummary"] = SUMMARY
        service.transport.rpcs["ListGrokBotTeamReviewItems"] = review_items
        service.transport.rpcs["ListGrokBotUserBotMemories"] = MEMORIES
        service.transport.rpcs["PromoteGrokBotMemoriesToTeam"] = {
            "created": [{"factId": "f2", "text": "Works Tuesdays"}],
            "alreadyInTeam": [{"factId": "f1", "text": "Prefers invoices in EUR"}],
            "keptPrivateCount": 0,
        }
        app = GbotApp(service, animate=False)
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/team")
            await settle(app, pilot)
            await pilot.press("m")
            await settle(app, pilot)
            memories = app.screen
            assert isinstance(memories, MemoriesPanel)
            assert memories.heading == "Helper memories"
            assert keys(memories) == {"space", "g"}
            await pilot.press("space")
            assert memories.marked == {"f1"}
            assert keys(memories) == {"space", "p", "g"}
            await pilot.press("p")
            assert (
                isinstance(app.screen, ConfirmScreen)
                and app.screen.heading == "Share 1 memories of Helper with the team?"
            )
            await pilot.press("enter")
            assert not calls(service, "PromoteGrokBotMemoriesToTeam")
            assert memories.marked == {"f1"}
            await pilot.press("down")
            await pilot.press("space")
            assert memories.marked == {"f1", "f2"}
            await pilot.press("p")
            assert (
                isinstance(app.screen, ConfirmScreen)
                and app.screen.heading == "Share 2 memories of Helper with the team?"
            )
            await accept(app, pilot)
            assert calls(service, "PromoteGrokBotMemoriesToTeam")[-1] == {
                "agentId": "demo-helper",
                "factIds": ["f1", "f2"],
            }
            assert notice.call_args.args[0] == (
                "Shared with the team: 1 created, 1 already in the team, "
                "0 kept private."
            )
            assert memories.marked == set()
            assert keys(memories) == {"space", "g"}

    asyncio.run(exercise())


def test_link_preview_panel_and_form(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["GetGrokBotTeamLinkPreview"] = {
            "setting": {"enabled": False}
        }
        service.transport.rpcs["SetGrokBotTeamLinkPreview"] = {
            "setting": {"enabled": True}
        }
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            assert run(ctx, "/team-link-preview 42") is None
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, LinkPreviewPanel)
            assert calls(service, "GetGrokBotTeamLinkPreview")[-1] == {"teamId": 42}
            assert ("Link previews", "off") in panel.detail.fields
            assert {a.key for a in panel.detail.actions} == {"t", "g"}
            await pilot.press("t")
            assert (
                isinstance(app.screen, ConfirmScreen)
                and app.screen.heading == "Turn link previews on for team 42?"
            )
            await pilot.press("enter")
            assert not calls(service, "SetGrokBotTeamLinkPreview")
            await pilot.press("t")
            await accept(app, pilot)
            assert calls(service, "SetGrokBotTeamLinkPreview")[-1] == {
                "teamId": 42,
                "enabled": True,
            }
            assert ("Link previews", "on") in panel.detail.fields
            await pilot.press("escape")
            assert run(ctx, "/team-link-preview") is None
            await settle(app, pilot)
            form = app.screen
            assert isinstance(form, FormPanel)
            form.query_one("#form-0", Input).value = "7"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert isinstance(app.screen, LinkPreviewPanel)
            assert app.screen.team_id == 7
            await pilot.press("escape")
            assert run(ctx, "/team-link-preview abc") == "Enter a team ID number."

    asyncio.run(exercise())


def test_read_only_refuses_every_change(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    notice = Mock()

    async def exercise():
        service = load_fake()
        service.transport.rpcs["GetGrokBotTeamContextSummary"] = SUMMARY
        service.transport.rpcs["ListGrokBotTeamReviewItems"] = review_items
        service.transport.rpcs["ListGrokBotUserBotMemories"] = MEMORIES
        service.transport.rpcs["GetGrokBotTeamLinkPreview"] = {
            "setting": {"enabled": False}
        }
        app = GbotApp(service, animate=False)
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            run(ctx, "/team")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, TeamBotPanel)
            item = panel.rows[3]
            app.read_only = True
            panel.approve(item)
            panel.reject(item)
            assert notice.call_args.args[0] == "Read-only mode"
            assert app.screen is panel
            panel.memories()
            await settle(app, pilot)
            memories = app.screen
            assert isinstance(memories, MemoriesPanel)
            memories.toggle(memories.rows[0])
            memories.promote()
            assert notice.call_args.args[0] == "Read-only mode"
            assert app.screen is memories
            await pilot.press("escape")
            run(ctx, "/team-link-preview 42")
            await settle(app, pilot)
            link = app.screen
            assert isinstance(link, LinkPreviewPanel)
            link.toggle()
            assert notice.call_args.args[0] == "Read-only mode"
            assert app.screen is link
            assert not calls(service, "ResolveGrokBotTeamReviewItem")
            assert not calls(service, "PromoteGrokBotMemoriesToTeam")
            assert not calls(service, "SetGrokBotTeamLinkPreview")

    asyncio.run(exercise())


def test_command_scopes():
    specs = {command.name: command for command in commands()}
    assert specs["team"].scope == "session" and specs["team"].needs_bot
    assert specs["team-bots"].scope == "any"
    assert specs["team-link-preview"].scope == "any"
