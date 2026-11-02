"""Desktop-compatible backend routing for known temporal bots."""

import json
import math
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING

from groken.client import ConnectError

if TYPE_CHECKING:
    from .transport import Transport


class Harness:
    """Per-owner harness knowledge, shared safely by foreground and background calls."""

    def __init__(self) -> None:
        self._rows: dict[str, object] = {}
        self._lock = threading.RLock()
        self._mirrors: list[threading.Thread] = []

    def background(self, action: Callable[[], None]) -> None:
        with self._lock:
            self._mirrors = [thread for thread in self._mirrors if thread.is_alive()]
            thread = threading.Thread(target=action, daemon=True)
            self._mirrors.append(thread)
            thread.start()

    def drain(self) -> None:
        """Finish scheduled mirror cleanup before the owner closes its transports."""
        with self._lock:
            pending, self._mirrors = self._mirrors, []
        for thread in pending:
            thread.join()

    def learn(self, rows: Iterable[object]) -> None:
        with self._lock:
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                identity = row.get("agentId", row.get("id"))
                if isinstance(identity, str) and identity:
                    self._rows[identity] = row.get(
                        "harness", self._rows.get(identity, "box")
                    )

    def temporal(self, identity: object) -> bool:
        with self._lock:
            return isinstance(identity, str) and self._rows.get(identity) == "temporal"


# Request fields are an allowlist: unrelated gateway metadata is never forwarded.
ROUTES = {
    "setAgentUnread": ("SetGrokBotAgentClientState", ""),
    "setAgentHiddenFromSidebar": ("SetGrokBotAgentClientState", ""),
    "setAgentNotifyOnUpdates": ("SetGrokBotAgentClientState", ""),
    "setAgentDraftingDisabled": ("SetGrokBotAgentDraftingDisabled", ""),
    "dismissAgentSuggestions": ("DismissGrokBotAgentSuggestions", "suggestionIds"),
    "voteFeedback": ("VoteGrokBotFeedback", "entryId comment"),
    "reactToMessage": ("ReactToGrokBotMessage", "entryId emoji"),
    "createThreadFromMessage": ("CreateGrokBotThreadFromMessage", "entryId"),
    "resolveConnectorGrant": ("ResolveGrokBotConnectorGrant", "requestId entryId"),
    "getSubagents": ("ListGrokBotSubagents", ""),
    "getAgentTasks": ("ListGrokBotAgentTasks", ""),
    "markAgentTaskDone": ("MarkGrokBotAgentTaskDone", "taskId"),
    "markAgentTaskRead": ("MarkGrokBotAgentTaskRead", "taskId entryId"),
    "setAgentTaskPinned": ("SetGrokBotAgentTaskPinned", "taskId"),
    "interruptAgentRun": ("InterruptGrokBotAgentRun", ""),
    "startFreshConversation": ("StartFreshGrokBotConversation", ""),
    "rollBackConversation": ("RollBackGrokBotConversation", ""),
}
# The send path: a temporal send goes only to the backend, a box send only to the gateway.
SEND_ROUTES = {
    "sendPrompt": "SendGrokBotUserMessage",
    "promptAcceptanceStatus": "GetGrokBotSendStatus",
}
RPCS = (
    tuple(dict.fromkeys(rpc for rpc, _ in ROUTES.values()))
    + ("DeleteGrokBotAgent",)
    + tuple(SEND_ROUTES.values())
)
_SESSION = {"voteFeedback", "reactToMessage", "resolveConnectorGrant"}
_RUNS = {"interruptAgentRun", "startFreshConversation", "rollBackConversation"}
_TASKS = {
    "getAgentTasks",
    "markAgentTaskDone",
    "markAgentTaskRead",
    "setAgentTaskPinned",
}
_DELETE = "deleteAgents"


