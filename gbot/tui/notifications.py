"""Roster transition notices, independent of the terminal UI."""

from collections.abc import Iterable
from dataclasses import dataclass

from gbot.service.models import Bot
from gbot.tui.model import RowState, build_rows


@dataclass(frozen=True)
class Notice:
    bot_id: str
    text: str
    bell: bool


class Notifier:
    def __init__(self) -> None:
        self._previous: dict[str, RowState] | None = None

    def update(self, bots: Iterable[Bot], *, open_bot_id: str | None) -> list[Notice]:
        rows = build_rows(bots, [], now_ms=0)
        notices = []
        if self._previous is not None:
            for row in rows:
                before = self._previous.get(row.bot_id)
                if row.bot_id == open_bot_id or before == row.state:
                    continue
                if row.state == RowState.NEEDS_INPUT:
                    notices.append(Notice(row.bot_id, f"{row.name} needs you", True))
                elif row.state == RowState.NEW_REPLY and before in {
                    RowState.WORKING,
                    RowState.IDLE,
                }:
                    notices.append(Notice(row.bot_id, f"{row.name} replied", False))
        self._previous = {row.bot_id: row.state for row in rows}
        return notices
