"""Pure card planning and printing-free discovery and answering."""

from collections.abc import Mapping

from gbot.bots import record
from gbot.pending import APP_ONLY, classify, one_line
from groken.client import ConnectError

from .models import Action, AnswerResult, Card
from .transport import Transport

COMMANDS = {"getAgentTranscriptTail": "object", "resolveConnectorGrant": "object"}
_GATEWAY_ANSWERS = {"resolveConnectorGrant"}
RPCS = (
    "SendGrokBotDraft",
    "DiscardGrokBotDraft",
    "ResolveGrokBotAutoReviewApproval",
    "ResolveGrokBotLocalToolPermission",
    "RespondGrokBotWidget",
    "DismissGrokBotWidget",
    "SubmitGrokBotUserForm",
    "DismissGrokBotUserForm",
    "SubmitGrokBotSecret",
)


def plan(card: Card, action: Action) -> tuple[str, dict[str, object]]:
    if action.all_bots and (card.type != "connector-grant" or not action.always):
        raise ValueError(
            "--all-bots requires a connector grant and --always. "
            "Use: gbot approve REF --always --all-bots"
        )
    if not card.allowed_actions:
        raise ValueError(f"{card.type}: {APP_ONLY}.")
    kind = action.kind
    if kind not in card.allowed_actions:
        right = " or ".join(f"gbot {name} REF" for name in card.allowed_actions)
        raise ValueError(f"{kind} cannot answer {card.type}. Use: {right}")
    payload: dict[str, object] = {"agentId": card.bot_id, "entryId": card.entry_id}
    if card.session_id:
        payload["sessionId"] = card.session_id
    if card.type == "connector-grant":
        if action.never or (kind == "deny" and action.always):
            raise ValueError(
                "Connector grants use: gbot approve REF [--always [--all-bots]] "
                "or gbot deny REF; --never does not apply."
            )
        if not card.request_id:
            raise ValueError("Pending approval is missing its requestId.")
        resolution = "skipped" if kind == "deny" else "allowed"
        if kind == "approve" and action.always:
            resolution = (
                "always_all_team_bots" if action.all_bots else "always_this_bot"
            )
        payload.update(requestId=card.request_id, resolution=resolution)
        return "resolveConnectorGrant", payload
    if card.type in {"email-draft", "slack-draft", "meeting-chat-draft"}:
        if action.always or action.never:
            raise ValueError("--always and --never do not apply to drafts.")
        if card.draft is None:
            raise ValueError("Pending draft is missing its draft record.")
        if kind == "deny":
            return "DiscardGrokBotDraft", payload
        draft = action.draft if action.draft is not None else card.draft
        if card.type == "email-draft":
            payload["email"] = {
                key: draft.get(key, [] if key == "cc" else "")
                for key in ("from", "to", "cc", "subject", "body")
            }
        else:
            payload["slack"] = {
                key: draft[key]
                for key in ("target", "body", "workspace", "thread")
                if key in draft
            }
        return "SendGrokBotDraft", payload
    if kind in {"approve", "deny"}:
        tool = card.type == "local-tool-permission"
        if not card.request_id:
            raise ValueError("Pending approval is missing its requestId.")
        if kind == "deny" and action.never and not tool:
            raise ValueError(
                "--never applies only to local-tool-permission. Use: gbot deny REF"
            )
        resolution = "approved" if kind == "approve" else "denied"
        if tool:
            resolution = "allow-once" if kind == "approve" else "deny"
        if kind == "approve" and action.always:
            resolution = "always"
        elif kind == "deny" and action.never:
            resolution = "never"
        payload.update(
            requestId=card.request_id,
            resolution={
                "approved": 1,
                "denied": 2,
                "allow-once": 1,
                "deny": 2,
                "always": 3,
                "never": 4,
            }[resolution],
        )
        if not tool:
            payload.pop("entryId")
            payload["approvalPlatform"] = "desktop"
        return (
            "ResolveGrokBotLocalToolPermission"
            if tool
            else "ResolveGrokBotAutoReviewApproval"
        ), payload
    if kind == "respond":
        if card.type == "widget":
            if action.value is None or action.fields:
                raise ValueError("Use: gbot respond REF VALUE for a widget.")
            if (
                card.validate_options
                and card.options is not None
                and action.value not in card.options
            ):
                raise ValueError(
                    "Invalid widget value. Options: " + " | ".join(card.options)
                )
            payload["value"] = action.value
            return "RespondGrokBotWidget", payload
        if action.value is not None or not action.fields:
            raise ValueError(
                "Use: gbot respond REF --field NAME=VALUE for a user-form."
            )
        values: dict[str, str] = {}
        for name, value in action.fields:
            if not name or name in values:
                raise ValueError(
                    "Each --field must have a unique, nonempty NAME=VALUE."
                )
            values[name] = value
        if card.fields is not None:
            valid = [
                field["id"] for field in card.fields if isinstance(field.get("id"), str)
            ]
            unknown = [name for name in values if name not in valid]
            if unknown:
                raise ValueError(
                    "Unknown field id: "
                    + ", ".join(unknown)
                    + ". Valid ids: "
                    + ", ".join(str(name) for name in valid)
                )
            for field in card.fields:
                if (
                    field.get("required")
                    and isinstance(field.get("id"), str)
                    and field["id"] not in values
                ):
                    raise ValueError(f"Missing required field: {field['id']}")
        payload.update(values=values, saveToVault=False, platform=1)
        return "SubmitGrokBotUserForm", payload
    if kind == "dismiss":
        if card.type == "widget":
            return "DismissGrokBotWidget", payload
        payload.update(mode=1, platform=1)
        return "DismissGrokBotUserForm", payload
    return "SubmitGrokBotSecret", payload


