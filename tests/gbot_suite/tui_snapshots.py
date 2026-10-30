import os
from pathlib import Path

from textual.app import App
from textual.pilot import Pilot


async def assert_snapshot(app: App, pilot: Pilot, name: str) -> None:
    # Some terminals and sandboxes report a blur, which dims focus styles; draw snapshots as focused.
    app.app_focus = True
    await pilot.pause()
    path = Path(__file__).parent / "snapshots" / f"{name}.svg"
    actual = app.export_screenshot()
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8", newline="\n")
    assert path.exists() and path.read_text(encoding="utf-8") == actual, (
        f"Snapshot mismatch: {path}. Set UPDATE_SNAPSHOTS=1 to update."
    )
