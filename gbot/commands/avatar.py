import argparse
import sys
from pathlib import Path

from gbot.bots import resolve_bot
from gbot.commands.approvals import _confirm, _require_confirmation
from gbot.context import Context
from gbot.output import terminal_safe
from gbot.service import avatar_voice, conversation
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "avatar", help="Read, set, generate or clear a bot avatar"
    )
    parser.add_argument("bot", metavar="BOT")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--file", type=Path)
    group.add_argument("--generate", metavar="TEXT")
    group.add_argument("--clear", action="store_true")
    parser.add_argument("--save-to", type=Path)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    if args.save_to and (args.file or args.clear):
        raise ValueError("--save-to is for the current or generated image.")
    if args.save_to and args.save_to.exists():
        raise FileExistsError(f"File already exists: {args.save_to}")
    mutation = args.file is not None or args.generate is not None or args.clear
    if mutation:
        _require_confirmation(args.yes)
    transport = ContextTransport(ctx)
    bot_id, _ = resolve_bot(ctx, args.bot)
    bot = next(bot for bot in conversation.roster(transport) if bot.id == bot_id)
    image = None
    if args.generate is not None:
        image = avatar_voice.generate_avatar(transport, args.generate)
        print(
            terminal_safe(
                f"Generated {image.mime_type} image ({len(image.data)} bytes)."
            ),
            file=sys.stderr,
        )
        if image.mime_type != "image/png":
            # Generated images can be exported, but saving to a bot requires PNG.
            if args.save_to:
                with args.save_to.open("xb") as target:
                    target.write(image.data)
            raise ValueError(
                "Generated image is not PNG; export it as PNG before setting the avatar."
            )
        avatar_voice.check_png(image.data)
    elif args.file is not None:
        if args.file.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Avatar exceeds 2 MiB; export a smaller PNG.")
        image = avatar_voice.Avatar(args.file.read_bytes(), "image/png")
        avatar_voice.check_png(image.data)
    elif not args.clear:
        image = avatar_voice.avatar(transport, bot.id)
    saved = None
    if args.save_to:
        if image is None:
            raise ValueError("No avatar image to save.")
        with args.save_to.open("xb") as target:
            target.write(image.data)
        saved = str(args.save_to)
    if mutation:
        _confirm(args.yes, json_mode=args.json)
        avatar_voice.set_avatar(transport, bot, image.data if image else None)
    result = {
        "id": bot.id,
        "shape": bot.raw.get("avatarShape"),
        "color": bot.avatar_color,
        "has_image": image is not None,
        "mime_type": image.mime_type if image else None,
        "saved_to": saved,
    }
    ctx.out.write(
        result,
        f"Shape: {result['shape']}; color: {result['color']}; image: {'set' if image else 'none'}"
        + (f"\nSaved: {saved}" if saved else ""),
    )
    return 0
