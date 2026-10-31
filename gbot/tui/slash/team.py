"""Team bots: shared context and review queue, memory sharing and team link previews (team accounts only)."""

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import TypeVar

from textual import events
from textual.widgets import Static

from gbot.output import terminal_safe
from gbot.service import team_bots as service
from gbot.service.errors import refusal
from gbot.service.models import Bot
from gbot.tui.panels.kit import (
    Detail,
    FormField,
    FormPanel,
    ListPanel,
    PanelAction,
    PanelRow,
)
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.avatar_voice import _Detail
from gbot.tui.slash.rooms import _writable
from groken.client import ConnectError

T = TypeVar("T")


def _attempt(call: Callable[[], T]) -> tuple[T | None, str]:
    """The call's value, or None and the server's sentence when the server refuses it."""
    try:
        return call(), ""
    except ConnectError as error:
        found = refusal(error)
        if found is None:
            raise
        return None, found.message


def _worker(
    ctx: SlashContext, work: Callable[[], object], done: Callable[[object], object]
) -> None:
    def run() -> None:
        try:
            result = work()
        except Exception as error:  # noqa: BLE001 - worker boundary
            found = refusal(error)
            message = found.message if found else str(error)
            ctx.app.call_from_thread(
                ctx.app.notify,
                terminal_safe(message),
                severity="error",
                markup=False,
            )
        else:
            ctx.app.call_from_thread(done, result)

    ctx.app.run_worker(run, thread=True, exit_on_error=False)


def _mutate(
    ctx: SlashContext,
    question: str,
    label: str,
    work: Callable[[], object],
    done: Callable[[object], object],
) -> None:
    if not _writable(ctx):
        return

    def confirmed(ok: bool | None) -> None:
        if not ok or not _writable(ctx):
            return

        def run() -> object:
            if ctx.app.read_only:
                raise ValueError("Read-only mode")
            return work()

        _worker(ctx, run, done)

    ctx.app.push_screen(ConfirmScreen(terminal_safe(question), "", label), confirmed)


def _team_id(text: str) -> int:
    if not text.strip().isdecimal():
        raise ValueError("Enter a team ID number.")
    return int(text.strip())


def _team_error(value: str) -> str | None:
    return None if value.strip().isdecimal() else "Enter a team ID number."


def _kind(change: service.ReviewChange) -> str:
    return " ".join(
        part
        for part in (change.kind.replace("_", " "), change.action)
        if part and part != "unspecified"
    )


class _TeamList(ListPanel):
    """A list whose empty or refused state is one plain sentence, set by its load."""

    def __init__(
        self,
        ctx: SlashContext,
        title: str,
        load: Callable[[], Sequence[PanelRow]],
        *,
        empty: str,
        actions: Sequence[PanelAction] = (),
    ) -> None:
        self.ctx = ctx
        self.empty_text = empty
        self.notice = ""
        super().__init__(title, load, empty=empty, actions=actions)

    def _loaded(self, rows: list[PanelRow], error: str) -> None:
        self.empty = self.notice or self.empty_text
        super()._loaded(rows, error)
        self._footer()

    def visible_actions(self) -> Sequence[PanelAction]:
        return self.actions

    def _footer(self) -> None:
        self.query_one(".panel-footer", Static).update(
            " · ".join(f"{a.key} {a.label}" for a in self.visible_actions())
            + " · esc back"
        )

    def _selected(self) -> PanelRow | None:
        rows = self.visible_rows
        return rows[min(self.index, len(rows) - 1)] if rows else None

    def on_mount(self) -> None:
        super().on_mount()
        self._footer()

    def on_key(self, event: events.Key) -> None:
        if event.key == "g" and not self.visible_rows:
            # ListPanel dispatches actions only for a selected row; an empty list still reloads.
            self.reload()
            event.stop()
            event.prevent_default()
            return
        super().on_key(event)
        self._footer()

    def reload_row(self, row: PanelRow | None = None) -> None:
        self.reload()


