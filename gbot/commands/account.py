"""Account reads: egress policy, bot analytics, default payment method and address lookup."""

import argparse
from dataclasses import asdict
from typing import NoReturn

from gbot.bots import resolve_bot
from gbot.context import Context
from gbot.service import account as service
from gbot.service.errors import Refusal
from gbot.service.transport import ContextTransport, Transport


def _refusal(refused: Refusal) -> NoReturn:
    # A refused read fails with the server's own sentence, as a refused change does.
    raise ValueError(refused.message)


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "account", help="Egress, analytics, payment method and address lookup"
    )
    children = parser.add_subparsers(dest="view", required=True)
    for name, help_text in (
        ("egress", "Show the cloud computer's network policy"),
        ("analytics", "Show a bot's usage analytics"),
        ("payment", "Show the default payment method"),
        ("address", "Look up an address"),
    ):
        child = children.add_parser(name, help=help_text)
        if name == "analytics":
            child.add_argument("bot", metavar="BOT")
        elif name == "address":
            child.add_argument("query", metavar="QUERY")
            child.add_argument(
                "--pick", type=int, metavar="N", help="Resolve suggestion N"
            )
        child.add_argument("--json", action="store_true")
        child.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    transport = ContextTransport(ctx)
    if args.view == "egress":
        return _egress(ctx, transport)
    if args.view == "analytics":
        return _analytics(ctx, transport, args.bot)
    if args.view == "payment":
        return _payment(ctx, transport)
    return _address(ctx, transport, args.query, args.pick)


def _egress(ctx: Context, transport: Transport) -> int:
    policy = service.egress_policy(transport)
    if isinstance(policy, Refusal):
        _refusal(policy)
    ctx.out.write(
        {
            "restricted": policy.restricted,
            "allowed_domains": list(policy.allowed_domains),
            "allowed_tcp": [
                {"cidr": cidr, "port": port} for cidr, port in policy.allowed_tcp
            ],
        },
        "\n".join(
            (
                *(
                    f"{label}: {value}"
                    for label, value in service.egress_fields(policy)
                ),
                *service.egress_lines(policy),
            )
        ),
    )
    return 0


def _analytics(ctx: Context, transport: Transport, requested: str) -> int:
    bot_id, _ = resolve_bot(ctx, requested)
    value = service.analytics(transport, bot_id)
    if isinstance(value, Refusal):
        _refusal(value)
    if value is None:
        ctx.out.write(None, service.NO_ANALYTICS)
        return 0
    ctx.out.write(
        asdict(value),
        "\n".join(
            (
                *(
                    f"{label}: {text}"
                    for label, text in service.analytics_fields(value)
                ),
                "",
                *service.analytics_lines(value),
            )
        ),
    )
    return 0


def _payment(ctx: Context, transport: Transport) -> int:
    method = service.default_payment_method(transport)
    if isinstance(method, Refusal):
        _refusal(method)
    ctx.out.write(asdict(method), f"{method.label}\n{service.CHANGE_PAYMENT}")
    return 0


def _address(ctx: Context, transport: Transport, query: str, pick: int | None) -> int:
    if not query.strip():
        raise ValueError("Enter an address to look up.")
    # One token per invocation: --pick resolves within the session that made the suggestions.
    token = service.new_session_token()
    outcome, suggestions = service.suggest_addresses(transport, query, token)
    if pick is None:
        lines = [
            f"{number}. {item.title}" + (f", {item.subtitle}" if item.subtitle else "")
            for number, item in enumerate(suggestions, 1)
        ]
        ctx.out.write(
            {
                "outcome": outcome,
                "suggestions": [
                    {"index": number, "title": item.title, "subtitle": item.subtitle}
                    for number, item in enumerate(suggestions, 1)
                ],
            },
            "\n".join(lines) or service.lookup_sentence(outcome),
        )
        return 0
    if not suggestions:
        raise ValueError(service.lookup_sentence(outcome))
    if not 1 <= pick <= len(suggestions):
        raise ValueError(f"Pick a number from 1 to {len(suggestions)}.")
    parts = service.resolve_address(transport, suggestions[pick - 1].id, token)
    if isinstance(parts, Refusal):
        _refusal(parts)
    if parts is None:
        raise ValueError(service.UNRESOLVED)
    ctx.out.write(
        asdict(parts),
        "\n".join(
            (
                parts.formatted,
                *(
                    f"{label}: {value}"
                    for label, value in service.address_fields(parts)
                ),
            )
        ),
    )
    return 0
