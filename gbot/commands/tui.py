import argparse
import asyncio
import sys
from pathlib import Path
from time import monotonic

from gbot.context import Context

SCREENSHOT_TIMEOUT = 20.0


def size(value: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in value.lower().split("x"))
        if width > 0 and height > 0:
            return width, height
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("size must be positive WxH (for example 120x40)")


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("tui", help="Open the terminal UI")
    parser.add_argument("--bot")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--screenshot", type=Path, metavar="PATH")
    parser.add_argument("--size", type=size, default=(120, 40), metavar="WxH")
    parser.add_argument("--ascii", action="store_true")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    try:
        # Command discovery and --help must work without the optional dependency.
        import textual  # noqa: F401

        from gbot.tui.app import GbotApp
    except ModuleNotFoundError as exc:
        if exc.name is None or exc.name.split(".")[0] != "textual":
            raise
        raise ValueError(
            "The terminal UI needs the tui extra. Reinstall from the repository "
            'folder with: uv tool install --editable ".[tui]" --force'
        ) from exc
    from gbot.service.fake import FakeService

    service = FakeService(auto_reply=True) if args.demo else ctx.service()
    closed = False

    def close() -> None:
        nonlocal closed
        if not closed:
            closed = True
            if args.demo:
                service.close()
            else:
                ctx.close()

    async def screenshot(app: GbotApp) -> int:
        async with app.run_test(size=args.size) as pilot:
            deadline = monotonic() + SCREENSHOT_TIMEOUT
            while True:
                await pilot.pause()
                if app.loaded or monotonic() >= deadline:
                    break
            args.screenshot.write_text(
                app.export_screenshot(), encoding="utf-8", newline="\n"
            )
            timed_out = not app.loaded
            if timed_out:
                close()
        if timed_out:
            print("gbot tui: still loading after 20 s", file=sys.stderr)
            return 1
        return 0

    try:
        app = GbotApp(
            service,
            ascii_only=args.ascii,
            bot=args.bot,
            animate=not args.screenshot,
            read_only=bool(args.screenshot),
        )
        if args.screenshot:
            return asyncio.run(screenshot(app))
        else:
            app.run()
    finally:
        close()
    return 0
