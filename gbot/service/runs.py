"""Run control commands shared by the CLI and TUI."""

from collections.abc import Mapping

from .transport import Transport

COMMANDS = {
    "interruptAgentRun": "object",
    "startFreshConversation": "object",
    "rollBackConversation": "object",
}
DEMO_COMMANDS = {
    "interruptAgentRun": {"hadActiveRun": True},
    "startFreshConversation": None,
    "rollBackConversation": None,
}


def _args(bot_id: str, session_id: str | None) -> dict[str, object]:
    args: dict[str, object] = {"id": bot_id}
    if session_id is not None:
        args["sessionId"] = session_id
    return args


def interrupt(transport: Transport, bot_id: str, session_id: str | None = None) -> bool:
    reply = transport.command("interruptAgentRun", _args(bot_id, session_id))
    if reply is None:
        return False
    if not isinstance(reply, Mapping) or not isinstance(
        reply.get("hadActiveRun"), bool
    ):
        raise ValueError("Unexpected reply to interruptAgentRun")  # noqa: TRY004 - protocol contract
    return reply["hadActiveRun"]


def start_fresh(
    transport: Transport, bot_id: str, session_id: str | None = None
) -> None:
    transport.command("startFreshConversation", _args(bot_id, session_id))


def roll_back(transport: Transport, bot_id: str, session_id: str | None = None) -> None:
    transport.command("rollBackConversation", _args(bot_id, session_id))
