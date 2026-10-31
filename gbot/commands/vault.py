"""Account vault commands; passwords never travel through argv."""

import argparse
import getpass
import sys
import warnings
from dataclasses import asdict

from gbot.context import Context
from gbot.service import vault
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "vault", help="Manage account vault and sign-in metadata"
    )
    action = parser.add_mutually_exclusive_group()
    for flag in (
        "add-login",
        "payment-methods",
        "passkeys",
        "onepassword",
        "onepassword-sync",
    ):
        action.add_argument("--" + flag, action="store_true")
    for flag in ("update-login", "delete", "revoke-passkey", "onepassword-disconnect"):
        action.add_argument("--" + flag, metavar="ID")
    # None means "not given": an update keeps the login's current value.
    parser.add_argument("--title")
    parser.add_argument("--username")
    parser.add_argument("--site", action="append")
    parser.add_argument("--notes")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def _save(args: argparse.Namespace, transport: ContextTransport) -> None:
    title, username, notes, sites = "", "", "", ()
    if args.update_login:
        current = next(
            (
                item
                for item in vault.list_items(transport)
                if item.id == args.update_login and item.kind == "login"
            ),
            None,
        )
        if current is None:
            raise ValueError("No login with that id.")
        title, username, notes, sites = (
            current.title,
            current.username,
            current.notes,
            current.sites,
        )
        print("Enter the password again to update this login.", file=sys.stderr)
    password = ""
    try:
        if sys.stdin.isatty():
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                password = getpass.getpass("Password (hidden): ")
        else:
            password = sys.stdin.readline().rstrip("\r\n")
    except getpass.GetPassWarning:
        raise ValueError(
            "This terminal cannot hide input; pipe the password on stdin instead."
        ) from None
    try:
        # put_login redacts transport failures; its own refusals name no password.
        vault.put_login(
            transport,
            id=args.update_login,
            title=title if args.title is None else args.title,
            username=username if args.username is None else args.username,
            password=password,
            notes=notes if args.notes is None else args.notes,
            sites=sites if args.site is None else args.site,
        )
    finally:
        password = ""


def run(args: argparse.Namespace, ctx: Context) -> int:
    mutation = bool(
        args.add_login
        or args.update_login
        or args.delete
        or args.revoke_passkey
        or args.onepassword_sync
        or args.onepassword_disconnect
    )
    if mutation and not args.yes:
        raise ValueError("Re-run with --yes to confirm")
    transport = ContextTransport(ctx)
    if args.add_login or args.update_login:
        _save(args, transport)
        ctx.out.write({"saved": True}, "Login saved.")
    elif args.delete:
        vault.delete_item(transport, args.delete)
        ctx.out.write({"deleted": True}, "Vault item deleted.")
    elif args.revoke_passkey:
        vault.revoke_passkey(transport, args.revoke_passkey)
        ctx.out.write({"revoked": True}, "Passkey revoked.")
    elif args.payment_methods:
        outcome, rows, count = vault.payment_methods(transport)
        ctx.out.write(
            {
                "outcome": outcome,
                "payment_methods": [asdict(r) for r in rows],
                "unavailable_count": count,
            },
            "\n".join(
                [
                    f"Payment methods: {outcome}",
                    *(f"{r.name}: {r.brand} ··{r.last4}" for r in rows),
                    "Add or edit payment methods in the Grok Bot app.",
                ]
            ),
        )
    elif args.passkeys:
        keys = vault.list_passkeys(transport)
        ctx.out.write(
            [asdict(r) for r in keys],
            "\n".join(f"{r.credential_id}  {r.name}  {r.device_type}" for r in keys)
            or "No passkeys. Add passkeys in the Grok Bot app.",
        )
    elif args.onepassword or args.onepassword_sync or args.onepassword_disconnect:
        state = (
            vault.sync_onepassword(transport)
            if args.onepassword_sync
            else vault.delete_onepassword(transport, args.onepassword_disconnect)
            if args.onepassword_disconnect
            else vault.onepassword_state(transport)
        )
        ctx.out.write(
            asdict(state),
            "\n".join(
                f"{r.connection_id}  {r.account_email}  {r.vault_name}  {r.item_count} items  {r.lifecycle_state}"
                for r in state.connections
            )
            or "Connect 1Password in the Grok Bot app",
        )
    else:
        items = vault.list_items(transport)
        ctx.out.write(
            [
                {**asdict(r), "card": {"brand": r.card.brand, "last4": r.card.last4}}
                if r.card
                else asdict(r)
                for r in items
            ],
            "\n".join(
                f"{r.id}  {r.kind}  {r.title}  "
                + (
                    f"{r.card.brand} ··{r.card.last4}"
                    if r.card
                    else f"{r.username}  {', '.join(r.sites)}"
                )
                for r in items
            )
            or "Vault is empty.",
        )
    return 0
