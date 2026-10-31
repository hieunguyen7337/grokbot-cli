import argparse
import math

from gbot.bots import resolve_bot
from gbot.commands.approvals import _confirm, _require_confirmation
from gbot.context import Context
from gbot.service import avatar_voice, conversation
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("voice", help="Read or choose a bot voice")
    parser.add_argument("bot", metavar="BOT", nargs="?")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--voice")
    parser.add_argument("--speed")
    parser.add_argument("--language")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    mutation = any(
        value is not None for value in (args.voice, args.speed, args.language)
    )
    if args.list:
        if args.bot or mutation:
            raise ValueError("Use --list by itself.")
        ctx.out.write(
            {
                "voices": [
                    {"id": key, "label": label} for key, label in avatar_voice.VOICES
                ],
                "speeds": avatar_voice.SPEEDS,
                "languages": avatar_voice.LANGUAGES,
            },
            "\n".join(f"{key}: {label}" for key, label in avatar_voice.VOICES),
        )
        return 0
    if args.bot is None:
        raise ValueError("Specify BOT or --list.")
    if mutation:
        _require_confirmation(args.yes)
    transport = ContextTransport(ctx)
    bot_id, _ = resolve_bot(ctx, args.bot)
    bot = next(bot for bot in conversation.roster(transport) if bot.id == bot_id)
    fields: dict[str, object] = {}
    if args.voice is not None:
        if args.voice not in dict(avatar_voice.VOICES):
            raise ValueError("Unknown voice id; use gbot voice --list.")
        fields["voiceId"] = args.voice
    if args.speed is not None:
        try:
            number = float(args.speed)
        except ValueError:
            number = math.nan
        if not math.isfinite(number):
            raise ValueError("Speed must be a number, such as 1.25.")
        fields["voiceSpeed"] = avatar_voice.normalize_speed(args.speed)
    if args.language is not None:
        fields["voiceLanguage"] = avatar_voice.normalize_language(args.language)
    if mutation:
        _confirm(args.yes, json_mode=args.json)
        if args.voice is None:
            avatar_voice.set_voice(
                transport, bot, speed=args.speed, language=args.language
            )
        else:
            avatar_voice.set_voice(
                transport,
                bot,
                voice_id=args.voice,
                speed=args.speed,
                language=args.language,
            )
    row = {**bot.raw, **fields}
    result = {
        "id": bot.id,
        "voice_id": row.get("voiceId"),
        "speed": avatar_voice.normalize_speed(row.get("voiceSpeed")),
        "language": avatar_voice.normalize_language(row.get("voiceLanguage")),
    }
    ctx.out.write(
        result,
        f"Voice: {result['voice_id']}; speed: {result['speed']}x; language: {result['language']}",
    )
    return 0
