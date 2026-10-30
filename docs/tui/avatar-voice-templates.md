# Avatars, voices and templates

The M3 service areas are `avatar_voice` and `templates`. CLI modules are discovered
automatically. All commands support `--json`; writes ask for terminal confirmation
or require `--yes` without a terminal. Untrusted output uses the CLI safe streams.

Avatar reads decode data URLs. Writes validate PNG signature and IHDR dimensions,
with limits of 2 MiB and 1024 pixels per side; there is no image resizer. Generation
does not itself save an avatar. Owned temporal and box avatar writes use the same
gateway command. Voice changes route temporal bots to SetGrokBotAgentVoice and box
bots to setAgentVoice; omitted fields are preserved. Audio preview is an app handoff.

Marketplace browsing pages at 100 entries, with a 20-page bound. Template details
retain the reviewed active version. Imports reserve a UUID, validate the returned
identity and temporal harness, and fall back to the gateway only on unimplemented.
Server setup completion is reported explicitly; other recipe setup is an app
handoff. No blobGetUrl is fetched. Source-template and export-policy reads follow
temporal routing. getBotTemplateVersion and GetGrokBotTemplateVersion remain
planned for the publishing milestone.

`load_fake` supplies all declared command and RPC replies, including imports with
the caller's reserved identity, for offline use.
