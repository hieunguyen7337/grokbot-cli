"""Who has the bot: the `/share` panel, and `/invite` for an invite you received."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from textual import events
from textual.css.query import NoMatches
from textual.timer import Timer
from textual.widgets import Input, Static

from gbot.output import terminal_safe
from gbot.service import sharing as service
from gbot.service.transport import Transport
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
from gbot.tui.slash.rooms import _refresh, _writable

Severity = Literal["information", "warning", "error"]
# Tests replace the clock to reach the polling deadline without waiting for it.
_clock = time.monotonic
_ROLE_LABELS = {"user": "User", "manager": "Manager"}


def _notice(
    ctx: SlashContext, message: str, severity: Severity = "information"
) -> None:
    ctx.app.notify(terminal_safe(message), severity=severity, markup=False)


def _when(stamp_ms: int) -> str:
    try:
        return datetime.fromtimestamp(stamp_ms / 1000, tz=UTC).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return "unknown"


def _cap(cap: service.CapUsage) -> str:
    return f"{cap.used} of {cap.limit}"


def _scrub(text: str, *secrets: str) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def _email_error(value: str) -> str | None:
    try:
        service.check_email(value)
    except ValueError as error:
        return str(error)
    return None


@dataclass(frozen=True)
class _Done:
    """What a finished change tells the person, and what the panel does next."""

    message: str = ""
    severity: Severity = "information"
    then: Callable[[], None] | None = None


def _outcome(outcome: str, good: str, then: Callable[[], None] | None = None) -> _Done:
    ok = outcome == good
    return _Done(
        service.sentence(outcome),
        "information" if ok else "warning",
        then if ok else None,
    )


class SharePanel(ListPanel):
    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        self.bot_id = ctx.bot_id or ""
        self.bot_label = terminal_safe(ctx.app.state.bots[self.bot_id].name)
        self.current = service.Overview()
        self.progress: service.InPlaceStatus | None = None
        self._timer: Timer | None = None
        self._delay: float | None = None
        self._started = 0.0
        super().__init__(
            f"Share {self.bot_label}", self.load_rows, empty="Nothing to show"
        )

    # Rows -------------------------------------------------------------------------------------------

    def load_rows(self) -> list[PanelRow]:
        current = service.overview(self.ctx.service.transport, self.bot_id)
        self.current = current
        return self.build_rows(current)

    def build_rows(self, view: service.Overview) -> list[PanelRow]:
        refused = view.refused
        access = view.access
        rows: list[PanelRow] = []

        def sentence_row(part: str, label: str) -> PanelRow:
            message = refused.get(part, "Not available.")
            return PanelRow(f"refused:{part}", f"{label}: {message}", tone="warn")

        if access is None:
            rows.append(sentence_row("access", "Access"))
        else:
            rows.append(
                PanelRow("owner", access.owner_label(), "person", "owner", "muted")
            )
            for principal in access.principals:
                if principal.kind == "team":
                    continue
                kind = service.kind_label(principal.kind).lower()
                group = access.groups.get(principal.ref or "")
                if group and group.member_count:
                    kind += f" · {group.member_count} members"
                rows.append(
                    PanelRow(
                        f"p:{principal.spec}",
                        access.describe(principal),
                        kind,
                        principal.role,
                        "warn" if principal.role == "manager" else "ok",
                    )
                )
            team = access.team_row()
            rows.append(
                PanelRow(
                    "team",
                    "Team row",
                    "everyone in the team",
                    f"on · {team.role}" if team else "off",
                    "ok" if team else "muted",
                )
            )
        if self.progress is not None:
            step = self.progress.step.replace("_", " ")
            rows.append(
                PanelRow(
                    "progress",
                    "Share in place",
                    f"step {step}" if step else "",
                    self.progress.state.replace("_", " "),
                    "warn",
                )
            )
        if view.link_access is None:
            rows.append(sentence_row("link_access", "Link access"))
        else:
            rows.append(
                PanelRow("link", "Link access", "", view.link_access.replace("_", " "))
            )
        if view.managers is None:
            rows.append(sentence_row("managers", "Managers"))
        elif not view.managers:
            rows.append(PanelRow("none:managers", "No managers", tone="muted"))
        else:
            rows.extend(
                PanelRow(
                    f"m:{user_id}",
                    access.person(user_id) if access else f"User #{user_id}",
                    "person · managers list",
                    "manager",
                )
                for user_id in view.managers
            )
        if view.invites is None:
            rows.append(sentence_row("invites", "Invites"))
        else:
            rows.extend(
                PanelRow(
                    f"i:{invite.email}",
                    invite.email,
                    "invited"
                    + (
                        f" · expires {_when(invite.expires_at_ms)}"
                        if invite.expires_at_ms
                        else ""
                    ),
                )
                for invite in view.invites
            )
            if not view.invites:
                rows.append(PanelRow("none:invites", "No invites", tone="muted"))
            if view.cap_usage:
                rows.append(
                    PanelRow("cap", "Invites used", "", _cap(view.cap_usage), "muted")
                )
        return rows

    # Keys that apply to the selected row ---------------------------------------------------------------

    def selected(self) -> PanelRow | None:
        rows = self.visible_rows
        return rows[self.index] if rows and self.index < len(rows) else None

    def principal(self, row: PanelRow | None) -> service.Principal | None:
        access = self.current.access
        if row is None or access is None or not row.key.startswith("p:"):
            return None
        return next((p for p in access.principals if f"p:{p.spec}" == row.key), None)

    def team_switch(self, access: service.AccessState) -> str:
        if access.team_row() is None:
            return "team row on"
        try:
            service.with_team_row(access, False)
        except ValueError:
            return ""
        return "team row off"

    def people_to_manage(self) -> dict[int, str]:
        access = self.current.access
        found: dict[int, str] = {}
        if access is not None:
            found.update(
                (user_id, name)
                for user_id, name in access.people.items()
                if user_id != access.creator_user_id
            )
        for user_id in self.current.managers or ():
            found.setdefault(
                user_id, access.person(user_id) if access else f"User #{user_id}"
            )
        return found

    def key_handlers(self) -> dict[str, Callable[[], None]]:
        return {
            "a": self.add_access,
            "r": self.change_role,
            "x": self.remove_access,
            "t": self.toggle_team,
            "v": self.make_visible,
            "p": self.share_in_place,
            "c": self.clone,
            "i": self.invite,
            "e": self.revoke_invite,
            "m": self.manage,
            "g": self.reload,
        }

    def applicable(self) -> list[tuple[str, str]]:
        view, access, row = self.current, self.current.access, self.selected()
        keys: list[tuple[str, str]] = []
        if access is not None:
            if self.candidates(access):
                keys.append(("a", "add"))
            on_team_row = row is not None and row.key == "team" and access.team_row()
            if (self.principal(row) or on_team_row) and len(access.available_roles) > 1:
                keys.append(("r", "role"))
            if self.principal(row):
                keys.append(("x", "remove"))
            switch = self.team_switch(access)
            if switch:
                keys.append(("t", switch))
        keys.append(("v", "team-visible"))
        if self.progress is None:
            keys.append(("p", "share in place"))
        keys.append(("c", "clone to team"))
        if view.invites is not None:
            keys.append(("i", "invite"))
            if row is not None and row.key.startswith("i:"):
                keys.append(("e", "revoke invite"))
        if view.managers is not None and self.people_to_manage():
            keys.append(("m", "managers"))
        keys.append(("g", "reload"))
        return keys

    def _draw(self) -> None:
        super()._draw()
        try:
            footer = self.query_one(".panel-footer", Static)
        except NoMatches:
            return
        from gbot.tui.app import GbotApp

        separator = cast(GbotApp, self.app).symbols.separator
        footer.styles.height = "auto"
        footer.update(
            f" {separator} ".join(
                [
                    "↑↓ select",
                    *(f"{key} {label}" for key, label in self.applicable()),
                    "esc back",
                ]
            )
        )

    def on_key(self, event: events.Key) -> None:
        handlers = self.key_handlers()
        if self.error or event.key not in handlers or isinstance(self.focused, Input):
            super().on_key(event)
            return
        if event.key in dict(self.applicable()):
            handlers[event.key]()
        event.stop()
        event.prevent_default()

    # Changing ---------------------------------------------------------------------------------------------

    def _change(self, question: str, work: Callable[[], _Done | None]) -> None:
        if not _writable(self.ctx):
            return

        def confirmed(ok: bool | None) -> None:
            if not ok or not _writable(self.ctx):
                return

            def run() -> None:
                try:
                    if self.ctx.app.read_only:
                        raise ValueError("Read-only mode")
                    done = work()
                except Exception as error:  # noqa: BLE001 - worker boundary
                    self.ctx.app.call_from_thread(self._failed, error)
                else:
                    self.ctx.app.call_from_thread(self._finished, done)

            self.ctx.app.run_worker(run, thread=True, exit_on_error=False)

        self.ctx.app.push_screen(
            ConfirmScreen(terminal_safe(question), "", "Confirm"), confirmed
        )

    def _failed(self, error: Exception) -> None:
        message = service.refused_message(error)
        _notice(self.ctx, message or str(error), "warning" if message else "error")
        if message:
            self.reload()

    def _finished(self, done: _Done | None) -> None:
        if done is not None and done.message:
            _notice(self.ctx, done.message, done.severity)
        if done is not None and done.then is not None:
            done.then()
        self.reload()

    def _update(
        self,
        question: str,
        edit: Callable[[service.AccessState], tuple[service.Principal, ...]],
    ) -> None:
        transport = self.ctx.service.transport

        def work() -> _Done:
            state = service.access(transport, self.bot_id)
            service.update_access(
                transport, self.bot_id, edit(state), state.expected_state_token
            )
            return _Done(f"Updated access to {self.bot_label}.")

        self._change(question, work)

    def _pick(
        self,
        title: str,
        rows: list[PanelRow],
        chosen: Callable[[PanelRow], None],
    ) -> None:
        def selected(row: PanelRow) -> None:
            self.ctx.app.pop_screen()
            # The next screen must be pushed by this panel: a screen pushed from the picker that is
            # closing would lose its result callback with it.
            self.call_later(chosen, row)

        self.ctx.app.push_screen(
            ListPanel(terminal_safe(title), lambda: rows, on_select=selected)
        )

    def _roles(self, access: service.AccessState, skip: str = "") -> list[PanelRow]:
        return [
            PanelRow(role, _ROLE_LABELS[role])
            for role in access.available_roles
            if role != skip
        ]

    def candidates(self, access: service.AccessState) -> list[PanelRow]:
        held = {p.key for p in access.principals}
        rows: list[PanelRow] = []
        if access.team_row() is None:
            rows.append(PanelRow("team", "Everyone in the team", "team"))
        if access.organization_name and ("organization", None) not in held:
            rows.append(
                PanelRow(
                    "organization",
                    f"Everyone in {access.organization_name}",
                    "organization",
                )
            )
        rows.extend(
            PanelRow(f"user:{user_id}", name, "person")
            for user_id, name in access.people.items()
            if user_id != access.creator_user_id and ("user", str(user_id)) not in held
        )
        rows.extend(
            PanelRow(
                f"group:{group_id}",
                group.name,
                "group"
                + (f" · {group.member_count} members" if group.member_count else ""),
            )
            for group_id, group in access.groups.items()
            if ("group", group_id) not in held
        )
        return rows

    def _grant_question(self, label: str, kind: str, role: str, adding: bool) -> str:
        if kind == "team" and role == "manager":
            return f"Make everyone in the team a manager of {self.bot_label}?"
        if role == "manager":
            return f"Make {label} a manager of {self.bot_label}?"
        verb = "Give" if adding else "Change"
        return f"{verb} {label} {'access to' if adding else 'to user on'} {self.bot_label}?"

    def add_access(self) -> None:
        if not _writable(self.ctx):
            return
        access = self.current.access
        rows = self.candidates(access) if access else []
        if access is None or not rows:
            _notice(self.ctx, "Nobody to add")
            return

        def role_chosen(target: PanelRow) -> None:
            def granted(role_row: PanelRow) -> None:
                role = role_row.key
                kind, _, ref = target.key.partition(":")
                principal = service.Principal(kind, ref or None, role)

                def edit(state: service.AccessState) -> tuple[service.Principal, ...]:
                    if kind == "team":
                        return service.with_team_row(state, True, role)
                    return service.with_principal(state.principals, principal)

                self._update(self._grant_question(target.label, kind, role, True), edit)

            roles = self._roles(access)
            if len(roles) == 1:
                granted(roles[0])
            else:
                self._pick(f"Role for {target.label}", roles, granted)

        self._pick(f"Add to {self.bot_label}", rows, role_chosen)

    def change_role(self) -> None:
        if not _writable(self.ctx):
            return
        access, row = self.current.access, self.selected()
        if access is None or row is None:
            return
        principal = self.principal(row)
        if principal is None and row.key == "team":
            principal = access.team_row()
        if principal is None:
            return
        target, label = (
            principal,
            row.label if row.key != "team" else "Everyone in the team",
        )

        def chosen(role_row: PanelRow) -> None:
            role = role_row.key

            def edit(state: service.AccessState) -> tuple[service.Principal, ...]:
                if target.kind == "team":
                    return service.with_team_row(state, True, role)
                return service.with_role(
                    state.principals, target.kind, target.ref, role
                )

            self._update(self._grant_question(label, target.kind, role, False), edit)

        roles = self._roles(access, skip=target.role)
        if len(roles) == 1:
            chosen(roles[0])
        elif roles:
            self._pick(f"Role for {label}", roles, chosen)

    def remove_access(self) -> None:
        if not _writable(self.ctx):
            return
        row = self.selected()
        principal = self.principal(row)
        if row is None or principal is None:
            return
        self._update(
            f"Remove {row.label} from {self.bot_label}?",
            lambda state: service.without_principal(
                state.principals, principal.kind, principal.ref
            ),
        )

    def toggle_team(self) -> None:
        if not _writable(self.ctx):
            return
        access = self.current.access
        if access is None:
            return
        on = access.team_row() is None
        try:
            service.with_team_row(access, on)
        except ValueError as error:
            _notice(self.ctx, str(error), "warning")
            return
        self._update(
            f"Turn {'on' if on else 'off'} the team row for {self.bot_label}?",
            lambda state: service.with_team_row(state, on),
        )

    def make_visible(self) -> None:
        transport = self.ctx.service.transport
        self._change(
            f"Make {self.bot_label} visible to your team?",
            lambda: _outcome(
                service.make_team_visible(transport, self.bot_id), "updated"
            ),
        )

    def share_in_place(self) -> None:
        transport = self.ctx.service.transport
        self._change(
            f"Share {self.bot_label} with your team in place?",
            lambda: _outcome(
                service.share_in_place(transport, self.bot_id),
                "started",
                self.start_polling,
            ),
        )

    def clone(self) -> None:
        transport = self.ctx.service.transport
        self._change(
            f"Clone {self.bot_label} to your team?",
            lambda: _outcome(
                service.clone_to_team(transport, self.bot_id).outcome, "cloned"
            ),
        )

    def invite(self) -> None:
        if _writable(self.ctx):
            self.ctx.app.push_screen(_InviteForm(self))

    def revoke_invite(self) -> None:
        if not _writable(self.ctx):
            return
        row = self.selected()
        if row is None or not row.key.startswith("i:"):
            return
        email, transport = row.key[2:], self.ctx.service.transport

        def work() -> _Done:
            count, cap = service.revoke_invite(transport, self.bot_id, email)
            return _Done(
                f"Revoked {count} invite{'' if count == 1 else 's'} for {email}."
                + (f" {_cap(cap)} invites used." if cap else "")
            )

        self._change(f"Revoke the invite for {email} to {self.bot_label}?", work)

    def manage(self) -> None:
        if not _writable(self.ctx):
            return
        people, held = self.people_to_manage(), set(self.current.managers or ())
        if not people:
            _notice(self.ctx, "Nobody to choose")
            return
        rows = [
            PanelRow(str(user_id), name, "person", "manager" if user_id in held else "")
            for user_id, name in people.items()
        ]
        transport = self.ctx.service.transport

        def chosen(row: PanelRow) -> None:
            user_id = int(row.key)
            if user_id in held:
                self._change(
                    f"Remove {row.label} as a manager of {self.bot_label}?",
                    lambda: self._manager(
                        service.remove_manager, transport, user_id, "Removed"
                    ),
                )
            else:
                self._change(
                    f"Make {row.label} a manager of {self.bot_label}?",
                    lambda: self._manager(
                        service.add_manager, transport, user_id, "Added"
                    ),
                )

        self._pick(f"Managers of {self.bot_label}", rows, chosen)

    def _manager(
        self,
        call: Callable[[Transport, str, int], None],
        transport: Transport,
        user_id: int,
        done: str,
    ) -> _Done:
        call(transport, self.bot_id, user_id)
        access = self.current.access
        return _Done(f"{done} manager {access.person(user_id) if access else user_id}.")

    # Sharing in place: poll with timers until done, failed or the deadline -------------------------------

    def start_polling(self) -> None:
        self._stop()
        self.progress = service.InPlaceStatus("running")
        self._started = _clock()
        self.rows = self.build_rows(self.current)
        self._draw()
        self._schedule()

    def _schedule(self) -> None:
        self._delay = service.next_poll_delay(self._delay)
        self._timer = self.set_timer(self._delay, self._tick)

    def _stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._timer, self._delay, self.progress = None, None, None

    def on_unmount(self) -> None:
        self._stop()

    def _tick(self) -> None:
        self._timer = None
        if self.progress is None:
            return
        if _clock() - self._started > service.POLL_DEADLINE_S:
            self._stop()
            _notice(
                self.ctx,
                "Sharing in place is still running after 45 minutes; open /share later to check.",
                "warning",
            )
            self.reload()
            return
        transport = self.ctx.service.transport

        def poll() -> None:
            try:
                status = service.in_place_status(transport, self.bot_id)
            except Exception as error:  # noqa: BLE001 - worker boundary
                self.ctx.app.call_from_thread(self._polled, None, error)
            else:
                self.ctx.app.call_from_thread(self._polled, status, None)

        self.ctx.app.run_worker(poll, thread=True, exit_on_error=False)

    def _polled(
        self, status: service.InPlaceStatus | None, error: Exception | None
    ) -> None:
        if self.progress is None:
            return
        if error is not None:
            message = service.refused_message(error)
            if message is None:
                # A transient failure: the share keeps running on the server, so read again.
                self._schedule()
                return
            self._stop()
            _notice(self.ctx, message, "warning")
            self.reload()
            return
        assert status is not None
        if status.state in ("done", "failed", "unknown"):
            self._stop()
            if status.state == "done":
                _notice(self.ctx, service.sentence("done"))
            elif status.state == "failed":
                reason = f": {status.failure_reason}" if status.failure_reason else "."
                _notice(
                    self.ctx,
                    service.sentence("failed").removesuffix(".") + reason,
                    "error",
                )
            else:
                _notice(self.ctx, service.sentence("unknown"), "warning")
            self.reload()
            return
        self.progress = status
        self.rows = self.build_rows(self.current)
        self._draw()
        self._schedule()


class _NoticeForm(FormPanel):
    """A form whose server refusals are shown as a plain notice, and other failures as errors."""

    ctx: SlashContext
    refused = False

    def refuse(self, error: Exception, *secrets: str) -> ValueError:
        message = service.refused_message(error)
        if message is None:
            raise error
        self.refused = True
        return ValueError(_scrub(message, *secrets))

    def _submit_error(self, message: str) -> None:
        text = terminal_safe(message)
        super()._submit_error(text)
        _notice(self.ctx, text, "warning" if self.refused else "error")


class _InviteForm(_NoticeForm):
    def __init__(self, panel: SharePanel) -> None:
        self.panel, self.ctx = panel, panel.ctx
        super().__init__(
            f"Invite to {panel.bot_label}",
            (
                FormField(
                    "email", "Email address", required=True, validate=_email_error
                ),
            ),
            self.save,
            submit_label="Invite",
        )

    def action_submit(self) -> None:
        if not _writable(self.ctx):
            return
        email = self.query_one("#form-0", Input).value.strip()
        if _email_error(email):
            # The form shows what is wrong; there is nothing to confirm yet.
            super().action_submit()
            return

        def confirmed(ok: bool | None) -> None:
            if ok and _writable(self.ctx):
                super(_InviteForm, self).action_submit()

        self.ctx.app.push_screen(
            ConfirmScreen(
                terminal_safe(f"Invite {email} to {self.panel.bot_label}?"),
                "",
                "Invite",
            ),
            confirmed,
        )

    def save(self, values: dict[str, str | bool]) -> str | None:
        email = str(values["email"]).strip()
        self.refused = False
        try:
            if self.ctx.app.read_only:
                raise ValueError("Read-only mode")
            result = service.create_invite(
                self.ctx.service.transport, self.panel.bot_id, email
            )
        except Exception as error:  # noqa: BLE001 - form boundary
            raise self.refuse(error) from None
        sent = result.invite.email or email
        return (
            f"Invited {sent}: "
            + ("email sent." if result.email_sent else "email not sent.")
            + (f" {_cap(result.cap_usage)} invites used." if result.cap_usage else "")
        )

    def _submit_done(self, message: str) -> None:
        super()._submit_done(message)
        self.panel.reload()


# A received invite ---------------------------------------------------------------------------------------


class _CodeForm(_NoticeForm):
    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        self.found: tuple[str, service.InvitePreview] | None = None
        super().__init__(
            "Accept an invite",
            (
                FormField(
                    "code",
                    "Invite code or link",
                    "password",
                    required=True,
                    hint="Paste the code or link from your invite",
                ),
            ),
            self.save,
            submit_label="Preview",
        )

    def save(self, values: dict[str, str | bool]) -> str | None:
        raw = str(values.pop("code", ""))
        code = service.invite_code(raw)
        self.refused = False
        try:
            preview = service.preview_invite(self.ctx.service.transport, code)
        except Exception as error:  # noqa: BLE001 - form boundary
            if service.refused_message(error) is None:
                raise ValueError(_scrub(str(error), raw, code)) from None
            raise self.refuse(error, raw, code) from None
        if not preview.found:
            raise ValueError("That invite was not found.")
        self.found = (code, preview)
        return None

    def _submit_done(self, message: str) -> None:
        super()._submit_done(message)
        found, self.found = self.found, None
        if found is not None:
            self.ctx.app.push_screen(InvitePanel(self.ctx, *found))


class InvitePanel(_Detail):
    def __init__(
        self, ctx: SlashContext, code: str, preview: service.InvitePreview
    ) -> None:
        self.ctx = ctx
        self._code = code
        self.preview = preview
        super().__init__("Invite", self.content)

    def acceptable(self) -> bool:
        preview = self.preview
        return (
            bool(self._code)
            and preview.found
            and any(item.state == "open" for item in preview.items)
            and preview.recipient_match != "does_not_match"
            and (preview.eligibility is None or preview.eligibility.eligible)
        )

    def content(self) -> Detail:
        preview = self.preview
        fields: list[tuple[str, str]] = []
        if preview.sender_name:
            fields.append(("From", preview.sender_name))
        for item in preview.items:
            fields.extend(
                (
                    ("Bot", item.bot_name or item.bot_id or "unknown"),
                    ("Role", item.role),
                    ("State", service.sentence(item.state or "unknown")),
                )
            )
            if item.expires_at_ms:
                fields.append(("Expires", _when(item.expires_at_ms)))
        eligibility = preview.eligibility
        if eligibility is None:
            fields.append(("Eligibility", "not reported"))
        elif eligibility.eligible:
            fields.append(("Eligibility", "eligible"))
        else:
            fields.append(
                ("Eligibility", service.sentence(eligibility.reason or "unknown"))
            )
        return Detail(
            tuple(fields),
            body=service.sentence(preview.recipient_match),
            actions=(PanelAction("a", "Accept", self.accept),)
            if self.acceptable()
            else (),
        )

    def accept(self) -> None:
        if not _writable(self.ctx) or not self.acceptable():
            return
        code = self._code
        names = ", ".join(
            item.bot_name or item.bot_id
            for item in self.preview.items
            if item.state == "open"
        )

        def confirmed(ok: bool | None) -> None:
            if not ok or not _writable(self.ctx):
                return

            def run() -> None:
                try:
                    if self.ctx.app.read_only:
                        raise ValueError("Read-only mode")
                    result = service.accept_invite(self.ctx.service.transport, code)
                except Exception as error:  # noqa: BLE001 - worker boundary
                    self.ctx.app.call_from_thread(self._failed, error)
                else:
                    self.ctx.app.call_from_thread(self._accepted, result)

            self.ctx.app.run_worker(run, thread=True, exit_on_error=False)

        self.ctx.app.push_screen(
            ConfirmScreen(
                terminal_safe(f"Accept access to {names or 'this bot'}?"), "", "Accept"
            ),
            confirmed,
        )

    def _failed(self, error: Exception) -> None:
        message = service.refused_message(error)
        _notice(
            self.ctx,
            _scrub(message or str(error), self._code),
            "warning" if message else "error",
        )

    def _accepted(self, result: service.AcceptResult) -> None:
        lines = [service.sentence(result.status)]
        lines.extend(
            f"{item.bot_name or item.bot_id}: {service.sentence(item.outcome or 'unknown')}"
            for item in result.items
        )
        redeemed = result.status == "redeemed"
        _notice(self.ctx, "\n".join(lines), "information" if redeemed else "warning")
        if redeemed:
            self._code = ""
            _refresh(self.ctx, lambda: None)
            if self.ctx.app.screen is self:
                self.ctx.app.pop_screen()


def share(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(SharePanel(ctx))


def invite(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(_CodeForm(ctx))


COMMANDS = (
    SlashCommand(
        "share",
        "See and change who has this bot",
        share,
        scope="session",
        needs_bot=True,
    ),
    SlashCommand("invite", "Accept an invite to a bot", invite),
)
