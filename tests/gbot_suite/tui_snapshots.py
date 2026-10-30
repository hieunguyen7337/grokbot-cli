import os
from pathlib import Path

from textual.app import App
from textual.pilot import Pilot

# Textual draws the first app in a process in monochrome when NO_COLOR is set (worker sandboxes set it), so
# drop it before any app starts: snapshots are always drawn in colour.
os.environ.pop("NO_COLOR", None)


async def assert_snapshot(app: App, pilot: Pilot, name: str) -> None:
    await pilot.pause()
    path = Path(__file__).parent / "snapshots" / f"{name}.svg"
    actual = app.export_screenshot()
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8", newline="\n")
    assert path.exists() and path.read_text(encoding="utf-8") == actual, (
        f"Snapshot mismatch: {path}. Set UPDATE_SNAPSHOTS=1 to update."
    )
