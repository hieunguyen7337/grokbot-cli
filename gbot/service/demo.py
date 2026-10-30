"""Synthetic bots, transcripts and cards for `gbot tui --demo` and tests. Shapes follow docs/protocol-tui.md;
every name, address and text is invented."""

from dataclasses import dataclass, field

MINUTE = 60_000
HOUR = 60 * MINUTE


@dataclass
class DemoState:
    rows: list[dict[str, object]]
    transcripts: dict[str, list[dict[str, object]]]
    boxes: dict[str, str] = field(default_factory=dict)


def _row(bot_id: str, name: str, now_ms: int, **fields: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": bot_id,
        "name": name,
        "description": f"{name} bot",
        "path": f"/bots/{bot_id}",
        "createdAt": now_ms - 30 * 24 * HOUR,
        "updatedAt": now_ms - HOUR,
        "hasUnread": False,
        "unreadCount": 0,
        "isActive": True,
        "isComposingMessage": False,
        "isGroup": False,
        "isRunning": False,
        "notificationsEnabled": True,
        "notifyOnUpdatesEnabled": True,
        "avatarDataUrl": None,
        "lastMessageId": None,
        "awaitingUserResponse": None,
        "lastEntry": None,
        "memberIds": [],
        "origin": "user",
        "lastActivityAt": now_ms - 3 * HOUR,
    }
    row.update(fields)
    return row


def _user(turn: int, seq: int, text: str, at: int) -> dict[str, object]:
    return {
        "id": f"t{turn}u",
        "seq": seq,
        "kind": "message",
        "role": "user",
        "content": text,
        "isStreaming": False,
        "clientNonce": f"nonce-{turn}",
        "timestampMs": at,
    }


def _bot(turn: int, step: int, seq: int, text: str, at: int) -> dict[str, object]:
    return {
        "id": f"t{turn}s{step}",
        "seq": seq,
        "kind": "send-message",
        "timestampMs": at,
        "message": {"type": "text", "content": text},
    }


def _tool(
    turn: int, step: int, seq: int, name: str, summary: str, at: int
) -> dict[str, object]:
    return {
        "id": f"t{turn}a{step}",
        "seq": seq,
        "kind": "tool-call",
        "name": name,
        "status": "done",
        "summary": summary,
        "timestampMs": at,
    }


def _card(
    turn: int, step: int, seq: int, message: dict[str, object], at: int
) -> dict[str, object]:
    return {
        "id": f"t{turn}s{step}",
        "seq": seq,
        "kind": "send-message",
        "timestampMs": at,
        "requestId": f"req-{turn}-{step}",
        "message": message,
    }


