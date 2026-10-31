"""See and change who has a bot: access, team visibility, invites, managers, in-place share and clone."""

import argparse
import getpass
import re
import sys
import warnings
from dataclasses import replace
from datetime import UTC, datetime

from gbot.bots import resolve_bot
from gbot.commands.approvals import _confirm, _require_confirmation
from gbot.context import Context
from gbot.service import sharing
from gbot.service.transport import ContextTransport, Transport
from groken.client import ConnectError
from groken.errors import explain_error

_SPEC = re.compile(r"(team|user|group|other_team|organization)(?::(\d+))?")
_LANGUAGE = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*")
_NEEDS_ID = ("user", "group", "other_team")
_INT32_MAX = 2**31 - 1
_ACTIONS = (
    ("--grant / --revoke / --team-row", "access"),
    ("--team-visible", "team_visible"),
    ("--share-in-place", "share_in_place"),
    ("--share-status", "share_status"),
    ("--clone-to-team", "clone_to_team"),
    ("--invite", "invite"),
    ("--revoke-invite", "revoke_invite"),
    ("--add-manager", "add_manager"),
    ("--remove-manager", "remove_manager"),
    ("--preview-invite", "preview_invite"),
    ("--accept-invite", "accept_invite"),
)


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("share", help="See and change who has a bot")
    parser.add_argument("bot", metavar="BOT", nargs="?")
    parser.add_argument(
        "--grant", action="append", default=[], metavar="KIND[:ID]=ROLE"
    )
    parser.add_argument("--revoke", action="append", default=[], metavar="KIND[:ID]")
    parser.add_argument("--team-row", choices=("on", "off"))
    parser.add_argument("--role", choices=sharing.ROLES)
    parser.add_argument("--team-visible", action="store_true")
    parser.add_argument("--share-in-place", action="store_true")
    parser.add_argument("--share-status", action="store_true")
    parser.add_argument("--clone-to-team", action="store_true")
    parser.add_argument(
        "--carry-secret", action="append", nargs="+", default=[], metavar="NAME"
    )
    parser.add_argument("--invite", metavar="EMAIL")
    parser.add_argument("--language", metavar="TAG")
    parser.add_argument("--revoke-invite", metavar="EMAIL")
    parser.add_argument("--add-manager", type=int, metavar="USER_ID")
    parser.add_argument("--remove-manager", type=int, metavar="USER_ID")
    parser.add_argument("--preview-invite", action="store_true")
    parser.add_argument("--accept-invite", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def _when(stamp_ms: int) -> str:
    try:
        return datetime.fromtimestamp(stamp_ms / 1000, tz=UTC).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return "unknown"


def _expires(stamp_ms: int) -> str:
    return "expires " + _when(stamp_ms) if stamp_ms > 0 else "no expiry reported"


def _cap(cap: sharing.CapUsage | None) -> str:
    return f"{cap.used} of {cap.limit} invites used" if cap else "invite use unknown"


def _cap_json(cap: sharing.CapUsage | None) -> dict[str, int] | None:
    return {"used": cap.used, "limit": cap.limit} if cap else None


def _parse_spec(text: str) -> tuple[str, str | None]:
    match = _SPEC.fullmatch(text.strip().casefold().replace("-", "_"))
    if match is None:
        raise ValueError(
            f"Not an access row: {text!r}. Use KIND or KIND:ID with KIND one of "
            + ", ".join(sharing.KINDS)
            + "."
        )
    kind, number = match.groups()
    if (kind in _NEEDS_ID) != (number is not None):
        raise ValueError(
            f"{kind} rows take an id (user:12)."
            if kind in _NEEDS_ID
            else f"{kind} rows take no id."
        )
    if number is None:
        return kind, None
    if kind != "group" and int(number) > _INT32_MAX:
        raise ValueError(f"{kind} ids are at most {_INT32_MAX}.")
    return kind, str(int(number))


def _grants(args: argparse.Namespace) -> list[sharing.Principal]:
    found = []
    for text in args.grant:
        target, _, role = text.rpartition("=")
        if not target or role.strip().casefold() not in sharing.ROLES:
            raise ValueError(
                f"Use --grant KIND[:ID]=ROLE with ROLE user or manager: {text!r}"
            )
        kind, ref = _parse_spec(target)
        if kind == "team":
            raise ValueError("Use --team-row on [--role manager] for the team row.")
        found.append(sharing.Principal(kind, ref, role.strip().casefold()))
    return found


def _revokes(args: argparse.Namespace) -> list[tuple[str, str | None]]:
    found = [_parse_spec(text) for text in args.revoke]
    if any(kind == "team" for kind, _ in found):
        raise ValueError("Use --team-row off to remove the team row.")
    return found


def _chosen(args: argparse.Namespace) -> str | None:
    selected = {
        "access": bool(args.grant or args.revoke or args.team_row),
        "team_visible": args.team_visible,
        "share_in_place": args.share_in_place,
        "share_status": args.share_status,
        "clone_to_team": args.clone_to_team,
        "invite": args.invite is not None,
        "revoke_invite": args.revoke_invite is not None,
        "add_manager": args.add_manager is not None,
        "remove_manager": args.remove_manager is not None,
        "preview_invite": args.preview_invite,
        "accept_invite": args.accept_invite,
    }
    names = [label for label, key in _ACTIONS if selected[key]]
    if len(names) > 1:
        raise ValueError("Use one action at a time: " + ", ".join(names) + ".")
    return next((key for _, key in _ACTIONS if selected[key]), None)


def _validate(args: argparse.Namespace, action: str | None) -> list[str]:
    secrets = [name.strip() for group in args.carry_secret for name in group]
    if any(not name for name in secrets):
        raise ValueError("Secret names must not be empty.")
    if args.team_row != "on" and args.role:
        raise ValueError("Use --role with --team-row on.")
    if args.language and action != "invite":
        raise ValueError("Use --language with --invite.")
    if secrets and action not in ("clone_to_team", "team_visible"):
        raise ValueError("Use --carry-secret with --clone-to-team or --team-visible.")
    if args.language and not _LANGUAGE.fullmatch(args.language):
        raise ValueError("A language tag looks like en or pt-BR.")
    if action in ("preview_invite", "accept_invite"):
        if args.bot:
            raise ValueError("The invite options take no BOT.")
    elif not args.bot:
        raise ValueError("Specify BOT.")
    return secrets


def _access_json(state: sharing.AccessState) -> dict[str, object]:
    return {
        "owner": state.owner_label(),
        "creator_user_id": state.creator_user_id,
        "viewer_user_id": state.viewer_user_id,
        "team_row_on": state.team_row_on,
        "team_row_off_allowed": state.team_row_off_allowed,
        "available_roles": list(state.available_roles),
        "principals": [
            {
                "kind": p.kind,
                "id": p.ref,
                "name": state.describe(p),
                "role": p.role,
                **(
                    {"invited_as_email": p.invited_as_email}
                    if p.invited_as_email
                    else {}
                ),
            }
            for p in state.principals
        ],
    }


def _access_text(state: sharing.AccessState) -> list[str]:
    team = state.team_row()
    lines = [
        "Owner: " + state.owner_label(),
        "Team row: " + (f"on ({team.role})" if team else "off"),
    ]
    rows = [
        (p.spec, state.describe(p), p.role)
        for p in state.principals
        if p.kind != "team"
    ]
    if rows:
        width = max(len(spec) for spec, _, _ in rows)
        lines.append("Access:")
        lines.extend(f"  {spec:<{width}}  {name}  {role}" for spec, name, role in rows)
    else:
        lines.append("Access: nobody besides the owner")
    return lines


def _managers_text(managers: tuple[int, ...], state: sharing.AccessState | None) -> str:
    people = state.person if state else (lambda ref: f"User #{ref}")
    return ", ".join(f"{people(user_id)} ({user_id})" for user_id in managers) or "none"


def _overview(
    args: argparse.Namespace, ctx: Context, transport: Transport, bot: tuple[str, str]
) -> int:
    bot_id, bot_name = bot
    view = sharing.overview(transport, bot_id)
    refused = view.refused
    payload: dict[str, object] = {"bot": {"id": bot_id, "name": bot_name}}
    lines = [f"Share {bot_name}"]
    if view.access is not None:
        payload["access"] = _access_json(view.access)
        lines.extend(_access_text(view.access))
    else:
        payload["access"] = {"refused": refused["access"]}
        lines.append("Access: " + refused["access"])
    if view.link_access is not None:
        payload["link_access"] = view.link_access
        lines.append("Link access: " + view.link_access)
    else:
        payload["link_access"] = {"refused": refused["link_access"]}
        lines.append("Link access: " + refused["link_access"])
    if view.managers is not None:
        payload["managers"] = [
            {
                "user_id": user_id,
                "name": view.access.people.get(user_id) if view.access else None,
            }
            for user_id in view.managers
        ]
        lines.append("Managers: " + _managers_text(view.managers, view.access))
    else:
        payload["managers"] = {"refused": refused["managers"]}
        lines.append("Managers: " + refused["managers"])
    if view.invites is not None:
        payload["invites"] = {
            "invites": [
                {
                    "email": invite.email,
                    "expires_at_ms": invite.expires_at_ms,
                    "last_shared_at_ms": invite.last_shared_at_ms,
                    "created_at_ms": invite.created_at_ms,
                }
                for invite in view.invites
            ],
            "cap_usage": _cap_json(view.cap_usage),
        }
        lines.append(
            "Invites: " + (_cap(view.cap_usage) if view.cap_usage else "none sent")
        )
        lines.extend(
            f"  {invite.email}  {_expires(invite.expires_at_ms)}"
            for invite in view.invites
        )
    else:
        payload["invites"] = {"refused": refused["invites"]}
        lines.append("Invites: " + refused["invites"])
    ctx.out.write(payload, "\n".join(lines))
    return 0


def _change_access(
    args: argparse.Namespace,
    ctx: Context,
    transport: Transport,
    bot: tuple[str, str],
    grants: list[sharing.Principal],
    revokes: list[tuple[str, str | None]],
) -> int:
    bot_id, bot_name = bot
    state = sharing.access(transport, bot_id)
    principals = state.principals
    if {g.key for g in grants} & set(revokes):
        raise ValueError("An access row cannot be both granted and revoked.")
    for kind, ref in revokes:
        try:
            principals = sharing.without_principal(principals, kind, ref)
        except ValueError:
            raise ValueError(
                f"{sharing.Principal(kind, ref).spec} does not have access to {bot_name}."
            ) from None
    for grant in grants:
        principals = sharing.with_principal(principals, grant)
    if args.team_row:
        staged = replace(state, principals=principals)
        existing = staged.team_row()
        # Without --role, an existing team row keeps its role: "on" must not demote a manager row.
        role = args.role or (existing.role if existing else "user")
        principals = sharing.with_team_row(staged, args.team_row == "on", role)
    if principals == state.principals:
        ctx.out.write({"changed": False, **_access_json(state)}, "No change.")
        return 0
    updated = sharing.update_access(
        transport, bot_id, principals, state.expected_state_token
    )
    ctx.out.write(
        {"changed": True, **_access_json(updated)},
        "\n".join((f"Updated access to {bot_name}.", *_access_text(updated))),
    )
    return 0


def _outcome(
    ctx: Context, outcome: str, good: str, extra: dict[str, object] | None = None
) -> int:
    message = sharing.sentence(outcome)
    if outcome != good:
        # A refused change reports its sentence on the error channel, as every other refusal does.
        raise ValueError(message)
    ctx.out.write({"outcome": outcome, "message": message, **(extra or {})}, message)
    return 0


def _status(ctx: Context, transport: Transport, bot: tuple[str, str]) -> int:
    status = sharing.in_place_status(transport, bot[0])
    text = sharing.sentence(status.state)
    if status.step:
        text += f" Step: {status.step.replace('_', ' ')}."
    if status.state == "failed" and status.failure_reason:
        text += f" Reason: {status.failure_reason}"
    ctx.out.write(
        {
            "state": status.state,
            "step": status.step,
            "failure_reason": status.failure_reason,
            "shared": status.shared,
            "message": sharing.sentence(status.state),
        },
        text,
    )
    return 0


def _invite(
    args: argparse.Namespace, ctx: Context, transport: Transport, bot: tuple[str, str]
) -> int:
    result = sharing.create_invite(
        transport, bot[0], args.invite, language=args.language
    )
    email = result.invite.email or args.invite.strip()
    ctx.out.write(
        {
            "email": email,
            "created": result.created,
            "email_sent": result.email_sent,
            "expires_at_ms": result.invite.expires_at_ms,
            "grace_ms": result.grace_ms,
            "cap_usage": _cap_json(result.cap_usage),
        },
        "\n".join(
            (
                f"Invite for {email}: "
                + ("created" if result.created else "already invited")
                + "; "
                + ("email sent" if result.email_sent else "email not sent"),
                _expires(result.invite.expires_at_ms).capitalize()
                + "; "
                + _cap(result.cap_usage),
            )
        ),
    )
    return 0


def _revoke_invite(
    args: argparse.Namespace, ctx: Context, transport: Transport, bot: tuple[str, str]
) -> int:
    count, cap = sharing.revoke_invite(transport, bot[0], args.revoke_invite)
    ctx.out.write(
        {"revoked_count": count, "cap_usage": _cap_json(cap)},
        (
            f"Revoked {count} invite" + ("" if count == 1 else "s")
            if count
            else "No invite to revoke"
        )
        + f" for {args.revoke_invite.strip()}; "
        + _cap(cap),
    )
    return 0


def _manager(
    args: argparse.Namespace, ctx: Context, transport: Transport, bot: tuple[str, str]
) -> int:
    if args.add_manager is not None:
        sharing.add_manager(transport, bot[0], args.add_manager)
        user_id, done = args.add_manager, "added"
    else:
        sharing.remove_manager(transport, bot[0], args.remove_manager)
        user_id, done = args.remove_manager, "removed"
    ctx.out.write(
        {"user_id": user_id, done: True}, f"Manager {user_id} {done} on {bot[1]}."
    )
    return 0


def _read_invite() -> tuple[str, str]:
    """The pasted code or link from a hidden prompt, or one stdin line without a terminal."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            text = (
                getpass.getpass("Invite code or link (hidden): ")
                if sys.stdin.isatty()
                else sys.stdin.readline()
            )
    except getpass.GetPassWarning:
        raise ValueError(
            "This terminal cannot hide input; pipe the invite on stdin instead."
        ) from None
    text = text.strip()
    code = sharing.invite_code(text)
    if not code:
        raise ValueError("No invite code given.")
    return text, code


def _redacted(error: Exception, *secrets: str) -> ValueError:
    message = sharing.refused_message(error) or explain_error(error, cli="gbot")
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[redacted]")
    return ValueError(message)


def _item_json(item: sharing.InviteItem) -> dict[str, object]:
    return {
        "bot_id": item.bot_id,
        "bot_name": item.bot_name,
        "role": item.role,
        "state": item.state,
        "outcome": item.outcome,
        "expires_at_ms": item.expires_at_ms,
    }


def _preview(ctx: Context, transport: Transport) -> int:
    raw, code = _read_invite()
    try:
        preview = sharing.preview_invite(transport, code)
    except Exception as error:  # noqa: BLE001 - the code must not reach any message
        raise _redacted(error, raw, code) from None
    eligibility = preview.eligibility
    payload = {
        "found": preview.found,
        "recipient_match": preview.recipient_match,
        "sender": preview.sender_name,
        "items": [_item_json(item) for item in preview.items],
        "eligibility": {
            "eligible": eligibility.eligible,
            "reason": eligibility.reason,
            "current_tier": eligibility.current_tier,
        }
        if eligibility
        else None,
    }
    if not preview.found:
        ctx.out.write(payload, "That invite was not found.")
        return 1
    lines = [
        "Invite from " + preview.sender_name if preview.sender_name else "Invite",
        *(
            f"Bot: {item.bot_name or item.bot_id} · role {item.role} · "
            f"{sharing.sentence(item.state).rstrip('.')} · {_expires(item.expires_at_ms)}"
            for item in preview.items
        ),
        sharing.sentence(preview.recipient_match),
    ]
    if eligibility is not None:
        lines.append(
            "You can accept this invite."
            if eligibility.eligible
            else sharing.sentence(eligibility.reason or "unspecified")
        )
    ctx.out.write(payload, "\n".join(lines))
    return 0


def _accept(ctx: Context, transport: Transport) -> int:
    raw, code = _read_invite()
    try:
        result = sharing.accept_invite(transport, code)
    except Exception as error:  # noqa: BLE001 - the code must not reach any message
        raise _redacted(error, raw, code) from None
    message = sharing.sentence(result.status)
    ctx.out.write(
        {
            "status": result.status,
            "message": message,
            "items": [_item_json(item) for item in result.items],
        },
        "\n".join(
            (
                message,
                *(
                    f"{item.bot_name or item.bot_id}: {sharing.sentence(item.outcome or 'unknown')}"
                    for item in result.items
                ),
            )
        ),
    )
    return 0 if result.status == "redeemed" else 1


def run(args: argparse.Namespace, ctx: Context) -> int:
    action = _chosen(args)
    secrets = _validate(args, action)
    # Reading the rows is part of validating them: a bad one must fail before anything is sent.
    grants, revokes = (
        (_grants(args), _revokes(args)) if action == "access" else ([], [])
    )
    if action not in (None, "share_status", "preview_invite"):
        _require_confirmation(args.yes)
        _confirm(args.yes, json_mode=args.json)
    transport = ContextTransport(ctx)
    if action == "preview_invite":
        return _preview(ctx, transport)
    if action == "accept_invite":
        return _accept(ctx, transport)
    try:
        bot = resolve_bot(ctx, args.bot)
        if action is None:
            return _overview(args, ctx, transport, bot)
        if action == "access":
            return _change_access(args, ctx, transport, bot, grants, revokes)
        if action == "team_visible":
            return _outcome(
                ctx, sharing.make_team_visible(transport, bot[0], secrets), "updated"
            )
        if action == "share_in_place":
            outcome = sharing.share_in_place(transport, bot[0])
            return _outcome(ctx, outcome, "started")
        if action == "share_status":
            return _status(ctx, transport, bot)
        if action == "clone_to_team":
            cloned = sharing.clone_to_team(transport, bot[0], secrets)
            return _outcome(
                ctx, cloned.outcome, "cloned", {"agent_id": cloned.agent_id}
            )
        if action == "invite":
            return _invite(args, ctx, transport, bot)
        if action == "revoke_invite":
            return _revoke_invite(args, ctx, transport, bot)
        return _manager(args, ctx, transport, bot)
    except ConnectError as error:
        message = sharing.refused_message(error)
        if message is None:
            raise
        raise ValueError(message) from None