class TeamBotPanel(_TeamList):
    """<bot> in your team: the shared summary, then the review queue (pending or approved)."""

    def __init__(self, ctx: SlashContext) -> None:
        self.bot = ctx.app.state.bots[ctx.bot_id or ""]
        self.showing = "pending"
        super().__init__(
            ctx,
            f"{self.bot.name} in your team",
            self.load_rows,
            empty="No pending changes.",
            actions=(
                PanelAction("a", "Approve", self.approve),
                PanelAction("r", "Reject", self.reject),
                PanelAction("h", "Approved", self.toggle_showing),
                PanelAction("m", "Memories", self.memories),
                PanelAction("g", "Reload", self.reload_row),
            ),
        )

    def visible_actions(self) -> Sequence[PanelAction]:
        pending = self.showing == "pending"
        row = self._selected()
        on_item = pending and row is not None and row.key.startswith("item:")
        shown = []
        for action in self.actions:
            if action.key in {"a", "r"} and not on_item:
                continue
            if action.key == "h":
                action = replace(action, label="Approved" if pending else "Pending")
            shown.append(action)
        return shown

    def load_rows(self) -> list[PanelRow]:
        if self.showing == "approved":
            return self._review_rows(("approved",), 20, "No approved changes yet.")
        return [
            *self._summary_rows(),
            *self._review_rows(("pending",), 100, "No pending changes."),
        ]

    def _summary_rows(self) -> list[PanelRow]:
        transport = self.ctx.service.transport
        summary, message = _attempt(
            lambda: service.context_summary(transport, self.bot.id)
        )
        if summary is None:
            return [PanelRow("summary", "Summary", message, tone="muted")]
        rows = [
            PanelRow(
                "summary",
                "Summary",
                summary.prose or "No summary yet.",
                status=f"{summary.memory_count} memories"
                + (" · stale" if summary.stale else ""),
                tone="warn" if summary.stale else "muted",
            )
        ]
        for fact in summary.learned:
            date = service.date_text(fact.learned_at_ms)
            rows.append(
                PanelRow(
                    f"fact:{fact.fact_id}",
                    fact.text,
                    f"learned {date}" if date else "learned",
                )
            )
        return rows

    def _review_rows(
        self, statuses: tuple[str, ...], limit: int, empty: str
    ) -> list[PanelRow]:
        transport = self.ctx.service.transport
        items, message = _attempt(
            lambda: service.review_items(transport, self.bot.id, statuses, limit)
        )
        if items is None:
            return [PanelRow("review", "Review", message, tone="muted")]
        if not items:
            return [PanelRow("review", "Review", empty, tone="muted")]
        return [
            PanelRow(
                f"item:{item.item_id}",
                _kind(item.change),
                item.change.summary or item.change.text or item.change.name,
                status=item.status,
                tone="warn" if item.status == "pending" else "ok",
            )
            for item in items
        ]

    def approve(self, row: PanelRow) -> None:
        self._decide(row, approve=True)

    def reject(self, row: PanelRow) -> None:
        self._decide(row, approve=False)

    def _decide(self, row: PanelRow, *, approve: bool) -> None:
        if self.showing != "pending" or not row.key.startswith("item:"):
            return
        item_id = row.key.removeprefix("item:")
        verb = "Approve" if approve else "Reject"
        transport = self.ctx.service.transport
        _mutate(
            self.ctx,
            f"{verb} this change to {self.bot.name}?",
            verb,
            lambda: service.resolve_review_item(
                transport, self.bot.id, item_id, approve
            ),
            lambda _: self.reload(),
        )

    def toggle_showing(self, row: PanelRow | None = None) -> None:
        self.showing = "approved" if self.showing == "pending" else "pending"
        self.reload()

    def memories(self, row: PanelRow | None = None) -> None:
        self.ctx.app.push_screen(MemoriesPanel(self.ctx, self.bot, self.reload))


class MemoriesPanel(_TeamList):
    """The bot's memories you can share with the team; space marks, p shares the marked ones."""

    def __init__(
        self, ctx: SlashContext, bot: Bot, after_promote: Callable[[], None]
    ) -> None:
        self.bot = bot
        self.after_promote = after_promote
        self.facts: tuple[service.MemoryFact, ...] = ()
        self.marked: set[str] = set()
        super().__init__(
            ctx,
            f"{bot.name} memories",
            self.load_rows,
            empty="No memories to share with the team.",
            actions=(
                PanelAction("space", "Mark", self.toggle),
                PanelAction("p", "Share", self.promote),
                PanelAction("g", "Reload", self.reload_row),
            ),
        )

    def visible_actions(self) -> Sequence[PanelAction]:
        return tuple(
            action
            for action in self.actions
            if (action.key != "space" or self.facts)
            and (action.key != "p" or self.marked)
        )

    def load_rows(self) -> list[PanelRow]:
        transport = self.ctx.service.transport
        facts, message = _attempt(lambda: service.bot_memories(transport, self.bot.id))
        self.notice = message
        self.facts = facts or ()
        self.marked &= {fact.fact_id for fact in self.facts}
        return self._rows()

    def _rows(self) -> list[PanelRow]:
        return [
            PanelRow(
                fact.fact_id,
                f"{'[x]' if fact.fact_id in self.marked else '[ ]'} {fact.text}",
                service.date_text(fact.learned_at_ms),
            )
            for fact in self.facts
        ]

    def toggle(self, row: PanelRow) -> None:
        self.marked ^= {row.key}
        self.rows = self._rows()
        self._draw()

    def promote(self, row: PanelRow | None = None) -> None:
        ids = [fact.fact_id for fact in self.facts if fact.fact_id in self.marked]
        if not ids:
            return
        transport = self.ctx.service.transport
        _mutate(
            self.ctx,
            f"Share {len(ids)} memories of {self.bot.name} with the team?",
            "Share",
            lambda: service.promote_memories(transport, self.bot.id, ids),
            self.promoted,
        )

    def promoted(self, result: object) -> None:
        assert isinstance(result, service.PromoteResult)
        self.marked.clear()
        self.ctx.app.notify(
            terminal_safe(service.promote_sentence(result)), markup=False
        )
        self.reload()
        self.after_promote()


