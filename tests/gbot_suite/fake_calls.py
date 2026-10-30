"""What a test's actions sent through a FakeTransport, without the app's background reads."""

from gbot.service.transport import FakeTransport

# The app reads trays when the roster loads and on every tray event.
BACKGROUND = {"getTrays"}


def actions(transport: FakeTransport) -> list[tuple[str, str, dict[str, object]]]:
    return [call for call in transport.calls if call[1] not in BACKGROUND]
