import time
from dataclasses import asdict, dataclass

from gbot import config
from gbot.bots import list_bots, record, resolve_bot
from gbot.context import Context

APP_ONLY = "answer in the Grok Bot app"
_BODIES = {
    "auto-review-approval": "approval",
    "meeting-join-consent": "approval",
    "local-tool-permission": "ask",
    "widget": "widget",
    "secret-request": "secretRequest",
    "user-form": "formRequest",
    "virtual-card-approval": "approval",
    "publish-approval": "approval",
    "cookie-origin-approval": "approval",
    "connector-grant": "ask",
    "credential-request": "credentialRequest",
    "mobile-tool-permission": "permission",
    "permission-request": "permission",
    "app-secrets-request": "request",
}
_STATUS_TYPES = {
    "auto-review-approval",
    "meeting-join-consent",
    "local-tool-permission",
    "virtual-card-approval",
    "publish-approval",
    "cookie-origin-approval",
    "connector-grant",
}


@dataclass(frozen=True)
class PendingItem:
    bot_id: str
    bot_name: str
    entry_id: str
    session_id: str | None
    type: str
    summary: str
    created_at: int | float | None
    allowed_actions: tuple[str, ...]
    request_id: str | None = None
    tool_text: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def one_line(value: str) -> str:
    return " ".join("".join(c if c.isprintable() else " " for c in value).split())


def command_text(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.strip().splitlines())


def command_block(value: str) -> str:
    lines = value.split("\n")
    if len(lines) == 1:
        return f"Tool/command: {value}"
    numbered = (f"  {n:>2}| {line}" for n, line in enumerate(lines, 1))
    return f"Tool/command ({len(lines)} lines, all run if approved):\n" + "\n".join(
        numbered
    )


def is_pending(entry: dict[str, object]) -> bool:
    if entry.get("kind") != "send-message":
        return False
    message = record(entry.get("message"))
    kind = str(message.get("type", ""))
    if kind not in _BODIES:
        return False
    body = record(message.get(_BODIES[kind]))
    if kind in _STATUS_TYPES:
        return body.get("status") == "pending"
    if kind == "widget":
        return (
            entry.get("respondedValue") is None
            and not entry.get("widgetDismissed")
            and not entry.get("widgetSkipped")
        )
    if kind == "secret-request":
        return not entry.get("secretProvided")
    if kind == "user-form":
        return entry.get("formResolution") is None
    if kind == "credential-request":
        return entry.get("credentialResolution") in (None, "retryable")
    if kind == "mobile-tool-permission":
        return body.get("status") != "granted"
    if kind == "app-secrets-request":
        secrets = body.get("secrets")
        return isinstance(secrets, list) and any(
            record(secret).get("state") == "requested" for secret in secrets
        )
    # The retired permission card has no answered marker in the wire schema.
    return True


def classify(
    entry: dict[str, object],
    bot_id: str,
    bot_name: str,
    session_id: str | None = None,
) -> PendingItem | None:
    if not is_pending(entry) or not isinstance(entry.get("id"), str):
        return None
    message = record(entry.get("message"))
    kind = str(message["type"])
    body = record(message.get(_BODIES[kind]))
    actions: tuple[str, ...] = ()
    if kind in {
        "auto-review-approval",
        "meeting-join-consent",
        "local-tool-permission",
    }:
        actions = ("approve", "deny")
    elif kind == "widget":
        if body.get("copyKind") not in {
            "automation_spend_guard_nudge",
            "automation_spend_guard_paused",
        }:
            actions = ("respond", "dismiss")
    elif kind == "user-form":
        if (
            body.get("reason") not in {"auth", "checkout"}
            and body.get("vaultKind")
            not in {
                "card",
                "login",
            }
            and body.get("saveToVault") != "card"
        ):
            actions = ("respond", "dismiss")
    elif (
        kind == "secret-request"
        and record(body.get("target")).get("kind") != "channel-credential"
    ):
        actions = ("secret",)
    summary = next(
        (
            one_line(value)
            for key in (
                "title",
                "summary",
                "description",
                "prompt",
                "label",
                "command",
                "target",
                "instruction",
                "serverName",
                "purpose",
                "goal",
                "reason",
            )
            if isinstance(value := body.get(key), str) and value.strip()
        ),
        one_line(str(message.get("title") or message.get("text") or kind)),
    )
    # Executable text keeps its line structure: joining lines would let a newline
    # hide a second command behind a `#` comment in the confirmation.
    tool = ""
    if kind == "local-tool-permission":
        tool = command_text(f"{body.get('action', '')}: {body.get('target', '')}")
    elif kind == "auto-review-approval":
        tool = command_text(str(body.get("command") or ""))
    created = entry.get("timestampMs")
    request_id = body.get("requestId")
    return PendingItem(
        bot_id,
        bot_name,
        str(entry["id"]),
        session_id,
        kind,
        summary,
        created if isinstance(created, (int, float)) else None,
        actions,
        request_id if isinstance(request_id, str) else None,
        tool,
    )


