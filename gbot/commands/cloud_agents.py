"""Cloud agents, their published apps, app secret names and publish proposals."""

import argparse
import getpass
import sys
import warnings
from collections.abc import Callable
from dataclasses import asdict

from gbot.bots import resolve_bot
from gbot.context import Context
from gbot.service import cloud_agents
from gbot.service.errors import refusal
from gbot.service.transport import ContextTransport
from groken.client import ConnectError

_VISIBILITY = ("private", "team", "public")


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("apps", help="Manage published cloud-agent apps")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--update", metavar="BC_ID")
    actions.add_argument("--unpublish", metavar="BC_ID")
    parser.add_argument("--slug")
    parser.add_argument("--apex")
    parser.add_argument("--visibility", choices=_VISIBILITY)
    parser.add_argument("--mute-redeploy-prompts", action="store_true")
    parser.add_argument("--require-confirmation", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run_apps)

    parser = subparsers.add_parser(
        "cloud-agent", help="Read or stop a cloud agent and manage its app"
    )
    parser.add_argument("bc_id", metavar="BC_ID")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--conversation", action="store_true")
    actions.add_argument("--stop", action="store_true")
    actions.add_argument("--proposals", action="store_true")
    actions.add_argument("--confirm-proposal", metavar="ID")
    actions.add_argument("--dismiss-proposal", metavar="ID")
    actions.add_argument("--secrets", metavar="DIR")
    actions.add_argument("--set-secret", metavar="NAME", action="append")
    parser.add_argument("--files", action="store_true")
    parser.add_argument("--artifacts", action="store_true")
    parser.add_argument("--bot", metavar="BOT")
    parser.add_argument("--slug")
    parser.add_argument("--visibility", choices=_VISIBILITY)
    parser.add_argument("--require-confirmation", action="store_true")
    parser.add_argument("--project-dir", metavar="DIR")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run_cloud_agent)


def _read(ctx: Context, work: Callable[[], object]) -> object | None:
    """A refused read is a plain sentence, not an error."""
    try:
        return work()
    except ConnectError as error:
        found = refusal(error)
        if found is None:
            raise
        ctx.out.write({"refused": found.code, "message": found.message}, found.message)
        return None


def _change(work: Callable[[], object]) -> object:
    """A refused change exits 1 with the server's own message."""
    try:
        return work()
    except ConnectError as error:
        found = refusal(error)
        if found is None:
            raise
        raise ValueError(found.message) from None


def _write_result(ctx: Context, result: object, done: str) -> int:
    assert isinstance(result, cloud_agents.AppResult)
    ctx.out.write(asdict(result), result.message or (done if result.ok else "Refused."))
    return 0 if result.ok else 1


def _app_row(app: cloud_agents.PublishedApp) -> dict[str, object]:
    # The app URL stays out of output: replies' links are treated as secrets.
    return {
        "bc_id": app.bc_id,
        "slug": app.slug,
        "apex": app.apex,
        "visibility": app.visibility,
    }


def run_apps(args: argparse.Namespace, ctx: Context) -> int:
    change = args.update or args.unpublish
    if change and not args.yes:
        raise ValueError("Re-run with --yes to confirm")
    if change and not (args.slug and args.apex):
        raise ValueError("Use --slug and --apex with --update or --unpublish.")
    if args.update and not args.visibility:
        raise ValueError("Use --visibility with --update.")
    if not args.update and (
        args.visibility or args.mute_redeploy_prompts or args.require_confirmation
    ):
        raise ValueError(
            "Use --visibility, --mute-redeploy-prompts and --require-confirmation with --update."
        )
    if not change and (args.slug or args.apex):
        raise ValueError("Use --slug and --apex with --update or --unpublish.")
    transport = ContextTransport(ctx)
    if args.update:
        result = _change(
            lambda: cloud_agents.update_app(
                transport,
                args.update,
                args.slug,
                args.apex,
                args.visibility,
                mute_redeploy_prompts=args.mute_redeploy_prompts,
                require_confirmation_for_updates=args.require_confirmation,
            )
        )
        return _write_result(ctx, result, f"Updated app {args.slug}.")
    if args.unpublish:
        result = _change(
            lambda: cloud_agents.unpublish_app(
                transport, args.unpublish, args.slug, args.apex
            )
        )
        return _write_result(ctx, result, f"Unpublished app {args.slug}.")
    state = _read(ctx, lambda: cloud_agents.apps(transport))
    if isinstance(state, cloud_agents.AppsState):
        ctx.out.write(
            {"kind": state.kind, "apps": [_app_row(app) for app in state.apps]},
            "\n".join(
                f"{app.slug}  {app.apex}  {app.visibility}  {app.bc_id}"
                for app in state.apps
            )
            or state.sentence,
        )
    return 0


