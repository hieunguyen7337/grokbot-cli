"""Gateway commands and backend RPCs gbot uses, with argument kinds as reported by the contract extractor.

The CLI's own names are listed here; each `gbot.service` area module adds its own through module-level `COMMANDS`
and `RPCS`, so parallel features never edit one shared list. `docs/parity.json` marks all of them `done`.
"""

import importlib
import pkgutil

_CLI_COMMANDS: dict[str, str] = {
    "listAgents": "none",
    "sendPrompt": "object",
    "getAgentTranscriptTail": "object",
    "getForeverBoxStatus": "object",
    "getHostStatus": "object",
    "getBoxSecretsStatus": "none",
    "getMcpState": "none",
    "listBoxMcpServers": "object",
    "getEffectiveMcpPlugins": "none",
    "listMcpServerTools": "object",
}

_CLI_RPCS: tuple[str, ...] = (
    "ResolveGrokBotAutoReviewApproval",
    "ResolveGrokBotLocalToolPermission",
    "RespondGrokBotWidget",
    "DismissGrokBotWidget",
    "SubmitGrokBotSecret",
    "SubmitGrokBotUserForm",
    "DismissGrokBotUserForm",
    "SendGrokBotDraft",
    "DiscardGrokBotDraft",
)


def _collect() -> tuple[dict[str, str], tuple[str, ...]]:
    from gbot import service

    commands = dict(_CLI_COMMANDS)
    rpcs = list(_CLI_RPCS)
    for info in sorted(
        pkgutil.iter_modules(service.__path__), key=lambda item: item.name
    ):
        module = importlib.import_module(f"gbot.service.{info.name}")
        commands.update(getattr(module, "COMMANDS", {}))
        rpcs.extend(name for name in getattr(module, "RPCS", ()) if name not in rpcs)
    return commands, tuple(rpcs)


USED_COMMANDS, USED_RPCS = _collect()
