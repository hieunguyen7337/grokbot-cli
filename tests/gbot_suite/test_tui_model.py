from dataclasses import replace

from rich.cells import cell_len

from gbot.pending import PendingItem
from gbot.service.fake import load_fake
from gbot.service.models import Awaiting, Bot, ConnectionStatus
from gbot.tui.model import (
    RowState,
    age_text,
    apply_filter,
    build_rows,
    counts,
    group,
    header_text,
    jump_section,
    layout_row,
    move,
    parse_filter,
)


def card(bot_id, session=None, actions=("approve",), kind="email-draft"):
    return PendingItem(
        bot_id, "name", "entry", session, kind, "Re: invoice", None, actions
    )


def test_states_and_summaries():
    bots = [
        Bot("a", "A", running=True, has_unread=True),
        Bot("b", "B"),
        Bot("c", "C", awaiting=Awaiting("reason")),
        Bot("d", "D"),
        Bot("e", "E", running=True),
        Bot("f", "F", has_unread=True, preview="reply"),
        Bot("g", "G", description="description", last_outcome="failed"),
        Bot("h", "H", retrying=True),
        Bot("hidden", "Hidden", hidden=True),
    ]
    rows = build_rows(
        bots, [card("a"), card("b", actions=()), card("d", "other")], now_ms=100
    )
    assert [r.variant for r in rows[:4]] == [
        "card",
        "app_only",
        "awaiting",
        "other_session",
    ]
    assert rows[0].summary == "Email draft: Re: invoice"
    assert rows[1].summary.endswith(" (open the Grok Bot app)")
    assert rows[2].summary == "Waiting for you: reason"
    assert rows[3].summary == "Needs you in another chat"
    assert [r.state for r in rows[4:7]] == [
        RowState.WORKING,
        RowState.NEW_REPLY,
        RowState.IDLE,
    ]
    assert [r.summary for r in rows[4:7]] == ["Thinking", "reply", "description"]
    assert [r.badge for r in rows[6:]] == ["failed", "retrying"]
    elsewhere = build_rows([bots[2]], [card("c", "thread")], now_ms=100)[0]
    assert elsewhere.variant == "other_session"
    widget = replace(card("a"), type="widget", summary="Pick", options=["a", "b"])
    assert build_rows(bots[:1], [widget], now_ms=0)[0].summary == "Pick (2 choices)"


def test_group_filter_selection_and_demo():
    service = load_fake()
    bots = service.roster()
    cards, _ = service.pending()
    rows = build_rows(
        bots, cards, now_ms=1_800_000_000_000, pins=("demo-ledger", "demo-inbox")
    )
    states = {r.name: r.state for r in rows}
    assert all(
        states[n] == RowState.NEEDS_INPUT for n in ("Inbox", "Planner", "Travel")
    )
    assert (
        states["Research"] == RowState.WORKING
        and states["Ledger"] == RowState.NEW_REPLY
    )
    sections = group(rows, order=("demo-travel",), idle_limit=1)
    assert [r.bot_id for r in sections[0].rows] == ["demo-ledger", "demo-inbox"]
    assert sections[1].rows[0].bot_id == "demo-travel"
    assert sections[-1].hidden_count > 0
    assert group(rows, expanded=frozenset({"idle"}))[-1].hidden_count == 0
    teams = group(rows, by="team")
    assert [r.bot_id for r in teams[0].rows] == [
        "demo-team",
        "demo-inbox",
        "demo-outbox",
        "demo-ledger",
    ]
    for query, expected in (
        ("s:working", "Research"),
        ("n:planner", "Planner"),
        ("t:email n:inbox", "Inbox"),
        ("receipts", "Ledger"),
    ):
        assert [r.name for r in apply_filter(rows, parse_filter(query), bots)] == [
            expected
        ]
    collapsed = group(rows, collapsed=frozenset({"input"}))
    assert not collapsed[1].rows and collapsed[1].collapsed
    assert move(collapsed, "demo-ledger", -1) == "demo-ledger"
    assert jump_section(collapsed, "demo-ledger", 1) == collapsed[2].rows[0].bot_id
    assert move([], None, 1) is None and jump_section([], None, 1) is None


def test_layout_headers_and_hostile_text():
    hostile = "A\x1b[31m[link=x]文\u202e\x07"
    row = build_rows(
        [Bot("x", hostile, running=True, activity=hostile, last_activity_at=0)],
        [],
        now_ms=12000,
    )[0]
    assert (
        "\x1b" not in row.name
        and "\u202e" not in row.summary
        and "\\u0007" in row.summary
    )
    for ascii_only in (False, True):
        for text in ("abc", "中文中文", "\U0001f600\U0001f600"):
            for width in range(30, 201):
                line = layout_row(
                    replace(row, name=text, summary=text * 100),
                    width,
                    ascii_only=ascii_only,
                )
                assert (
                    cell_len(
                        "  "
                        + line.glyph
                        + " "
                        + line.name
                        + "  "
                        + line.summary
                        + line.age
                    )
                    == width
                )
        assert (
            layout_row(row, 30, frame=0, ascii_only=ascii_only).glyph
            == layout_row(row, 30, frame=24, ascii_only=ascii_only).glyph
        )
        for status in ConnectionStatus:
            left, right = header_text(counts([row]), status, ascii_only=ascii_only)
            assert "1 working" in left and status.value in right
    assert [
        age_text(x) for x in (0, 12000, 240000, 10800000, 172800000, 3024000000)
    ] == ["now", "12s", "4m", "3h", "2d", "5w"]


def test_error_badge_precedence():
    bots = [
        Bot("a", "A", last_outcome="failed", retrying=True),
        Bot("b", "B", retrying=True),
        Bot("c", "C"),
        Bot("d", "D"),
    ]
    rows = build_rows(bots, [], now_ms=0, errors=dict.fromkeys("abc", "failure"))
    assert [r.badge for r in rows] == ["failed", "retrying", "error", None]


def test_precise_header_text():
    expected = (
        "connecting",
        "live",
        "reconnecting (3)",
        "computer asleep · wakes when you act",
        "signed out · run gbot login",
        "offline · retrying",
    )
    for status, label in zip(ConnectionStatus, expected):
        assert header_text({}, status, attempt=3)[1] == f"● {label}"
        assert header_text({}, status, attempt=3, ascii_only=True)[1] == (
            "o " + label.replace("·", "-")
        )
    assert header_text({}, ConnectionStatus.RECONNECTING)[1] == "● reconnecting"
