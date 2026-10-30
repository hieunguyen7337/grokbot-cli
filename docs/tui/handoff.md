# Browser handoffs

Use `gbot.service.handoff.wait_until` for browser steps whose completion is learned
by reading status (protocol-m4b section 11). Supply a synchronous `check` returning
`None` while pending, or any other value when finished (including `False`). The
frozen `HandoffResult` has `status` (`done`, `cancelled`, `timeout`) and `value`.
Exceptions propagate to the caller. Checks should use bounded transport timeouts:
cancellation cannot interrupt a check already running.

The first check runs immediately. Later checks wait 1, 2, 3, then 5 seconds,
repeating 5 seconds, bounded by a monotonic ten-minute deadline by default. Supply
`cancel` and optional `wake` threading events. A wake is cleared and triggers a
fresh check; cancellation takes priority. With two events, event waits are capped
at 50 ms to observe cancellation without auxiliary threads. No sleep is used.

Push `HandoffScreen(title, url, check, ...)` with a result callback in the TUI.
It opens the browser on mount, displays a sanitized, wrapped URL, and runs checks
in a thread worker. Every service event wakes every handoff in the screen stack.
Completion dismisses with its value. Timeout or a check exception leaves the
screen open; reopening starts a fresh wait with a fresh deadline. Browser launch
failure leaves the link available to copy. URLs are displayed but never logged.

| Key | Action |
| --- | --- |
| `o` | Open again; restart the wait after timeout or check failure |
| `c` | Copy the original URL and notify `Link copied` |
| Escape | Cancel and dismiss with `cancelled` |

Unmounting signals cancellation and wakes the worker. An in-flight check must
return before its thread can stop; late results cannot update a closed screen.

CLI callers use `gbot.handoff.run_handoff(url, check, ...)`. It prints a sanitized
link on stderr, optionally opens a browser, and waits without service-event wakes.
Pass `open_browser=False` for manual opening. KeyboardInterrupt returns
`cancelled`; the command maps this to exit 130. Other check exceptions propagate.
Both wrappers accept an injected opener; tests must always supply one.