def effect(
    card: Card, action: Action, method: str, payload: dict[str, object]
) -> str | None:
    if card.type == "connector-grant":
        return str(payload["resolution"])
    draft_effect = {
        "SendGrokBotDraft": "sends it now",
        "DiscardGrokBotDraft": "discards it",
    }.get(method)
    if draft_effect is not None:
        return draft_effect
    if "resolution" not in payload:
        return None
    if action.always:
        return "always"
    if action.never:
        return "never"
    if card.type == "local-tool-permission":
        return "allow-once" if action.kind == "approve" else "deny"
    return "approved" if action.kind == "approve" else "denied"


def answer(transport: Transport, card: Card, action: Action) -> AnswerResult:
    if action.kind == "secret":
        failure = None
        try:
            method, payload = plan(card, action)
            payload["value"] = action.secret
            reply = transport.rpc(method, payload)
            try:
                check_reply(reply, method, secret=True)
            except ValueError as exc:
                failure = str(exc)
        except Exception:  # noqa: BLE001 - secret submission is a redaction boundary
            failure = "Secret was not submitted successfully; no value is displayed."
        if failure:
            raise ValueError(failure) from None
        return AnswerResult("SubmitGrokBotSecret", "secret stored")
    else:
        method, payload = plan(card, action)
        reply = (
            transport.command(method, payload)
            if method in _GATEWAY_ANSWERS
            else transport.rpc(method, payload)
        )
        check_reply(reply, method)
    word = effect(card, action, method, payload)
    return AnswerResult(
        method,
        word
        or {
            "respond": "answered" if card.type == "widget" else "submitted",
            "dismiss": "dismissed",
            "secret": "secret stored",
        }[action.kind],
    )


def check_reply(reply: object, method: str, *, secret: bool = False) -> None:
    if method in _GATEWAY_ANSWERS and (
        reply is None or isinstance(reply, Mapping) and "refusal" not in reply
    ):
        return
    if not isinstance(reply, Mapping):
        reply = {}
    refusal = reply.get("refusal")
    if isinstance(refusal, dict):
        code = refusal.get("failureCode", "unknown")
        message = refusal.get("message")
        detail = f"Answer refused: {code}"
        if message and not secret:
            detail += f": {message}"
        raise ValueError(detail)  # noqa: TRY004 - refusal is a service error
    flag = "dispatched" if method.startswith("ResolveGrokBot") else "accepted"
    if method in _GATEWAY_ANSWERS or reply.get(flag) is not True:
        raise ValueError(
            "Answer was not accepted; the item may already be answered. Run: gbot approvals"
        )


