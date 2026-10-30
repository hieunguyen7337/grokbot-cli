"""Browse public templates and review imports."""

from collections.abc import Sequence
from uuid import uuid4

from rich.text import Text
from textual.widgets import Static

from gbot.output import terminal_safe
from gbot.service import templates as service
from gbot.tui.panels.kit import Detail, ListPanel, PanelAction, PanelRow
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.avatar_voice import _confirm, _Detail, _worker


class _TemplatesPanel(ListPanel):
    def reload(self) -> None:
        super().reload()
        self.query_one("#panel-rows", Static).update("Loading templates…")

    def _draw(self) -> None:
        super()._draw()
        widget = self.query_one("#panel-rows", Static)
        if isinstance(widget.content, Text):
            # Category rows are headings, never interpreted as Rich markup.
            text = widget.content.copy()
            offset = 0
            for line in text.plain.splitlines(keepends=True):
                if line.startswith(("  ", "> ")) and any(
                    row.key.startswith("heading:") and line[2:].rstrip() == row.label
                    for row in self.visible_rows
                ):
                    text.stylize("dim", offset, offset + len(line))
                offset += len(line)
            widget.update(text)


def templates(ctx: SlashContext, args: str) -> None:
    category = args.strip()
    listings: dict[str, service.Listing] = {}

    def load() -> list[PanelRow]:
        try:
            market = service.marketplace(ctx.service.transport)
        except Exception as error:
            ctx.app.call_from_thread(ctx.app.service_error, error)
            raise
        listings.clear()
        rows: list[PanelRow] = []
        seen: set[str] = set()

        def matches(item: service.Listing) -> bool:
            return not category or category.casefold() in {
                value.casefold() for value in (item.category, *item.categories)
            }

        def group(title: str, items: Sequence[service.Listing]) -> None:
            selected = [
                item for item in items if matches(item) and item.share_id not in seen
            ]
            if not selected:
                return
            rows.append(PanelRow(f"heading:{title}", title))
            for item in selected:
                if item.share_id in seen:
                    continue
                seen.add(item.share_id)
                listings[item.share_id] = item
                rows.append(
                    PanelRow(
                        item.share_id,
                        item.name,
                        f"{item.creator_name} · {item.category}",
                    )
                )

        group("Featured", market.featured_listings)
        categories = list(
            dict.fromkeys(
                (*market.category_order, *(item.category for item in market.listings))
            )
        )
        for name in categories:
            group(name, [item for item in market.listings if item.category == name])
        return rows

    def select(row: PanelRow) -> None:
        listing = listings.get(row.key)
        if listing is None:
            return

        def load_detail() -> None:
            details = service.details(ctx.service.transport, listing.share_id)
            ctx.app.call_from_thread(
                ctx.app.push_screen, _TemplatePanel(ctx, listing, details)
            )

        _worker(ctx, load_detail)

    ctx.app.push_screen(
        _TemplatesPanel(
            "Templates",
            load,
            on_select=select,
            empty=f"No templates in {category}" if category else "No templates",
        )
    )


class _TemplatePanel(_Detail):
    def __init__(
        self,
        ctx: SlashContext,
        listing: service.Listing,
        details: service.TemplateDetails,
    ) -> None:
        self.ctx, self.details = ctx, details
        self.agent_id = str(uuid4())
        self.result: service.TemplateResult | None = None
        name = str(details.template.get("name") or listing.name)
        self.template_name = name
        super().__init__(
            name,
            lambda: Detail(
                (
                    ("Name", name),
                    (
                        "Description",
                        str(details.template.get("description") or listing.description),
                    ),
                    ("Creator", details.creator_display_name or listing.creator_name),
                    (
                        "Categories",
                        ", ".join(listing.categories or (listing.category,)),
                    ),
                    ("Version", str(details.expected_active_version)),
                ),
                actions=(PanelAction("u", "Use template", self.use),),
            ),
        )

    def use(self) -> None:
        def create() -> None:
            self.result = service.create_from_template(
                self.ctx.service.transport, self.details, agent_id=self.agent_id
            )

        def opened() -> None:
            if self.result is None:
                return
            # open_bot accepts the home screen; imports work from session panels too.
            while self.ctx.app.screen is not self.ctx.app.home:
                self.ctx.app.pop_screen()
            self.ctx.app.open_bot(self.result.bot)
            if not self.result.setup_handled_by_server:
                self.ctx.app.notify(
                    terminal_safe(self.result.note), severity="warning", markup=False
                )

        _confirm(
            self.ctx,
            f"Create a bot from {terminal_safe(self.template_name)}?",
            create,
            opened,
        )


COMMANDS = (
    SlashCommand("templates", "Browse public templates", templates, args="[category]"),
)