def _tail(ctx: Context, bot_id: str, session_id: str | None) -> list[dict[str, object]]:
    args: dict[str, object] = {"id": bot_id, "limit": 100}
    if session_id is not None:
        args["sessionId"] = session_id
    entries: dict[str, dict[str, object]] = {}
    while True:
        page = record(ctx.manager().command("getAgentTranscriptTail", args.copy()))
        rows = page.get("entries")
        if not isinstance(rows, list):
            raise TypeError("Invalid transcript page from gateway.")
        for row in rows:
            entry = record(row)
            if isinstance(entry.get("id"), str):
                entries.setdefault(str(entry["id"]), entry)
        cursor = page.get("nextBeforeSeq")
        if not isinstance(cursor, (int, float)):
            break
        previous = args.get("beforeSeq")
        if isinstance(previous, (int, float)) and cursor >= previous:
            raise ValueError("Transcript pagination did not advance.")
        args["beforeSeq"] = cursor
    return list(entries.values())


def discover(
    ctx: Context,
    requested: str | None = None,
    *,
    all_bots: bool = False,
    awaiting_only: bool = True,
) -> list[PendingItem]:
    selected = None
    if not all_bots and (requested is not None or config.default_bot() is not None):
        selected = resolve_bot(ctx, requested)[0]
    bots = list_bots(ctx)
    found: dict[tuple[str, str], PendingItem] = {}
    for bot in bots:
        bot_id, name = str(bot["id"]), str(bot["name"])
        if selected is not None:
            if selected != bot_id:
                continue
        elif awaiting_only and not bot.get("awaitingUserResponse"):
            continue
        sessions: list[str | None] = [None]
        awaiting = bot.get("awaitingSessionIds")
        if isinstance(awaiting, list):
            sessions.extend(dict.fromkeys(s for s in awaiting if isinstance(s, str)))
        for session_id in sessions:
            for entry in _tail(ctx, bot_id, session_id):
                key = (bot_id, str(entry["id"]))
                item = classify(entry, bot_id, name, session_id)
                if item is not None:
                    found[key] = item
                else:
                    found.pop(key, None)
    return list(found.values())


def resolve_ref(ctx: Context, ref: str) -> PendingItem:
    # A REF can come from an explicit --bot listing before its roster flag updates.
    items = discover(ctx, all_bots=True, awaiting_only=False)
    exact = [item for item in items if item.entry_id == ref]
    if not exact and len(ref) < 6:
        raise ValueError("REF prefixes must contain at least 6 characters.")
    matches = exact or [item for item in items if item.entry_id.startswith(ref)]
    if not matches:
        raise ValueError(f"Unknown pending REF: {ref}. Run: gbot approvals --all")
    if len(matches) != 1:
        raise ValueError(f"Ambiguous pending REF: {ref}. Use the full entry id.")
    return matches[0]


def render(items: list[PendingItem]) -> str:
    if not items:
        return "Nothing pending."
    lines = []
    for item in items:
        age = "?"
        if item.created_at is not None:
            seconds = max(0, int(time.time() - item.created_at / 1000))
            age = f"{seconds}s" if seconds < 60 else f"{seconds // 60}m"
        suffix = "" if item.allowed_actions else f" ({APP_ONLY})"
        lines.append(
            f"{item.entry_id[:8]}  {one_line(item.bot_name)}  {item.type}  {age}  "
            f"{item.summary}{suffix}"
        )
    hints = dict.fromkeys(
        f"{item.type}: "
        + (
            " / ".join(f"gbot {action} REF" for action in item.allowed_actions)
            if item.allowed_actions
            else APP_ONLY
        )
        for item in items
    )
    lines.append("Answer with: " + "; ".join(hints))
    return "\n".join(lines)
