"""Gateway argument kinds used by gbot, as reported by the contract extractor."""

USED_COMMANDS: dict[str, str] = {
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

USED_RPCS: tuple[str, ...] = (
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
