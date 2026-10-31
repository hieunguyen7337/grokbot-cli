"""Read-only account panels: egress, analytics, default payment method, address lookup and teach status."""

from collections.abc import Callable
from dataclasses import replace

from textual.widgets import Static

from gbot.output import terminal_safe
from gbot.service import account as service
from gbot.service.errors import Refusal
from gbot.tui.panels.kit import (
    Detail,
    DetailPanel,
    FormField,
    FormPanel,
    ListPanel,
    PanelAction,
    PanelRow,
)
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.avatar_voice import _Detail


def _worker(
    ctx: SlashContext, work: Callable[[], object], done: Callable[[object], object]
) -> None:
    def run() -> None:
        try:
            result = work()
        except Exception as error:  # noqa: BLE001 - worker boundary
            ctx.app.call_from_thread(
                ctx.app.notify,
                terminal_safe(str(error)),
                severity="error",
                markup=False,
            )
        else:
            ctx.app.call_from_thread(done, result)

    ctx.app.run_worker(run, thread=True, exit_on_error=False)


class _Read(_Detail):
    """A read-only detail that loads in a thread worker; g reloads it."""

    def __init__(
        self, ctx: SlashContext, title: str, fetch: Callable[[], Detail]
    ) -> None:
        self.ctx = ctx
        self.fetch = fetch
        self.generation = 0
        super().__init__(title, lambda: Detail((), body="Loading…"))

    def on_mount(self) -> None:
        super().on_mount()
        self.reload()

    def reload(self) -> None:
        self.generation += 1
        generation = self.generation

        def load() -> Detail:
            try:
                return self.fetch()
            except Exception as error:  # noqa: BLE001 - panel boundary
                return Detail((), body=str(error))

        def done(value: object) -> None:
            # A slow earlier load must not replace the result of a later reload.
            if generation == self.generation:
                self.loaded(value)

        _worker(self.ctx, load, done)

    def loaded(self, value: object) -> None:
        assert isinstance(value, Detail)
        self.detail = replace(value, actions=(PanelAction("g", "Reload", self.reload),))
        self.index = 0
        self._draw()
        self.query_one(".panel-footer", Static).update(
            " · ".join(f"{a.key} {a.label}" for a in self.detail.actions)
            + " · esc back"
        )


def analytics(ctx: SlashContext, args: str) -> None:
    bot = ctx.app.state.bots[ctx.bot_id or ""]

    def load() -> Detail:
        value = service.analytics(ctx.service.transport, bot.id)
        if isinstance(value, Refusal):
            return Detail((), body=value.message)
        if value is None:
            return Detail((), body=service.NO_ANALYTICS)
        return Detail(
            service.analytics_fields(value),
            body="\n".join(service.analytics_lines(value)),
        )

    ctx.app.push_screen(_Read(ctx, f"{bot.name} analytics", load))


def egress(ctx: SlashContext, args: str) -> None:
    def load() -> Detail:
        policy = service.egress_policy(ctx.service.transport)
        if isinstance(policy, Refusal):
            return Detail((), body=policy.message)
        return Detail(
            service.egress_fields(policy),
            body="\n".join(service.egress_lines(policy)),
        )

    ctx.app.push_screen(_Read(ctx, "Network egress", load))


def payment(ctx: SlashContext, args: str) -> None:
    def load() -> Detail:
        method = service.default_payment_method(ctx.service.transport)
        if isinstance(method, Refusal):
            return Detail((), body=method.message)
        return Detail(
            (("Default payment method", method.label),),
            body=service.CHANGE_PAYMENT,
        )

    ctx.app.push_screen(_Read(ctx, "Payment method", load))


class AddressPanel(ListPanel):
    """Suggestions from one lookup; Enter resolves the selected one with the same session token."""

    def __init__(
        self,
        ctx: SlashContext,
        token: str,
        outcome: str,
        suggestions: tuple[service.Suggestion, ...],
    ) -> None:
        self.ctx = ctx
        self.token = token
        super().__init__(
            "Address suggestions",
            lambda: [
                PanelRow(item.id, item.title, item.subtitle) for item in suggestions
            ],
            on_select=self.resolve,
            empty=service.lookup_sentence(outcome),
        )

    def resolve(self, row: PanelRow) -> None:
        _worker(
            self.ctx,
            lambda: service.resolve_address(
                self.ctx.service.transport, row.key, self.token
            ),
            self.resolved,
        )

    def resolved(self, value: object) -> None:
        if isinstance(value, Refusal):
            self.ctx.app.notify(terminal_safe(value.message), markup=False)
        elif not isinstance(value, service.AddressParts):
            self.ctx.app.notify(service.UNRESOLVED, markup=False)
        else:
            parts = value
            self.ctx.app.push_screen(
                DetailPanel(
                    "Address",
                    lambda: Detail(service.address_fields(parts), body=parts.formatted),
                )
            )


class _Lookup(FormPanel):
    """Asks for the query; the search swaps this form for the suggestions."""

    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        self.token = service.new_session_token()
        super().__init__(
            "Address lookup",
            (FormField("query", "Address", required=True),),
            self.search,
            submit_label="Search",
        )

    def search(self, values: dict[str, str | bool]) -> None:
        query = str(values["query"]).strip()
        outcome, suggestions = service.suggest_addresses(
            self.ctx.service.transport, query, self.token
        )
        self.ctx.app.call_from_thread(self._show, outcome, suggestions)

    def _show(self, outcome: str, suggestions: tuple[service.Suggestion, ...]) -> None:
        if self.ctx.app.screen is not self:
            return
        self.ctx.app.pop_screen()
        self.ctx.app.push_screen(
            AddressPanel(self.ctx, self.token, outcome, suggestions)
        )

    def _submit_done(self, message: str) -> None:
        pass


def address(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(_Lookup(ctx))


def teach(ctx: SlashContext, args: str) -> None:
    ctx.app.notify("Teach recording runs in the Grok Bot desktop app.", markup=False)


COMMANDS = (
    SlashCommand(
        "analytics",
        "Show bot usage analytics",
        analytics,
        scope="session",
        needs_bot=True,
    ),
    SlashCommand("egress", "Show the network egress policy", egress),
    SlashCommand("payment", "Show the default payment method", payment),
    SlashCommand("address", "Look up an address", address),
    SlashCommand("teach", "Teach recording status", teach, scope="session"),
)