def waiting(row: Mapping[str, object]) -> bool:
    """Whether a roster row says the bot waits on the user, so a capped read must still read it in full.

    Any `awaitingUserResponse` but absent, None or False counts (the model treats every mapping, even an empty
    one, as waiting), and so does a listed waiting session.
    """
    flag = row.get("awaitingUserResponse")
    sessions = row.get("awaitingSessionIds")
    return (flag is not None and flag is not False) or (
        isinstance(sessions, list) and any(isinstance(s, str) for s in sessions)
    )


def tail(
    transport: Transport,
    bot_id: str,
    session_id: str | None,
    *,
    max_pages: int | None = None,
) -> list[dict[str, object]]:
    args: dict[str, object] = {"id": bot_id, "limit": 100}
    if session_id is not None:
        args["sessionId"] = session_id
    entries: dict[str, dict[str, object]] = {}
    pages = 0
    while True:
        page = record(transport.command("getAgentTranscriptTail", args.copy()))
        rows = page.get("entries")
        if not isinstance(rows, list):
            raise TypeError("Invalid transcript page from gateway.")
        for row in rows:
            entry = record(row)
            if isinstance(entry.get("id"), str):
                entries.setdefault(str(entry["id"]), entry)
        pages += 1
        cursor = page.get("nextBeforeSeq")
        if not isinstance(cursor, (int, float)):
            break
        previous = args.get("beforeSeq")
        if isinstance(previous, (int, float)) and cursor >= previous:
            raise ValueError("Transcript pagination did not advance.")
        if max_pages is not None and pages >= max_pages:
            break
        args["beforeSeq"] = cursor
    return list(entries.values())


def discover(
    transport: Transport,
    rows: list[dict[str, object]],
    *,
    selected: str | None = None,
    all_bots: bool = False,
    awaiting_only: bool = True,
    recent_pages: int | None = None,
) -> tuple[list[Card], list[str]]:
    warnings: list[str] = []
    found: dict[tuple[str, str], Card] = {}
    for bot in rows:
        bot_id, name = str(bot["id"]), str(bot["name"])
        if selected is not None:
            if selected != bot_id:
                continue
        elif not all_bots and awaiting_only and not bot.get("awaitingUserResponse"):
            continue
        sessions: list[str | None] = [None]
        awaiting = bot.get("awaitingSessionIds")
        if isinstance(awaiting, list):
            sessions.extend(dict.fromkeys(s for s in awaiting if isinstance(s, str)))
        # A bot the roster shows as waiting is always read in full; the cap only spares the others.
        cap = None if waiting(bot) else recent_pages
        try:
            scanned = [
                (session_id, tail(transport, bot_id, session_id, max_pages=cap))
                for session_id in sessions
            ]
        except Exception as exc:
            # Auth failures must fail the command, or an expired login reads as "nothing pending".
            if not all_bots or (isinstance(exc, ConnectError) and exc.status == 401):
                raise
            warnings.append(f"{one_line(name)}: {one_line(str(exc))}")
            continue
        for session_id, entries in scanned:
            for entry in entries:
                key = (bot_id, str(entry["id"]))
                item = classify(entry, bot_id, name, session_id)
                if item is not None:
                    found[key] = item
                else:
                    found.pop(key, None)
    return list(found.values()), warnings


def still_pending(transport: Transport, card: Card) -> bool:
    args: dict[str, object] = {"id": card.bot_id, "limit": 100}
    if card.session_id is not None:
        args["sessionId"] = card.session_id
    for _ in range(5):
        page = record(transport.command("getAgentTranscriptTail", args.copy()))
        rows = page.get("entries")
        if not isinstance(rows, list):
            raise TypeError("Invalid transcript page from gateway.")
        for row in rows:
            entry = record(row)
            if entry.get("id") == card.entry_id:
                return (
                    classify(entry, card.bot_id, card.bot_name, card.session_id)
                    is not None
                )
        cursor = page.get("nextBeforeSeq")
        if not isinstance(cursor, (int, float)):
            break
        previous = args.get("beforeSeq")
        if isinstance(previous, (int, float)) and cursor >= previous:
            raise ValueError("Transcript pagination did not advance.")
        args["beforeSeq"] = cursor
    return False