def _request(name: str, args: Mapping[str, object]) -> dict[str, object]:
    payload = {key: args[key] for key in ROUTES[name][1].split() if key in args}
    target = args.get("agentId", args.get("id"))
    payload["id" if name == "setAgentDraftingDisabled" else "agentId"] = target
    session = args.get("sessionId")
    if (name in _SESSION and session) or (name in _RUNS and session is not None):
        payload["sessionId"] = session
    if name == "setAgentUnread":
        payload["markUnread" if args.get("isUnread") is True else "markRead"] = True
        if args.get("markFollowedThreadsRead") is True:
            payload["markFollowedThreadsRead"] = True
    for command, source, destination in (
        ("setAgentHiddenFromSidebar", "isHidden", "hiddenFromSidebar"),
        ("setAgentNotifyOnUpdates", "isEnabled", "notifyOnUpdatesEnabled"),
        ("setAgentDraftingDisabled", "isDisabled", "disabled"),
        ("setAgentTaskPinned", "isPinned", "pinned"),
    ):
        if name == command:
            payload[destination] = args[source]
    for command, field, prefix in (
        (
            "dismissAgentSuggestions",
            "reason",
            "GROK_BOT_AGENT_SUGGESTION_DISMISS_REASON_",
        ),
        ("voteFeedback", "action", "GROK_BOT_FEEDBACK_ACTION_"),
        ("resolveConnectorGrant", "resolution", "GROK_BOT_CONNECTOR_GRANT_RESOLUTION_"),
    ):
        if name == command:
            payload[field] = prefix + str(args[field]).upper()
    if name == "voteFeedback":
        payload["categories"] = list(args.get("categories", []))  # type: ignore[arg-type]
    if name == "getAgentTasks":
        payload["includeRecentlyDone"] = True
    if name == "interruptAgentRun":
        payload["reason"] = "user_interrupt"
    return payload


def _number(value: object) -> int:
    return int(str(value or 0))


def _reply(name: str, reply: Mapping[str, object]) -> object:
    if "refusal" in reply:
        from .cards import check_reply

        check_reply(reply, ROUTES[name][0])
    if name == "setAgentHiddenFromSidebar":
        state = reply.get("state")
        updated = _number(state.get("updatedAtMs")) if isinstance(state, Mapping) else 0
        return {"stateUpdatedAt": updated} if updated > 0 else None
    if name == "interruptAgentRun":
        return {"hadActiveRun": reply.get("hadActiveRun", False)}
    if name in _TASKS or name == "getSubagents":
        result = []
        rows = reply.get("tasks" if name in _TASKS else "subagents", [])
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            if name in _TASKS:
                item = {key: row.get(key, "") for key in ("id", "name", "description")}
                status = re.sub(
                    r"[\s-]+", "_", str(row.get("status", "")).strip().lower()
                )
                item["status"] = "done" if status == "done" else "open"
                item["updatedAtMs"] = _number(row.get("updatedAtMs"))
                for key in (
                    "unreadEntryId",
                    "unreadPreview",
                    "unreadAtMs",
                    "pinnedAtMs",
                ):
                    if key in row:
                        item[key] = (
                            _number(row[key]) if key.endswith("Ms") else row[key]
                        )
                if row.get("subagentIds"):
                    item["subagentIds"] = list(row["subagentIds"])
            else:
                item = {
                    key: row.get(key, "")
                    for key in ("subagentId", "subagentType", "title")
                }
                item.update(
                    status="running", startedAtMs=_number(row.get("startedAtMs"))
                )
                if _number(row.get("freshUntilMs")) > 0:
                    item["freshUntilMs"] = _number(row["freshUntilMs"])
            result.append(item)
        return result
    return None


def now_ms() -> int:
    return int(time.time() * 1000)


