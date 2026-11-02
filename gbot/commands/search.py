"""Search a bot's places card within a map area."""

import argparse

from gbot.context import Context
from gbot.service import search
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("search", help="Search places in a bot card")
    children = parser.add_subparsers(dest="search_action", required=True)
    places = children.add_parser("places", help="Search a places card in a map area")
    places.add_argument("agent_id", metavar="AGENT_ID")
    places.add_argument("entry_id", metavar="ENTRY_ID")
    places.add_argument("card_index", type=int, metavar="CARD_INDEX")
    places.add_argument("--south-west", metavar="LAT,LONG")
    places.add_argument("--north-east", metavar="LAT,LONG")
    places.add_argument("--session-id", default="")
    places.add_argument("--language", default="")
    places.add_argument("--json", action="store_true")
    places.set_defaults(func=run)


def _point(value: str | None) -> dict[str, float] | None:
    if value is None:
        return None
    try:
        latitude, longitude = (float(part) for part in value.split(","))
    except (ValueError, TypeError):
        raise ValueError("Coordinates must be LAT,LONG.") from None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError(
            "Coordinates are outside the valid latitude or longitude range."
        )
    return {"latitude": latitude, "longitude": longitude}


def run(args: argparse.Namespace, ctx: Context) -> int:
    result = search.places_area(
        ContextTransport(ctx),
        args.agent_id,
        args.entry_id,
        args.card_index,
        south_west=_point(args.south_west),
        north_east=_point(args.north_east),
        language=args.language,
        session_id=args.session_id,
    )
    ctx.out.write(
        {"outcome": result.outcome, "card": result.card},
        f"{result.outcome}" + (f"\n{result.card}" if result.card is not None else ""),
    )
    return 0 if result.outcome in {"found", "empty"} else 2