def _agent_row(agent: service.TeamAgent) -> PanelRow:
    last = service.date_text(agent.last_turn_at_ms)
    return PanelRow(
        agent.agent_id,
        agent.name or agent.agent_id,
        f"{agent.user_turns} user turns · {agent.teammate_turns} teammate turns",
        status=f"last turn {last}" if last else "no turns yet",
        tone="muted",
    )


class TeamBotsPanel(_TeamList):
    """Team agents with their turn counts; empty on a personal account."""

    def __init__(self, ctx: SlashContext) -> None:
        super().__init__(
            ctx,
            "Team bots",
            self.load_rows,
            empty="No team bots.",
            actions=(PanelAction("g", "Reload", self.reload_row),),
        )

    def load_rows(self) -> list[PanelRow]:
        transport = self.ctx.service.transport
        agents, message = _attempt(lambda: service.team_agents(transport))
        self.notice = message
        if agents is None:
            return []
        return [_agent_row(agent) for agent in agents.entries]


class LinkPreviewPanel(_Detail):
    """A team's link previews; t turns them on or off after confirmation."""

    def __init__(self, ctx: SlashContext, team_id: int) -> None:
        self.ctx = ctx
        self.team_id = team_id
        self.setting: bool | None = None
        self.notice = ""
        super().__init__(f"Link previews for team {team_id}", self.content)

    def on_mount(self) -> None:
        super().on_mount()
        self.reload()

    def content(self) -> Detail:
        actions = [PanelAction("g", "Reload", self.reload)]
        if self.setting is not None:
            turn = "off" if self.setting else "on"
            actions.insert(0, PanelAction("t", f"Turn {turn}", self.toggle))
        state = "unknown" if self.setting is None else ("on" if self.setting else "off")
        return Detail(
            (("Team", str(self.team_id)), ("Link previews", state)),
            body=self.notice,
            actions=tuple(actions),
        )

    def reload(self) -> None:
        transport = self.ctx.service.transport
        team_id = self.team_id

        def fetch() -> object:
            value, message = _attempt(lambda: service.link_preview(transport, team_id))
            return value if value is not None else message

        _worker(self.ctx, fetch, self.loaded)

    def loaded(self, value: object) -> None:
        if isinstance(value, bool):
            self.setting, self.notice = value, ""
        elif isinstance(value, str):
            self.setting, self.notice = None, value
        self.detail = self.content()
        self.index = 0
        self._draw()
        self._footer()

    def _footer(self) -> None:
        self.query_one(".panel-footer", Static).update(
            " · ".join(f"{a.key} {a.label}" for a in self.detail.actions)
            + " · esc back"
        )

    def toggle(self) -> None:
        if self.setting is None:
            return
        team_id = self.team_id
        enabled = not self.setting
        transport = self.ctx.service.transport
        word = "on" if enabled else "off"
        _mutate(
            self.ctx,
            f"Turn link previews {word} for team {team_id}?",
            f"Turn {word}",
            lambda: service.set_link_preview(transport, team_id, enabled),
            self.loaded,
        )


class _TeamForm(FormPanel):
    """Asks for a team ID; the submit replaces this form, so reads stay open in read-only mode."""

    def _submit_done(self, message: str) -> None:
        pass


def _open_preview(ctx: SlashContext, team_id: int) -> None:
    def replace_form() -> None:
        ctx.app.pop_screen()
        ctx.app.push_screen(LinkPreviewPanel(ctx, team_id))

    ctx.app.call_from_thread(replace_form)


def team(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(TeamBotPanel(ctx))


def team_bots(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(TeamBotsPanel(ctx))


def link_preview(ctx: SlashContext, args: str) -> None:
    if args.strip():
        ctx.app.push_screen(LinkPreviewPanel(ctx, _team_id(args)))
        return

    def submit(values: dict[str, str | bool]) -> None:
        _open_preview(ctx, _team_id(str(values["team"])))

    ctx.app.push_screen(
        _TeamForm(
            "Team link preview",
            (
                FormField(
                    "team",
                    "Team ID",
                    "text",
                    required=True,
                    validate=_team_error,
                ),
            ),
            submit,
            submit_label="Show",
        )
    )


COMMANDS = (
    SlashCommand("team", "Review a team bot", team, scope="session", needs_bot=True),
    SlashCommand("team-bots", "List team bots", team_bots),
    SlashCommand(
        "team-link-preview", "Team link previews", link_preview, args="[TEAM_ID]"
    ),
)
