"""Browse connector catalog entries and setup metadata."""

import argparse
from dataclasses import asdict

from gbot.context import Context
from gbot.service import plugins
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("catalog", help="Browse connector catalog")
    parser.add_argument("action", nargs="?", choices=("show",))
    parser.add_argument("entry", metavar="ENTRY", nargs="?")
    parser.add_argument("--category", metavar="KEY")
    parser.add_argument("--search", metavar="TEXT")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def field_text(field: plugins.Field) -> str:
    return (
        field.label
        + (" · required" if field.required else " · optional")
        + (" · secret" if field.secret else "")
    )


def run(args: argparse.Namespace, ctx: Context) -> int:
    if args.action == "show" and not args.entry:
        raise ValueError("Specify ENTRY.")
    entries = plugins.catalog(ContextTransport(ctx))
    if args.action == "show":
        entry = plugins.find_entry(entries, args.entry)
        ctx.out.write(
            asdict(entry),
            "\n".join(
                [
                    entry.display_name,
                    entry.description,
                    f"Publisher: {entry.publisher}",
                    "Connectors: " + ", ".join(entry.connector_names),
                    *[field_text(field) for field in entry.fields],
                ]
            ),
        )
        return 0
    if args.category:
        entries = [
            e
            for e in entries
            if args.category.casefold()
            in {c.casefold() for c in (e.category, *e.category_keys)}
        ]
    if args.search:
        entries = [
            e
            for e in entries
            if args.search.casefold()
            in f"{e.name} {e.display_name} {e.description}".casefold()
        ]
    ctx.out.write(
        [asdict(e) for e in entries],
        "\n".join(
            f"{e.display_name}  {e.category}  {e.publisher}  {len(e.connector_names)} connectors"
            for e in entries
        )
        or "No catalog entries",
    )
    return 0