def _int64(value: object) -> str | None:
    """A JSON number as a protobuf JSON int64 (a decimal string); anything else is dropped."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return str(math.floor(value))


def _age(args: Mapping[str, object], now: int) -> dict[str, str]:
    sent = args.get("firstSentAtMs")
    if isinstance(sent, bool) or not isinstance(sent, int | float):
        return {}
    return {"firstSentAgeMs": str(max(0, math.floor(now - sent)))}


def _nonce(args: Mapping[str, object]) -> str:
    nonce = args.get("clientNonce")
    if not isinstance(nonce, str) or not nonce:
        raise ValueError("A temporal bot send needs a clientNonce.")
    return nonce


def _send_request(args: Mapping[str, object], now: int) -> dict[str, object]:
    """sendPrompt arguments as SendGrokBotUserMessage (docs/protocol-temporal.md section 1).

    source, initiator and sendSource are not forwarded: their protobuf enum names are not documented.
    """
    payload: dict[str, object] = {
        "agentId": args.get("agentId"),
        "messageId": _nonce(args),
        "text": args.get("prompt", ""),
        "sentAtMs": str(now),
    }
    for key in (
        "richText",
        "replyToId",
        "replyQuote",
        "traceparent",
        "mcpConfigJson",
        "taskId",
        "language",
    ):
        if args.get(key) is not None:
            payload[key] = args[key]
    if args.get("isFork") is True:
        payload["isFork"] = True
    for key in ("attachmentPaths", "attachmentNames"):
        value = args.get(key)
        payload[key] = list(value) if isinstance(value, list | tuple) else []
    for key in ("enterEpochMs", "composedAtMs"):
        number = _int64(args.get(key))
        if number is not None:
            payload[key] = number
    for key in ("sessionId", "machineId"):
        if args.get(key):
            payload[key] = args[key]
    for key in ("onePasswordAppInstalled", "rendersMcpElicitationForms"):
        if args.get(key) is True:
            payload[key] = True
    payload.update(_age(args, now))
    return payload


def _status_request(args: Mapping[str, object], now: int) -> dict[str, object]:
    payload: dict[str, object] = {
        "agentId": args.get("agentId"),
        "messageId": _nonce(args),
    }
    if args.get("sessionId"):
        payload["sessionId"] = args["sessionId"]
    if args.get("taskId") is not None:
        payload["taskId"] = args["taskId"]
    payload.update(_age(args, now))
    return payload


def _enum(value: object, *names: str) -> str | None:
    """The documented short name an enum value ends with; the full protobuf prefix is not documented."""
    if not isinstance(value, str):
        return None
    return next(
        (name for name in names if value == name or value.endswith("_" + name)), None
    )


def _enums(reply: Mapping[str, object]) -> list[str]:
    return [
        value
        for value in reply.values()
        if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]*", value)
    ]


def _send_reply(reply: Mapping[str, object]) -> dict[str, object]:
    refusal = reply.get("refusal")
    if isinstance(refusal, Mapping):
        detail = f"Send refused: {refusal.get('failureCode') or 'unknown'}"
        if refusal.get("message"):
            detail += f": {refusal['message']}"
        raise ValueError(detail)  # noqa: TRY004 - a refusal is a service error
    values = _enums(reply)
    if any(_enum(v, "ACCEPTED_BOX", "ACCEPTED_TEMPORAL", "DUPLICATE") for v in values):
        return {"accepted": True}
    delivery = next((v for v in values if _enum(v, "REFUSED")), None)
    if delivery is None:
        named = reply.get("delivery")
        delivery = named if isinstance(named, str) and named else "unknown delivery"
    raise ValueError(f"Send refused: {delivery}")


def _status_reply(
    reply: Mapping[str, object], args: Mapping[str, object]
) -> dict[str, object]:
    outcome = reply.get("outcome")
    if _enum(outcome, "NOT_FOUND"):
        return {"outcome": "not-found"}
    nested = reply.get("record")
    record = nested if isinstance(nested, Mapping) else reply
    status = _enum(record.get("status"), "ACCEPTED", "REJECTED", "PENDING")
    if not _enum(outcome, "FOUND") or status is None:
        return {"outcome": "unknown-durability"}
    status = status.lower()
    echo = record.get("echoEntryId")
    code = record.get("rejectionCode")
    return {
        "accountSlot": "host",
        "clientNonce": args.get("clientNonce"),
        "agentId": args.get("agentId"),
        "inputDigest": "",
        "status": status,
        "acceptedAtMs": _number(record.get("acceptedAtMs")),
        "echoEntryId": echo if isinstance(echo, str) and echo else None,
        "rejectionCode": code
        if status == "rejected" and isinstance(code, str) and code
        else None,
    }


class Router:
    """Transport wrapper; only explicit temporal routes use backend twins."""

    def __init__(
        self, inner: "Transport", harness: Harness, *, mirror: "Transport | None" = None
    ) -> None:
        self.inner = inner
        self.harness = harness
        self.mirror = mirror or inner

    def _mirror(self, name: str, args: Mapping[str, object]) -> None:
        def run() -> None:
            try:
                self.mirror.command(name, args)
            except Exception:  # noqa: BLE001, S110 - mirrors never affect backend success
                # Backend success is authoritative; stale pod cleanup is best effort.
                pass

        self.harness.background(run)

    def command(self, name: str, args: Mapping[str, object] | None = None) -> object:
        sent = dict(args or {})
        ids = sent.get("ids")
        if (
            name == "deleteAgents"
            and isinstance(ids, list)
            and any(self.harness.temporal(identity) for identity in ids)
        ):
            return self._delete(ids)
        if name in SEND_ROUTES and self.harness.temporal(sent.get("agentId")):
            now = now_ms()
            if name == "sendPrompt":
                return _send_reply(
                    self.rpc(SEND_ROUTES[name], _send_request(sent, now))
                )
            payload = _status_request(sent, now)
            return _status_reply(self.rpc(SEND_ROUTES[name], payload), sent)
        if name in ROUTES and self.harness.temporal(
            sent.get("agentId", sent.get("id"))
        ):
            reply = _reply(name, self.rpc(ROUTES[name][0], _request(name, sent)))
            if name == "setAgentNotifyOnUpdates":
                self._mirror(name, sent)
            return reply
        reply = self.inner.command(name, args)
        if name == "listAgents" and isinstance(reply, list):
            self.harness.learn(reply)
        elif name in {
            "createAgent",
            "createGroup",
            "createAgentFromTemplate",
        } and isinstance(reply, Mapping):
            self.harness.learn([reply.get("agent")])
        return reply

    def rpc(self, method: str, payload: Mapping[str, object]) -> dict[str, object]:
        reply = self.inner.rpc(method, payload)
        rows = reply.get("agents")
        if method == "ListGrokBotAgents" and isinstance(rows, list):
            self.harness.learn(rows)
        return reply

    def _delete(self, ids: list[object]) -> dict[str, object]:
        deleted, refused, failed = [], [], []
        box = [identity for identity in ids if not self.harness.temporal(identity)]
        for identity in ids:
            if not self.harness.temporal(identity):
                continue
            try:
                self.rpc("DeleteGrokBotAgent", {"id": identity})
                deleted.append(identity)
            except Exception as exc:  # noqa: BLE001 - isolate each deletion failure
                code = ""
                if isinstance(exc, ConnectError):
                    try:
                        code = json.loads(exc.body).get("code", "")
                    except (ValueError, AttributeError):
                        pass
                    if exc.status == 404 or code == "not_found":
                        deleted.append(identity)
                        continue
                (
                    refused
                    if code == "permission_denied"
                    or isinstance(exc, ConnectError)
                    and exc.status == 403
                    else failed
                ).append(identity)
        raw = self.inner.command(_DELETE, {"ids": box}) if box else {}
        result = dict(raw) if isinstance(raw, Mapping) else {}
        result.setdefault("transcript", [])
        for key, values in (("refusedAgentIds", refused), ("failedAgentIds", failed)):
            if values:
                result[key] = list(result.get(key, [])) + values
        if deleted:
            self._mirror("deleteAgents", {"ids": deleted})
        return result
