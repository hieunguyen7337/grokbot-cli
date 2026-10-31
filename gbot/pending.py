import sys
import time
from dataclasses import asdict, dataclass

from gbot import config
from gbot.bots import list_bots, record, resolve_bot
from gbot.context import Context
from gbot.output import terminal_safe

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
    "email-draft": "draft",
    "slack-draft": "draft",
    "meeting-chat-draft": "draft",
}
_DRAFT_TYPES = {"email-draft", "slack-draft", "meeting-chat-draft"}
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
    draft: dict[str, object] | None = None
    options: list[str] | None = None
    fields: list[dict[str, object]] | None = None
    validate_options: bool = False

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data.pop("validate_options")
        return data


def one_line(value: str) -> str:
    return " ".join("".join(c if c.isprintable() else " " for c in value).split())


def command_text(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.strip().splitlines())


def command_block(value: str, heading: str | None = None) -> str:
    lines = value.split("\n")
    if len(lines) == 1 and heading is None:
        return f"Tool/command: {value}"
    numbered = (f"  {n:>2}| {line}" for n, line in enumerate(lines, 1))
    title = heading or "Tool/command ({count} lines, all run if approved):"
    return title.format(count=len(lines)) + "\n" + "\n".join(numbered)


def is_pending(entry: dict[str, object]) -> bool:
    if entry.get("kind") != "send-message":
        return False
    message = record(entry.get("message"))
    kind = str(message.get("type", ""))
    if kind not in _BODIES:
        return False
    body = record(message.get(_BODIES[kind]))
    if kind in _DRAFT_TYPES:
        return entry.get("draftSendState") is None
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
    return _classify(entry, bot_id, bot_name, session_id)


def _classify(
    entry: dict[str, object], bot_id: str, bot_name: str, session_id: str | None
) -> PendingItem:
    message = record(entry.get("message"))
    kind = str(message["type"])
    body = record(message.get(_BODIES[kind]))
    actions: tuple[str, ...] = ()
    if kind in {"email-draft", "slack-draft"}:
        actions = ("approve", "deny")
    elif kind == "meeting-chat-draft":
        actions = ("deny",)
    elif kind in {"auto-review-approval", "local-tool-permission", "connector-grant"}:
        # meeting-join-consent stays app-only: the app has no verified backend RPC for it.
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
    elif kind in {
        "connector-grant",
        "virtual-card-approval",
        "credential-request",
        "permission-request",
    }:

        def text(value: object) -> str:
            return one_line(terminal_safe(str(value or "")))

        lines: list[str] = []
        if kind == "connector-grant":
            lines.append(f"Connector: {text(body.get('serverName'))}")
            if body.get("remembered"):
                lines.append(f"Remembered: {text(body['remembered'])}")
        elif kind == "virtual-card-approval":
            amount = body.get("amountCents")
            money = (
                f"{amount / 100:.2f}"
                if isinstance(amount, (int, float)) and not isinstance(amount, bool)
                else "?"
            )
            lines = [
                f"Pay {money} {text(body.get('currency'))} to {text(body.get('merchantName'))}",
                text(body.get("merchantUrl")),
            ]
            items = body.get("lineItems")
            for item in items if isinstance(items, list) else []:
                row = record(item)
                label, cents = row.get("label"), row.get("amountCents")
                if (
                    not isinstance(label, str)
                    or not isinstance(cents, (int, float))
                    or isinstance(cents, bool)
                ):
                    continue
                quantity = row.get("quantity")
                count = (
                    f" x{quantity}"
                    if isinstance(quantity, (int, float)) and quantity > 1
                    else ""
                )
                lines.append(f"  {text(label)}{count}  {cents / 100:.2f}")
            if body.get("context"):
                lines.append(text(body["context"]))
        elif kind == "credential-request":
            if body.get("kind") == "brokered-login":
                lines.append(f"Sign in for: {text(body.get('goal'))}")
                entries = body.get("entries")
                for credential in entries if isinstance(entries, list) else []:
                    row = record(credential)
                    lines.append(
                        f"  {text(row.get('website'))}: {text(row.get('reason'))}"
                    )
            elif body.get("kind") == "browser-login":
                lines.append(
                    f"Sign in to {text(body.get('targetSite'))}: {text(body.get('purpose'))}"
                )
        else:
            lines = [
                f"{text(body.get('kind'))} permission: {text(body.get('title'))}",
                text(body.get("reason")),
            ]
            if body.get("detail"):
                lines.append(text(body["detail"]))
        tool = "\n".join(lines)
    elif kind in _DRAFT_TYPES:

        def addresses(key: str) -> str:
            value = body.get(key)
            return (
                ", ".join(str(part) for part in value)
                if isinstance(value, list)
                else ""
            )

        if kind == "email-draft":
            lines = [f"From: {body.get('from', '')}", f"To: {addresses('to')}"]
            if "cc" in body:
                lines.append(f"Cc: {addresses('cc')}")
            lines.append(f"Subject: {body.get('subject', '')}")
            summary = one_line(
                f"From: {body.get('from', '')}; To: {addresses('to')}; "
                f"Subject: {body.get('subject', '')}"
            )
        elif kind == "slack-draft":
            lines = [f"To: {body.get('target', '')}"]
            for key, label in (("thread", "Thread"), ("workspace", "Workspace")):
                if key in body:
                    lines.append(f"{label}: {body[key]}")
            first_line = str(body.get("body", "")).split("\n", 1)[0]
            workspace = (
                f"; Workspace: {body['workspace']}" if "workspace" in body else ""
            )
            summary = one_line(f"To: {body.get('target', '')}{workspace}; {first_line}")
        else:
            meeting = body.get("meetingTitle") or body.get("meetingId", "")
            lines = [f"Meeting: {meeting}"]
            summary = one_line(f"Meeting: {meeting}")
        # Shown verbatim, line by line: approving sends exactly this draft.
        tool = "\n".join([*lines, "", str(body.get("body", ""))])
    created = entry.get("timestampMs")
    request_id = body.get("requestId")
    options = None
    fields = None
    if kind == "widget":
        steps = body.get("steps")
        option_body = record(steps[0]) if isinstance(steps, list) and steps else body
        raw_options = option_body.get("options")
        if isinstance(raw_options, list):
            options = [
                label
                for option in raw_options
                if isinstance(label := record(option).get("label"), str)
            ]
    raw_fields = body.get("fields")
    if kind == "user-form" and isinstance(raw_fields, list):
        fields = [
            {key: record(field).get(key) for key in ("id", "label", "type", "required")}
            for field in raw_fields
            if isinstance(field, dict)
        ]
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
        body.copy()
        if kind in _DRAFT_TYPES and isinstance(message.get("draft"), dict)
        else None,
        options,
        fields,
        kind == "widget"
        and not (
            body.get("multiSelect") or body.get("steps") or body.get("allowCustom")
        )
        and options is not None,
    )