def demo_state(now_ms: int) -> DemoState:
    t = now_ms
    inbox = [
        _user(
            1, 1, "Check my inbox and draft replies to anything urgent.", t - 2 * HOUR
        ),
        _tool(
            1,
            0,
            2,
            "gmail.search_threads",
            "Searched 24 unread threads",
            t - 2 * HOUR + MINUTE,
        ),
        _bot(
            1,
            1,
            3,
            "Two threads need a reply today. I drafted the first one.",
            t - 2 * HOUR + 2 * MINUTE,
        ),
        _card(
            1,
            2,
            4,
            {
                "type": "email-draft",
                "draft": {
                    "from": "you@example.com",
                    "to": ["ada@example.com"],
                    "cc": [],
                    "subject": "Re: invoice",
                    "body": "Hi Ada,\n\nThanks - the invoice is approved and will be paid on Friday.\n\nBest",
                },
            },
            t - 3 * MINUTE,
        ),
    ]
    planner = [
        _user(1, 1, "Plan the team offsite.", t - 5 * HOUR),
        _bot(
            1,
            1,
            2,
            "I found four venues that fit the dates and budget.",
            t - 5 * HOUR + 4 * MINUTE,
        ),
        _card(
            1,
            2,
            3,
            {
                "type": "widget",
                "widget": {
                    "prompt": "Which venue should I book?",
                    "options": [
                        {"label": "Lakeside Lodge"},
                        {"label": "City Loft"},
                        {"label": "Harbor Hall"},
                        {"label": "Garden House"},
                    ],
                },
            },
            t - HOUR,
        ),
    ]
    research = [
        _user(1, 1, "Find flights SFO to NRT for the week of March 9.", t - 4 * MINUTE),
        _tool(1, 0, 2, "web.search", "Searching flights SFO to NRT", t - 3 * MINUTE),
    ]
    ledger = [
        _user(1, 1, "Log the receipts in my Drive folder.", t - HOUR),
        _tool(1, 0, 2, "drive.list_files", "Listed 3 new receipts", t - 50 * MINUTE),
        _bot(
            1,
            1,
            3,
            "Logged 3 receipts to the October sheet. Total: $182.40.",
            t - 12 * MINUTE,
        ),
    ]
    travel = [
        _user(1, 1, "Rebook my hotel for one more night.", t - 30 * MINUTE),
        _card(
            1,
            1,
            2,
            {
                "type": "auto-review-approval",
                "approval": {
                    "requestId": "review-travel",
                    "status": "pending",
                    "summary": "Extend booking by one night",
                    "reason": "This changes a paid reservation",
                    "surface": "box_shell",
                    "command": "book extend --nights 1",
                },
            },
            t - 25 * MINUTE,
        ),
    ]
    outbox = [
        _user(1, 1, "Send the weekly update to the team list.", t - 26 * HOUR),
        _bot(
            1,
            1,
            2,
            "Sent the weekly update to team@example.com.",
            t - 26 * HOUR + 2 * MINUTE,
        ),
    ]
    helper = [
        _user(1, 1, "Summarise the meeting notes.", t - 3 * HOUR),
        {
            "id": "t1n0",
            "seq": 2,
            "kind": "notice",
            "text": "The turn stopped after an error.",
            "timestampMs": t - 3 * HOUR + MINUTE,
        },
    ]
    team = [
        _user(1, 1, "Who is handling the invoice follow-up?", t - 6 * HOUR),
        _bot(
            1,
            1,
            2,
            "Inbox drafted the reply; Outbox will send it once you approve.",
            t - 6 * HOUR + MINUTE,
        ),
    ]
    rows = [
        _row(
            "demo-inbox",
            "Inbox",
            t,
            awaitingUserResponse={
                "tabId": "main",
                "reason": "draft",
                "since": t - 3 * MINUTE,
            },
            lastMessagePreview="Email draft: Re: invoice",
            lastActivityAt=t - 3 * MINUTE,
            avatarColor="blue",
        ),
        _row(
            "demo-planner",
            "Planner",
            t,
            awaitingUserResponse={
                "tabId": "main",
                "reason": "widget",
                "since": t - HOUR,
            },
            lastMessagePreview="Which venue should I book?",
            lastActivityAt=t - HOUR,
            avatarColor="purple",
        ),
        _row(
            "demo-research",
            "Research",
            t,
            isRunning=True,
            isRunningTurn=True,
            currentActivity={
                "kind": "tool",
                "tool": "web.search",
                "detail": "flights SFO to NRT",
            },
            lastMessagePreview="Find flights SFO to NRT for the week of March 9.",
            lastActivityAt=t - 3 * MINUTE,
            avatarColor="green",
        ),
        _row(
            "demo-ledger",
            "Ledger",
            t,
            hasUnread=True,
            unreadCount=1,
            lastMessagePreview="Logged 3 receipts to the October sheet. Total: $182.40.",
            lastActivityAt=t - 12 * MINUTE,
            lastViewedAt=t - HOUR,
            avatarColor="orange",
        ),
        _row(
            "demo-travel",
            "Travel",
            t,
            awaitingUserResponse={
                "tabId": "main",
                "reason": "auto-review",
                "since": t - 25 * MINUTE,
            },
            lastMessagePreview="Approve: Extend booking by one night",
            lastActivityAt=t - 25 * MINUTE,
            avatarColor="teal",
        ),
        _row(
            "demo-outbox",
            "Outbox",
            t,
            lastMessagePreview="Sent the weekly update to team@example.com.",
            lastActivityAt=t - 26 * HOUR,
        ),
        _row(
            "demo-helper",
            "Helper",
            t,
            lastMessagePreview="The turn stopped after an error.",
            lastActivityAt=t - 3 * HOUR,
            lastTurnSettlement={
                "clientNonce": "nonce-1",
                "outcome": "failed",
                "settledAtMs": t - 3 * HOUR,
            },
        ),
        _row(
            "demo-team",
            "Email team",
            t,
            isGroup=True,
            memberIds=["demo-inbox", "demo-outbox", "demo-ledger"],
            lastMessagePreview="Inbox drafted the reply; Outbox will send it once you approve.",
            lastActivityAt=t - 6 * HOUR,
        ),
    ]
    transcripts = {
        "demo-inbox": inbox,
        "demo-planner": planner,
        "demo-research": research,
        "demo-ledger": ledger,
        "demo-travel": travel,
        "demo-outbox": outbox,
        "demo-helper": helper,
        "demo-team": team,
    }
    boxes = {"demo-research": "running", "demo-inbox": "hibernated"}
    return DemoState(rows, transcripts, boxes)
