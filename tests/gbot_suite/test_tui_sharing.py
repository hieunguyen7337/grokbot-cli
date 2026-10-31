import asyncio
import json
from typing import Any
from unittest.mock import Mock

import pytest
from textual.widgets import Input, Static
from tui_snapshots import assert_snapshot

from gbot.service import sharing
from gbot.service.fake import load_fake
from gbot.tui.app import GbotApp
from gbot.tui.panels.kit import FormPanel, ListPanel
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.slash import SlashContext, commands, run
from gbot.tui.slash import sharing as slash
from gbot.tui.slash.sharing import InvitePanel, SharePanel
from groken.client import ConnectError

ROLE = "GROK_BOT_ACCESS_ROLE_"
CODE = "secret-token-123"
LINK = "grokbot://v1/agent-invite?id=bot-1&token=" + CODE
URL = "https://example.invalid/invite?token=" + CODE


def refusal(code, message):
    return ConnectError(403, json.dumps({"code": code, "message": message}))


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


async def open_panel(app, pilot, ctx):
    assert run(ctx, "/share") is None
    await settle(app, pilot)
    panel = app.screen
    assert isinstance(panel, SharePanel)
    return panel


async def accept(app, pilot):
    await pilot.pause()
    assert isinstance(app.screen, ConfirmScreen)
    assert app.screen.focused is not None
    assert app.screen.focused.id == "cancel"
    await pilot.click("#confirm")
    await settle(app, pilot)


async def cancel(app, pilot, question):
    await pilot.pause()
    assert isinstance(app.screen, ConfirmScreen)
    assert app.screen.heading == question
    assert app.screen.focused is not None and app.screen.focused.id == "cancel"
    await pilot.press("enter")
    await settle(app, pilot)


def calls(service, rpc) -> list[dict[str, Any]]:
    return [payload for _, name, payload in service.transport.calls if name == rpc]


def labels(panel):
    return [row.label for row in panel.rows]


def keys(panel):
    return {key for key, _ in panel.applicable()}


def pick(app, index):
    """Move the selection of the list on top of the screen stack."""
    screen = app.screen
    assert isinstance(screen, ListPanel)
    screen.index = index


def select(panel, key):
    panel.index = next(i for i, row in enumerate(panel.rows) if row.key == key)


def footer(panel):
    return str(panel.query_one(".panel-footer", Static).render())


ACCESS = {
    "creatorUserId": 1,
    "viewerUserId": 1,
    "state": {
        "availableRoles": [ROLE + "USER", ROLE + "MANAGER"],
        "expectedStateToken": "tok",
        "principals": [
            {"team": {}, "role": ROLE + "USER"},
            {"userId": 2, "role": ROLE + "USER"},
            {"groupId": "7", "role": ROLE + "MANAGER"},
        ],
        "teamRowOn": True,
        "teamRowOffAllowed": True,
    },
    "personalBotPeople": [
        {"userId": 1, "name": "Sam Rivera"},
        {"userId": 2, "name": "Avery Chen"},
        {"userId": 3, "name": "Jordan Lee"},
        {"userId": 4, "name": "Riley Park"},
    ],
    "botTeamDirectory": {
        "groups": [
            {"groupId": "7", "name": "Design", "memberCount": 4},
            {"groupId": "8", "name": "Ops", "memberCount": 2},
        ]
    },
    "crossTierDirectory": {"organization": {"name": "Example Org"}},
}
OFF = {
    **ACCESS,
    "state": {
        **ACCESS["state"],
        "teamRowOn": False,
        "principals": ACCESS["state"]["principals"][1:],
    },
}


def test_panel_snapshot_rows_and_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            specs = {c.name: c for c in commands()}
            assert specs["share"].scope == "session" and specs["share"].needs_bot
            assert specs["invite"].scope == "any" and not specs["invite"].needs_bot
            panel = await open_panel(app, pilot, ctx)
            assert panel.heading == "Share Helper"
            assert [row.key for row in panel.rows] == [
                "owner",
                "p:user:2",
                "p:group:7",
                "team",
                "link",
                "m:3",
                "i:invitee@example.invalid",
                "cap",
            ]
            assert labels(panel)[:4] == [
                "Sam Rivera (you)",
                "Avery Chen",
                "Design",
                "Team row",
            ]
            assert [r.status for r in panel.rows[:4]] == [
                "owner",
                "user",
                "manager",
                "on · user",
            ]
            assert panel.rows[2].detail == "group · 4 members"
            assert panel.rows[4].status == "allowed"
            assert panel.rows[5].label == "Jordan Lee"
            await assert_snapshot(app, pilot, "panel-share")

    asyncio.run(exercise())