def describe(entry: dict[str, object]) -> str:
    message = record(entry.get("message"))
    kind = str(message.get("type") or "unknown")
    if kind not in _BODIES:
        return kind
    item = _classify({**entry, "id": str(entry.get("id", ""))}, "", "", None)
    if is_pending(entry):
        state = "pending"
    elif kind == "widget":
        if entry.get("respondedValue") is not None:
            state = f"answered: {one_line(str(entry['respondedValue']))}"
        else:
            state = "dismissed" if entry.get("widgetDismissed") else "skipped"
    elif kind == "user-form":
        state = str(entry.get("formResolution"))
    elif kind in _DRAFT_TYPES:
        state = str(entry.get("draftSendState"))
    else:
        body = record(message.get(_BODIES[kind]))
        state = str(body.get("status") or "answered")
    return f"{kind}: {item.summary} ({one_line(state)})"


def discover(
    ctx: Context,
    requested: str | None = None,
    *,
    all_bots: bool = False,
    awaiting_only: bool = True,
) -> list[PendingItem]:
    from gbot.service import cards
    from gbot.service.transport import ContextTransport

    selected = None
    if not all_bots and (requested is not None or config.default_bot() is not None):
        selected = resolve_bot(ctx, requested)[0]
    items, warnings = cards.discover(
        ContextTransport(ctx),
        list_bots(ctx),
        selected=selected,
        all_bots=all_bots,
        awaiting_only=awaiting_only,
    )
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return items


def resolve_ref(ctx: Context, ref: str, bot: str | None = None) -> PendingItem:
    # A REF can come from an explicit --bot listing before its roster flag updates.
    # Entry ids are per-bot transcript ids, so two bots can share one: --bot narrows it.
    items = (
        discover(ctx, bot, awaiting_only=False)
        if bot is not None
        else discover(ctx, all_bots=True, awaiting_only=False)
    )
    exact = [item for item in items if item.entry_id == ref]
    if not exact and len(ref) < 6:
        raise ValueError("REF prefixes must contain at least 6 characters.")
    matches = exact or [item for item in items if item.entry_id.startswith(ref)]
    if not matches:
        raise ValueError(f"Unknown pending REF: {ref}. Run: gbot approvals --all")
    if len(matches) != 1:
        bots = sorted({item.bot_name for item in matches})
        hint = "Add --bot NAME" if len(bots) > 1 else "Use the full entry id"
        raise ValueError(
            f"Ambiguous pending REF: {ref} (on {', '.join(bots)}). {hint}."
        )
    return matches[0]


def render(items: list[PendingItem]) -> str:
    if not items:
        return "Nothing pending."
    lines = []
    for item in items:
        age = "?"
        if item.created_at is not None:
            seconds = max(0, int(time.time() - item.created_at / 1000))
            if seconds < 60:
                age = f"{seconds}s"
            elif seconds < 3600:
                age = f"{seconds // 60}m"
            elif seconds < 172800:
                age = f"{seconds // 3600}h"
            else:
                age = f"{seconds // 86400}d"
        suffix = "" if item.allowed_actions else f" ({APP_ONLY})"
        lines.append(
            f"{item.entry_id[:8]}  {one_line(item.bot_name)}  {item.type}  {age}  "
            f"{item.summary}{suffix}"
        )
        if not item.allowed_actions and item.tool_text:
            lines.extend("  " + line for line in item.tool_text.splitlines())
        if item.options is not None:
            lines.append(
                "  options: " + " | ".join(one_line(option) for option in item.options)
            )
        if item.fields is not None:
            fields = [
                f"{one_line(str(field.get('id') or ''))} ({one_line(str(field.get('type') or ''))}, {'required' if field.get('required') else 'optional'})"
                for field in item.fields
            ]
            lines.append("  fields: " + ", ".join(fields))
    hints = dict.fromkeys(
        f"{item.type}: "
        + (
            " / ".join(
                f"gbot {action} REF"
                + (
                    " VALUE"
                    if action == "respond" and item.type == "widget"
                    else " --field ID=VALUE"
                    if action == "respond" and item.type == "user-form"
                    else ""
                )
                for action in item.allowed_actions
            )
            if item.allowed_actions
            else APP_ONLY
        )
        for item in items
    )
    lines.append("Answer with: " + "; ".join(hints))
    return "\n".join(lines)
