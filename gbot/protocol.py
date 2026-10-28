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
    "resolveAutoReviewApproval": "object",
    "resolveLocalToolPermission": "object",
    "respondToWidget": "object",
    "dismissWidget": "object",
    "submitSecret": "object",
    "submitUserForm": "object",
    "dismissUserForm": "object",
    "sendDraft": "object",
    "discardDraft": "object",
}