def _read_values(names: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            for name in names:
                values[name] = (
                    getpass.getpass(f"Value for {name} (hidden): ")
                    if sys.stdin.isatty()
                    else sys.stdin.readline().rstrip("\r\n")
                )
                if not values[name]:
                    raise ValueError(f"No value for {name}.")
    except getpass.GetPassWarning:
        values.clear()
        raise ValueError(
            "This terminal cannot hide input; pipe the values on stdin instead."
        ) from None
    except BaseException:
        values.clear()
        raise
    return values


def run_cloud_agent(args: argparse.Namespace, ctx: Context) -> int:
    change = bool(
        args.stop or args.confirm_proposal or args.dismiss_proposal or args.set_secret
    )
    if change and not args.yes:
        raise ValueError("Re-run with --yes to confirm")
    if args.confirm_proposal and not (args.bot and args.slug and args.visibility):
        raise ValueError("Use --bot, --slug and --visibility with --confirm-proposal.")
    if args.bot and not (args.confirm_proposal or args.dismiss_proposal):
        raise ValueError("Use --bot with --confirm-proposal or --dismiss-proposal.")
    if not args.confirm_proposal and (
        args.slug or args.visibility or args.require_confirmation
    ):
        raise ValueError(
            "Use --slug, --visibility and --require-confirmation with --confirm-proposal."
        )
    if bool(args.set_secret) != bool(args.project_dir):
        raise ValueError("Use --set-secret NAME with --project-dir DIR.")
    reading_info = not any(
        (
            args.conversation,
            args.proposals,
            args.secrets,
            change,
        )
    )
    if (args.files or args.artifacts) and not reading_info:
        raise ValueError("Use --files and --artifacts when reading the cloud agent.")
    transport = ContextTransport(ctx)
    bc_id = args.bc_id
    if args.stop:
        _change(lambda: cloud_agents.stop(transport, bc_id))
        ctx.out.write({"bc_id": bc_id, "stopped": True}, f"Stopped {bc_id}.")
        return 0
    if args.confirm_proposal:
        bot_id, _ = resolve_bot(ctx, args.bot)
        result = _change(
            lambda: cloud_agents.confirm_proposal(
                transport,
                bot_id,
                bc_id,
                args.confirm_proposal,
                args.slug,
                args.visibility,
                args.require_confirmation,
            )
        )
        return _write_result(ctx, result, f"Confirmed publishing {args.slug}.")
    if args.dismiss_proposal:
        bot_id = resolve_bot(ctx, args.bot)[0] if args.bot else None
        result = _change(
            lambda: cloud_agents.dismiss_proposal(
                transport, bc_id, args.dismiss_proposal, bot_id
            )
        )
        return _write_result(ctx, result, "Dismissed the proposal.")
    if args.set_secret:
        names = list(dict.fromkeys(args.set_secret))
        values = _read_values(names)
        try:
            saved = _change(
                lambda: cloud_agents.set_app_secrets(
                    transport, bc_id, args.project_dir, values
                )
            )
        finally:
            values.clear()
        assert isinstance(saved, cloud_agents.SetResult)
        cloud_agents.tell_secrets_set(
            transport,
            bc_id,
            args.project_dir,
            saved.saved,
            saved.refused,
            saved.apply_needed,
        )
        ctx.out.write(
            asdict(saved),
            "\n".join(
                (
                    *(f"Saved {name}." for name in saved.saved),
                    *(
                        f"{item.name}: {item.message or item.kind.replace('_', ' ')}"
                        for item in saved.refused
                    ),
                    *(
                        ("Apply the secrets in the app to use them.",)
                        if saved.apply_needed
                        else ()
                    ),
                )
            )
            or "Nothing saved.",
        )
        return 1 if saved.refused else 0
    if args.secrets:
        names = _read(
            ctx, lambda: cloud_agents.app_secret_names(transport, bc_id, args.secrets)
        )
        if isinstance(names, tuple):
            ctx.out.write(list(names), "\n".join(names) or "No app secrets.")
        return 0
    if args.conversation:
        messages = _read(ctx, lambda: cloud_agents.conversation(transport, bc_id))
        if isinstance(messages, tuple):
            ctx.out.write(
                [asdict(message) for message in messages],
                "\n".join(f"{m.role}: {m.text}" for m in messages) or "No messages.",
            )
        return 0
    if args.proposals:
        rows = _read(ctx, lambda: cloud_agents.proposals(transport, bc_id))
        if isinstance(rows, tuple):
            ctx.out.write(
                [asdict(row) for row in rows],
                "\n".join(
                    f"{p.proposal_id}  {p.slug}  {p.visibility}  {p.summary}".rstrip()
                    for p in rows
                )
                or "No publish proposals.",
            )
        return 0
    found = _read(
        ctx,
        lambda: (
            cloud_agents.info(
                transport,
                bc_id,
                include_files=args.files,
                include_artifacts=args.artifacts,
            )
            or cloud_agents.NOT_FOUND
        ),
    )
    if found == cloud_agents.NOT_FOUND:
        ctx.out.write(None, cloud_agents.NOT_FOUND)
    elif isinstance(found, cloud_agents.CloudAgentInfo):
        ctx.out.write(
            asdict(found),
            "\n".join(f"{label}: {value}" for label, value in found.fields),
        )
    return 0