def test_actions_appear_only_when_they_apply(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["GetGrokBotAgentAccess"] = ACCESS
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            panel = await open_panel(app, pilot, ctx)
            everything = {"a", "t", "v", "p", "c", "i", "m", "g"}
            select(panel, "owner")
            assert keys(panel) == everything
            select(panel, "p:user:2")
            assert keys(panel) == everything | {"r", "x"}
            select(panel, "team")
            assert keys(panel) == everything | {"r"}
            select(panel, "i:invitee@example.invalid")
            assert keys(panel) == everything | {"e"}
            panel._draw()
            assert "e revoke invite" in footer(panel) and "x remove" not in footer(
                panel
            )
            # The team row off: the key now turns it on, and nothing about it is removable.
            service.transport.rpcs["GetGrokBotAgentAccess"] = OFF
            await pilot.press("g")
            await settle(app, pilot)
            select(panel, "team")
            assert dict(panel.applicable())["t"] == "team row on"
            assert "r" not in keys(panel)
            # Only one role to pick, a team row that cannot go off, nobody to add or manage.
            service.transport.rpcs["GetGrokBotAgentAccess"] = {
                "state": {
                    "availableRoles": [ROLE + "USER"],
                    "principals": [{"team": {}, "role": ROLE + "USER"}],
                    "teamRowOn": True,
                }
            }
            service.transport.rpcs["ListGrokBotAgentManagers"] = {}
            await pilot.press("g")
            await settle(app, pilot)
            assert keys(panel) == {"v", "p", "c", "i", "g"}
            # Keys that do not apply do nothing.
            before = len(service.transport.calls)
            for key in ("x", "r", "e", "m", "t"):
                await pilot.press(key)
            assert isinstance(app.screen, SharePanel)
            assert len(service.transport.calls) == before

    asyncio.run(exercise())


def test_a_refused_part_is_one_sentence_and_hides_its_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["ListGrokBotAgentAccessInvites"] = refusal(
            "failed_precondition", "Invites need a team."
        )
        service.transport.rpcs["ListGrokBotAgentManagers"] = refusal(
            "permission_denied", "Not a manager."
        )
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            panel = await open_panel(app, pilot, ctx)
            assert "Invites: Invites need a team." in labels(panel)
            assert "Managers: Not a manager." in labels(panel)
            assert "Sam Rivera (you)" in labels(panel)
            assert keys(panel).isdisjoint({"i", "e", "m"})
            service.transport.rpcs["GetGrokBotAgentAccess"] = refusal(
                "permission_denied", "Only managers can see this."
            )
            await pilot.press("g")
            await settle(app, pilot)
            assert labels(panel)[0] == "Access: Only managers can see this."
            assert keys(panel).isdisjoint({"a", "r", "x", "t"})
            assert isinstance(panel.query_one("#panel-rows", Static), Static)
            # A failure that is not a refusal stays an error with the retry key.
            service.transport.rpcs["GetGrokBotAgentLinkAccess"] = ConnectError(
                500, "down"
            )
            await pilot.press("g")
            await settle(app, pilot)
            assert "500" in panel.error and "r retry" in str(
                panel.query_one("#panel-rows", Static).render()
            )

    asyncio.run(exercise())


def test_changes_confirm_cancel_first_then_send_the_whole_list(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["GetGrokBotAgentAccess"] = ACCESS
        service.transport.rpcs["UpdateGrokBotAgentAccess"] = ACCESS
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            panel = await open_panel(app, pilot, ctx)
            # Remove a row: cancel sends nothing, confirm sends the rest with the token.
            select(panel, "p:user:2")
            await pilot.press("x")
            await cancel(app, pilot, "Remove Avery Chen from Helper?")
            assert calls(service, "UpdateGrokBotAgentAccess") == []
            await pilot.press("x")
            await accept(app, pilot)
            (payload,) = calls(service, "UpdateGrokBotAgentAccess")
            assert payload["update"] == {
                "principals": [
                    {"team": {}, "role": ROLE + "USER"},
                    {"groupId": "7", "role": ROLE + "MANAGER"},
                ],
                "expectedStateToken": "tok",
                "listsCrossTierPrincipals": True,
            }
            assert notice.call_args.args[0] == "Updated access to Helper."
            assert notice.call_args.kwargs == {
                "severity": "information",
                "markup": False,
            }
            # Change a role: the one other role is applied after a confirm.
            select(panel, "p:group:7")
            await pilot.press("r")
            await cancel(app, pilot, "Change Design to user on Helper?")
            await pilot.press("r")
            await accept(app, pilot)
            assert calls(service, "UpdateGrokBotAgentAccess")[-1]["update"][
                "principals"
            ][2] == {
                "groupId": "7",
                "role": ROLE + "USER",
            }
            # Team row: off, with the confirm naming the bot.
            await pilot.press("t")
            await cancel(app, pilot, "Turn off the team row for Helper?")
            await pilot.press("t")
            await accept(app, pilot)
            assert [
                next(iter(r))
                for r in calls(service, "UpdateGrokBotAgentAccess")[-1]["update"][
                    "principals"
                ]
            ] == [
                "userId",
                "groupId",
            ]
            # Team row on, then the team row as manager asks the stronger question.
            service.transport.rpcs["GetGrokBotAgentAccess"] = OFF
            await pilot.press("g")
            await settle(app, pilot)
            await pilot.press("t")
            await cancel(app, pilot, "Turn on the team row for Helper?")
            service.transport.rpcs["GetGrokBotAgentAccess"] = ACCESS
            await pilot.press("g")
            await settle(app, pilot)
            select(panel, "team")
            await pilot.press("r")
            await cancel(app, pilot, "Make everyone in the team a manager of Helper?")
            await pilot.press("r")
            await accept(app, pilot)
            assert calls(service, "UpdateGrokBotAgentAccess")[-1]["update"][
                "principals"
            ][0] == {
                "team": {},
                "role": ROLE + "MANAGER",
            }

    asyncio.run(exercise())


def test_add_picks_from_the_directory_then_a_role(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["GetGrokBotAgentAccess"] = OFF
        service.transport.rpcs["UpdateGrokBotAgentAccess"] = OFF
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            panel = await open_panel(app, pilot, ctx)
            await pilot.press("a")
            await settle(app, pilot)
            picker = app.screen
            assert isinstance(picker, ListPanel) and picker.heading == "Add to Helper"
            # The team, the organization, people who do not have it yet, and groups.
            assert [(r.key, r.label) for r in picker.rows] == [
                ("team", "Everyone in the team"),
                ("organization", "Everyone in Example Org"),
                ("user:3", "Jordan Lee"),
                ("user:4", "Riley Park"),
                ("group:8", "Ops"),
            ]
            pick(app, 2)
            await pilot.press("enter")
            await settle(app, pilot)
            roles = app.screen
            assert (
                isinstance(roles, ListPanel) and roles.heading == "Role for Jordan Lee"
            )
            assert [r.key for r in roles.rows] == ["user", "manager"]
            pick(app, 1)
            await pilot.press("enter")
            await cancel(app, pilot, "Make Jordan Lee a manager of Helper?")
            assert calls(service, "UpdateGrokBotAgentAccess") == []
            assert app.screen is panel
            # The team as manager asks the team question.
            await pilot.press("a")
            await settle(app, pilot)
            await pilot.press("enter")
            await settle(app, pilot)
            pick(app, 1)
            await pilot.press("enter")
            await cancel(app, pilot, "Make everyone in the team a manager of Helper?")
            # A group as user: confirmed and sent with the existing rows.
            await pilot.press("a")
            await settle(app, pilot)
            pick(app, 4)
            await pilot.press("enter")
            await settle(app, pilot)
            await pilot.press("enter")
            await accept(app, pilot)
            assert calls(service, "UpdateGrokBotAgentAccess")[-1]["update"][
                "principals"
            ] == [
                {"userId": 2, "role": ROLE + "USER"},
                {"groupId": "7", "role": ROLE + "MANAGER"},
                {"groupId": "8", "role": ROLE + "USER"},
            ]

    asyncio.run(exercise())


def test_team_visible_clone_and_the_refusal_notices(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            panel = await open_panel(app, pilot, ctx)
            await pilot.press("v")
            await cancel(app, pilot, "Make Helper visible to your team?")
            assert calls(service, "SetGrokBotAgentVisibility") == []
            await pilot.press("v")
            await accept(app, pilot)
            assert calls(service, "SetGrokBotAgentVisibility") == [
                {
                    "agentId": "demo-helper",
                    "visibility": "GROK_BOT_AGENT_VISIBILITY_TEAM",
                }
            ]
            assert notice.call_args.args[0] == sharing.sentence("no_team")
            assert notice.call_args.kwargs == {"severity": "warning", "markup": False}
            service.transport.rpcs["SetGrokBotAgentVisibility"] = {"outcome": "UPDATED"}
            await pilot.press("v")
            await accept(app, pilot)
            assert notice.call_args.args[0] == sharing.sentence("updated")
            assert notice.call_args.kwargs["severity"] == "information"
            await pilot.press("c")
            await cancel(app, pilot, "Clone Helper to your team?")
            await pilot.press("c")
            await accept(app, pilot)
            assert calls(service, "CloneGrokBotAgentToTeam") == [
                {"agentId": "demo-helper"}
            ]
            assert notice.call_args.args[0] == sharing.sentence("no_team")
            # A server refusal is a plain warning notice with the server's own words.
            service.transport.rpcs["CloneGrokBotAgentToTeam"] = refusal(
                "failed_precondition", "Join a team first.\x1b[2J[bold]"
            )
            await pilot.press("c")
            await accept(app, pilot)
            assert "Join a team first." in notice.call_args.args[0]
            assert "\x1b" not in notice.call_args.args[0]
            assert notice.call_args.kwargs == {"severity": "warning", "markup": False}
            assert app.screen is panel
            # Anything else is an error notice.
            service.transport.rpcs["CloneGrokBotAgentToTeam"] = ConnectError(
                500, "boom"
            )
            await pilot.press("c")
            await accept(app, pilot)
            assert notice.call_args.kwargs == {"severity": "error", "markup": False}

    asyncio.run(exercise())


def test_invite_and_revoke_by_email(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["CreateGrokBotAgentAccessInvite"] = {
            "invite": {"email": "new@example.invalid"},
            "inviteCreated": True,
            "inviteUrl": URL,
            "inviteEmailSent": True,
            "capUsage": {"used": 2, "limit": 10},
        }
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            panel = await open_panel(app, pilot, ctx)
            await pilot.press("i")
            await settle(app, pilot)
            form = app.screen
            assert isinstance(form, FormPanel) and form.heading == "Invite to Helper"
            form.query_one("#form-0", Input).value = "not-an-email"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert app.screen is form
            assert "valid email" in str(
                form.query_one("#form-error-0", Static).render()
            )
            form.query_one("#form-0", Input).value = "new@example.invalid"
            await pilot.press("ctrl+s")
            await cancel(app, pilot, "Invite new@example.invalid to Helper?")
            assert calls(service, "CreateGrokBotAgentAccessInvite") == []
            await pilot.press("ctrl+s")
            await accept(app, pilot)
            assert calls(service, "CreateGrokBotAgentAccessInvite") == [
                {
                    "agentId": "demo-helper",
                    "email": "new@example.invalid",
                    "sendEmail": True,
                }
            ]
            assert app.screen is panel
            assert notice.call_args.args[0] == (
                "Invited new@example.invalid: email sent. 2 of 10 invites used."
            )
            assert URL not in str(notice.call_args_list)
            assert CODE not in app.export_screenshot()
            # Revoke the selected invite.
            select(panel, "i:invitee@example.invalid")
            await pilot.press("e")
            await cancel(
                app, pilot, "Revoke the invite for invitee@example.invalid to Helper?"
            )
            assert calls(service, "RevokeGrokBotAgentAccessInvite") == []
            await pilot.press("e")
            await accept(app, pilot)
            assert calls(service, "RevokeGrokBotAgentAccessInvite") == [
                {"agentId": "demo-helper", "email": "invitee@example.invalid"}
            ]
            assert notice.call_args.args[0].startswith(
                "Revoked 1 invite for invitee@example.invalid"
            )
            # A refusal in the form is a warning notice, and the form stays.
            service.transport.rpcs["CreateGrokBotAgentAccessInvite"] = refusal(
                "failed_precondition", "Invites need a team."
            )
            await pilot.press("i")
            await settle(app, pilot)
            app.screen.query_one("#form-0", Input).value = "other@example.invalid"
            await pilot.press("ctrl+s")
            await accept(app, pilot)
            assert notice.call_args.args[0] == "Invites need a team."
            assert notice.call_args.kwargs == {"severity": "warning", "markup": False}
            assert isinstance(app.screen, FormPanel)

    asyncio.run(exercise())


def test_managers_are_picked_from_people(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["GetGrokBotAgentAccess"] = ACCESS
        service.transport.rpcs["ListGrokBotAgentManagers"] = {"managerUserIds": [3, 9]}
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            panel = await open_panel(app, pilot, ctx)
            assert "User #9" in labels(panel)
            await pilot.press("m")
            await settle(app, pilot)
            picker = app.screen
            assert (
                isinstance(picker, ListPanel) and picker.heading == "Managers of Helper"
            )
            assert [(r.key, r.label, r.status) for r in picker.rows] == [
                ("2", "Avery Chen", ""),
                ("3", "Jordan Lee", "manager"),
                ("4", "Riley Park", ""),
                ("9", "User #9", "manager"),
            ]
            pick(app, 0)
            await pilot.press("enter")
            await cancel(app, pilot, "Make Avery Chen a manager of Helper?")
            await pilot.press("m")
            await settle(app, pilot)
            pick(app, 0)
            await pilot.press("enter")
            await accept(app, pilot)
            assert calls(service, "AddGrokBotAgentManager") == [
                {"agentId": "demo-helper", "userId": 2}
            ]
            await pilot.press("m")
            await settle(app, pilot)
            pick(app, 1)
            await pilot.press("enter")
            await cancel(app, pilot, "Remove Jordan Lee as a manager of Helper?")
            await pilot.press("m")
            await settle(app, pilot)
            pick(app, 1)
            await pilot.press("enter")
            await accept(app, pilot)
            assert calls(service, "RemoveGrokBotAgentManager") == [
                {"agentId": "demo-helper", "userId": 3}
            ]

    asyncio.run(exercise())


async def until(app, pilot, condition, limit=400):
    """Let the app run, with no sleeping, until a condition holds."""
    for _ in range(limit):
        if condition():
            return
        await settle(app, pilot)
    raise AssertionError("the app never reached the expected state")


def drive_polling(monkeypatch):
    """Make the poll timers short and record what the panel asked `next_poll_delay` for."""
    asked = []

    def delay(previous):
        asked.append(previous)
        return 0.001

    monkeypatch.setattr(slash.service, "next_poll_delay", delay)
    return asked


def scripted(replies):
    it = iter(replies)

    def reply(args):
        value = next(it)
        if isinstance(value, Exception):
            raise value
        return value

    return reply


def test_in_place_share_polls_with_timers_and_stops_on_done(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        asked = drive_polling(monkeypatch)
        service.transport.rpcs["ShareGrokBotAgentInPlace"] = {"outcome": "STARTED"}
        service.transport.rpcs["GetGrokBotAgentInPlaceShareStatus"] = scripted(
            [
                {"state": "RUNNING", "step": "CHECK"},
                {"state": "RUNNING", "step": "GRANTS"},
                {"state": "DONE", "shared": True},
            ]
        )
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            panel = await open_panel(app, pilot, ctx)
            await pilot.press("p")
            await cancel(app, pilot, "Share Helper with your team in place?")
            assert calls(service, "ShareGrokBotAgentInPlace") == []
            assert panel._timer is None and panel.progress is None
            await pilot.press("p")
            await accept(app, pilot)
            await until(app, pilot, lambda: panel.progress is None)
            assert calls(service, "ShareGrokBotAgentInPlace") == [
                {"agentId": "demo-helper"}
            ]
            assert len(calls(service, "GetGrokBotAgentInPlaceShareStatus")) == 3
            # The timers are gone once the share is done: more running time reads nothing.
            for _ in range(10):
                await settle(app, pilot)
            assert len(calls(service, "GetGrokBotAgentInPlaceShareStatus")) == 3
            assert panel._timer is None
            assert "progress" not in [row.key for row in panel.rows]
            assert notice.call_args.args[0] == sharing.sentence("done")
            # The first delay has no history; the next ones are asked for from the last delay.
            assert asked == [None, 0.001, 0.001]
            assert "p share in place" in footer(panel)

    asyncio.run(exercise())


def test_the_first_poll_timer_waits_one_second(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["ShareGrokBotAgentInPlace"] = {"outcome": "STARTED"}
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            panel = await open_panel(app, pilot, ctx)
            await pilot.press("p")
            await accept(app, pilot)
            # A real Textual timer, set from the service's first delay; the test does not wait for it.
            assert panel._timer is not None and panel._timer._interval == 1.0
            assert calls(service, "GetGrokBotAgentInPlaceShareStatus") == []

    asyncio.run(exercise())


def test_in_place_share_shows_state_and_step_while_running(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        drive_polling(monkeypatch)
        service.transport.rpcs["ShareGrokBotAgentInPlace"] = {"outcome": "STARTED"}
        service.transport.rpcs["GetGrokBotAgentInPlaceShareStatus"] = {
            "state": "RUNNING",
            "step": "GRANTS",
        }
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            panel = await open_panel(app, pilot, ctx)
            await pilot.press("p")
            await accept(app, pilot)
            await until(
                app,
                pilot,
                lambda: (
                    len(calls(service, "GetGrokBotAgentInPlaceShareStatus")) >= 3
                    and panel.progress is not None
                    and panel.progress.step == "grants"
                ),
            )
            row = next(r for r in panel.rows if r.key == "progress")
            assert (row.label, row.detail, row.status) == (
                "Share in place",
                "step grants",
                "running",
            )
            assert "p" not in keys(panel)
            # Closing the panel stops the timers.
            await pilot.press("escape")
            await settle(app, pilot)
            assert app.screen is not panel
            for _ in range(5):
                await settle(app, pilot)
            polled = len(calls(service, "GetGrokBotAgentInPlaceShareStatus"))
            for _ in range(10):
                await settle(app, pilot)
            assert len(calls(service, "GetGrokBotAgentInPlaceShareStatus")) == polled
            assert panel._timer is None and panel.progress is None

    asyncio.run(exercise())


def test_in_place_share_failed_deadline_and_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        drive_polling(monkeypatch)
        service.transport.rpcs["ShareGrokBotAgentInPlace"] = {"outcome": "STARTED"}
        service.transport.rpcs["GetGrokBotAgentInPlaceShareStatus"] = scripted(
            [
                {"state": "RUNNING"},
                ConnectError(500, "blip"),
                {"state": "FAILED", "failureReason": "disk full"},
            ]
        )
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            panel = await open_panel(app, pilot, ctx)
            await pilot.press("p")
            await accept(app, pilot)
            await until(app, pilot, lambda: panel.progress is None)
            # A transient error is retried; a failed share says why.
            assert len(calls(service, "GetGrokBotAgentInPlaceShareStatus")) == 3
            assert notice.call_args.args[0] == "Sharing in place failed: disk full"
            assert notice.call_args.kwargs["severity"] == "error"
            # Past the deadline the panel stops asking and says so.
            service.transport.rpcs["GetGrokBotAgentInPlaceShareStatus"] = {
                "state": "RUNNING"
            }
            now = [1000.0]
            monkeypatch.setattr(slash, "_clock", lambda: now[0])
            await pilot.press("p")
            await accept(app, pilot)
            assert panel.progress is not None
            now[0] += sharing.POLL_DEADLINE_S + 1
            await until(app, pilot, lambda: panel.progress is None)
            assert panel._timer is None
            assert "45 minutes" in notice.call_args.args[0]
            # A refusal while polling stops it with the server's message.
            service.transport.rpcs["GetGrokBotAgentInPlaceShareStatus"] = refusal(
                "permission_denied", "Not yours."
            )
            now[0] = 1000.0
            await pilot.press("p")
            await accept(app, pilot)
            await until(app, pilot, lambda: panel.progress is None)
            assert notice.call_args.args[0] == "Not yours."
            assert notice.call_args.kwargs == {"severity": "warning", "markup": False}

    asyncio.run(exercise())


def test_read_only_refuses_every_change(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        service.transport.rpcs["GetGrokBotAgentAccess"] = ACCESS
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            panel = await open_panel(app, pilot, ctx)
            select(panel, "p:user:2")
            app.read_only = True
            before = len(service.transport.calls)
            for change in (
                panel.add_access,
                panel.change_role,
                panel.remove_access,
                panel.toggle_team,
                panel.make_visible,
                panel.share_in_place,
                panel.clone,
                panel.invite,
                panel.revoke_invite,
                panel.manage,
            ):
                change()
                assert notice.call_args.args[0] == "Read-only mode"
                assert app.screen is panel
            for key in ("a", "r", "x", "t", "v", "p", "c", "i", "m"):
                await pilot.press(key)
                assert app.screen is panel
            assert len(service.transport.calls) == before
            # A change confirmed just as the app turns read-only is not sent either.
            app.read_only = False
            await pilot.press("v")
            app.read_only = True
            await pilot.click("#confirm")
            await settle(app, pilot)
            assert calls(service, "SetGrokBotAgentVisibility") == []

    asyncio.run(exercise())


def test_invite_screen_previews_then_accepts(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            ctx = SlashContext(app, app.screen, None, None)
            assert run(ctx, "/invite") is None
            await settle(app, pilot)
            form = app.screen
            assert isinstance(form, FormPanel) and form.heading == "Accept an invite"
            field = form.query_one("#form-0", Input)
            assert field.password
            field.value = LINK
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, InvitePanel)
            assert calls(service, "PreviewGrokBotAgentAccessInvite") == [{"code": CODE}]
            assert dict(panel.detail.fields) == {
                "From": "Avery Chen",
                "Bot": "Shared helper",
                "Role": "user",
                "State": sharing.sentence("open"),
                "Expires": "2027-02-14",
                "Eligibility": "eligible",
            }
            assert panel.detail.body == sharing.sentence("matches")
            assert [a.key for a in panel.detail.actions] == ["a"]
            assert CODE not in app.export_screenshot() and CODE not in repr(
                panel.preview
            )
            await pilot.press("a")
            await cancel(app, pilot, "Accept access to Shared helper?")
            assert calls(service, "AcceptGrokBotAgentAccessInvite") == []
            await pilot.press("a")
            await accept(app, pilot)
            assert calls(service, "AcceptGrokBotAgentAccessInvite") == [{"code": CODE}]
            assert (
                notice.call_args.args[0]
                == "Invite accepted.\nShared helper: Access granted."
            )
            assert notice.call_args.kwargs == {
                "severity": "information",
                "markup": False,
            }
            assert CODE not in str(notice.call_args_list) and app.screen is not panel

    asyncio.run(exercise())


def test_invite_states_that_cannot_be_accepted_and_failures(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            ctx = SlashContext(app, app.screen, None, None)
            preview: dict[str, Any] = dict(
                sharing.DEMO_RPCS["PreviewGrokBotAgentAccessInvite"]  # type: ignore[arg-type]
            )
            cases = [
                ({**preview, "recipientMatch": "DOES_NOT_MATCH"}, "does_not_match"),
                (
                    {
                        **preview,
                        "eligibility": {"eligible": False, "reason": "NO_SUBSCRIPTION"},
                    },
                    "no_subscription",
                ),
                (
                    {
                        **preview,
                        "invites": [{**preview["invites"][0], "state": "EXPIRED"}],
                    },
                    "expired",
                ),
            ]
            for reply, why in cases:
                service.transport.rpcs["PreviewGrokBotAgentAccessInvite"] = reply
                run(ctx, "/invite")
                await settle(app, pilot)
                app.screen.query_one("#form-0", Input).value = CODE
                await pilot.press("ctrl+s")
                await settle(app, pilot)
                panel = app.screen
                assert isinstance(panel, InvitePanel), why
                assert panel.detail.actions == ()
                before = len(service.transport.calls)
                panel.accept()
                assert len(service.transport.calls) == before
                await pilot.press("escape")
                await settle(app, pilot)
            # An unknown code stays on the form with a message that does not echo the code.
            service.transport.rpcs["PreviewGrokBotAgentAccessInvite"] = {}
            run(ctx, "/invite")
            await settle(app, pilot)
            form = app.screen
            form.query_one("#form-0", Input).value = LINK
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert app.screen is form
            assert notice.call_args.args[0] == "That invite was not found."
            assert form.query_one("#form-0", Input).value == ""
            # A refusal is a warning with the server's message; the code is scrubbed from it.
            service.transport.rpcs["PreviewGrokBotAgentAccessInvite"] = refusal(
                "invalid_argument", f"Bad code {CODE}."
            )
            form.query_one("#form-0", Input).value = LINK
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert notice.call_args.args[0] == "Bad code [redacted]."
            assert notice.call_args.kwargs == {"severity": "warning", "markup": False}
            service.transport.rpcs["PreviewGrokBotAgentAccessInvite"] = ConnectError(
                500, f"upstream {LINK} failed"
            )
            form.query_one("#form-0", Input).value = LINK
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert CODE not in notice.call_args.args[0]
            assert notice.call_args.kwargs["severity"] == "error"
            assert CODE not in str(notice.call_args_list)

    asyncio.run(exercise())


def test_accepting_reports_each_outcome_and_respects_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        app = GbotApp(service, animate=False)
        notice = Mock()
        monkeypatch.setattr(app, "notify", notice)
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(app, pilot)
            ctx = SlashContext(app, app.screen, None, None)
            run(ctx, "/invite")
            await settle(app, pilot)
            app.screen.query_one("#form-0", Input).value = CODE
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            panel = app.screen
            assert isinstance(panel, InvitePanel)
            app.read_only = True
            panel.accept()
            assert notice.call_args.args[0] == "Read-only mode"
            assert isinstance(app.screen, InvitePanel)
            assert calls(service, "AcceptGrokBotAgentAccessInvite") == []
            app.read_only = False
            service.transport.rpcs["AcceptGrokBotAgentAccessInvite"] = {
                "status": "NOT_ELIGIBLE",
                "items": [
                    {"bot": {"name": "Shared helper"}, "outcome": "NOT_GRANTABLE"}
                ],
            }
            await pilot.press("a")
            await accept(app, pilot)
            assert notice.call_args.args[0] == (
                f"{sharing.sentence('not_eligible')}\nShared helper: {sharing.sentence('not_grantable')}"
            )
            assert notice.call_args.kwargs["severity"] == "warning"
            assert app.screen is panel
            service.transport.rpcs["AcceptGrokBotAgentAccessInvite"] = refusal(
                "permission_denied", f"No access for {CODE}"
            )
            await pilot.press("a")
            await accept(app, pilot)
            assert notice.call_args.args[0] == "No access for [redacted]"

    asyncio.run(exercise())


def test_hostile_text_is_shown_as_plain_text(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))

    async def exercise():
        service = load_fake()
        hostile = "[bold]\x1b[31mEve\x1b[0m"
        service.transport.rpcs["GetGrokBotAgentAccess"] = {
            **ACCESS,
            "botTeamDirectory": {
                "groups": [{"groupId": "7", "name": hostile, "memberCount": 1}]
            },
        }
        app = GbotApp(service, animate=False)
        async with app.run_test(size=(100, 30)) as pilot:
            ctx = await setup(app, pilot)
            panel = await open_panel(app, pilot, ctx)
            screenshot = app.export_screenshot()
            assert "\x1b" not in screenshot
            assert "\\u001b" in str(panel.query_one("#panel-rows", Static).render())

    asyncio.run(exercise())


def test_the_secret_never_appears_in_a_repr():
    result = sharing.InviteResult(sharing.Invite("a@example.invalid"), url=URL)
    preview = sharing.InvitePreview(sender_name="Pat")
    for value in (result, preview, sharing.AccessState()):
        assert URL not in repr(value) and CODE not in repr(value)
    with pytest.raises(AssertionError):
        assert URL in repr(result)
