"""Cloud agents, their published apps, app secret names and publish proposals (gateway commands)."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

from .errors import refusal
from .models import _record, _text
from .transport import Transport

COMMANDS = {
    "getCloudAgentInfo": "object",
    "getCloudAgentConversation": "object",
    "stopCloudAgent": "object",
    "listCloudAgentPublishedApps": "none",
    "updateCloudAgentPublishApp": "object",
    "unpublishCloudAgentPublishApp": "object",
    "getCloudAgentAppSecrets": "object",
    "setCloudAgentAppSecrets": "object",
    "tellCloudAgentAppSecretsSet": "object",
    "getCloudAgentPublishProposals": "object",
    "confirmCloudAgentPublishProposal": "object",
    "dismissCloudAgentPublishProposal": "object",
}

VISIBILITIES = ("unspecified", "private", "team", "public")
REFUSAL_KINDS = ("not_owned", "not_sensitive", "host_error", "value_not_saved")
NOT_FOUND = "No cloud agent with that id."
APPS_OFF = "Cloud-agent apps are off for this account."
APPS_UNKNOWN = "Cloud-agent apps returned an unknown state."
NO_APPS = "No published apps."
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)
_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")


def _enum(value: object, names: Sequence[str]) -> str:
    """Full names (any `..._PRIVATE` prefix), short names or numbers to a lowercase short name, else unknown."""
    if isinstance(value, int) and not isinstance(value, bool):
        return names[value] if 0 <= value < len(names) else "unknown"
    if not isinstance(value, str) or not value:
        return "unknown"
    name = value.strip().lower()
    if name.isdecimal():
        return _enum(int(name), names)
    if name in names:
        return name
    return next(
        (
            item
            for item in sorted(names, key=len, reverse=True)
            if name.endswith("_" + item)
        ),
        "unknown",
    )


def _safe(text: str) -> str:
    """Replies may carry access links; never pass a URL on."""
    return _URL.sub("[link hidden]", text)


def _redact(text: str, values: Mapping[str, str]) -> str:
    for value in sorted(values.values(), key=len, reverse=True):
        if value:
            text = text.replace(value, "[redacted]")
    return _safe(text)


def _first(row: Mapping[str, object], keys: Sequence[str], kind: type) -> object:
    for key in keys:
        value = row.get(key)
        if isinstance(value, kind) and not isinstance(value, bool):
            return value
    return None


def _count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _stamp(row: Mapping[str, object]) -> int | None:
    for key in ("createdAt", "createdAtMs"):
        value = row.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().isdecimal():
            return int(value.strip())
    return None


def _repo(value: str) -> str:
    if not _URL.match(value):
        return value
    parts = urlsplit(value)
    # Only host and path: user info, query and fragment can carry credentials.
    return (parts.hostname or "") + parts.path


def _rows(value: object) -> tuple[Mapping[str, object], ...]:
    return (
        tuple(row for row in value if isinstance(row, Mapping))
        if isinstance(value, list)
        else ()
    )


@dataclass(frozen=True)
class CloudAgentInfo:
    bc_id: str
    status: str
    title: str
    branch: str
    repo: str
    created_at: int | None
    file_count: int
    artifact_count: int
    extra: tuple[str, ...] = ()

    @property
    def fields(self) -> tuple[tuple[str, str], ...]:
        stamp = self.created_at
        created = (
            datetime.fromtimestamp(stamp / 1000, UTC).strftime("%Y-%m-%d %H:%M UTC")
            if stamp is not None and 0 < stamp < 10**14
            else "unknown"
        )
        return (
            ("Cloud agent", self.bc_id),
            ("Status", self.status or "unknown"),
            ("Title", self.title or "none"),
            ("Branch", self.branch or "none"),
            ("Repository", self.repo or "none"),
            ("Created", created),
            ("Files", str(self.file_count)),
            ("Artifacts", str(self.artifact_count)),
            *((("Other fields", ", ".join(self.extra)),) if self.extra else ()),
        )


_INFO_KEYS = frozenset(
    {
        "bcId",
        "id",
        "status",
        "state",
        "title",
        "name",
        "branch",
        "repo",
        "repository",
        "createdAt",
        "createdAtMs",
        "files",
        "artifacts",
    }
)


def info(
    transport: Transport,
    bc_id: str,
    *,
    include_files: bool = False,
    include_artifacts: bool = False,
) -> CloudAgentInfo | None:
    reply = transport.command(
        "getCloudAgentInfo",
        {
            "bcId": bc_id,
            "includeFiles": include_files,
            "includeArtifacts": include_artifacts,
        },
    )
    if not isinstance(reply, Mapping):
        return None
    row: Mapping[str, object] = reply
    return CloudAgentInfo(
        _text(_first(row, ("bcId", "id"), str)) or bc_id,
        _safe(_text(_first(row, ("status", "state"), str))),
        _safe(_text(_first(row, ("title", "name"), str))),
        _safe(_text(_first(row, ("branch",), str))),
        _repo(_text(_first(row, ("repo", "repository"), str))),
        _stamp(row),
        _count(row.get("files")),
        _count(row.get("artifacts")),
        tuple(sorted(str(key) for key in row if key not in _INFO_KEYS)),
    )


@dataclass(frozen=True)
class Message:
    role: str
    text: str


def _message_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            part
            if isinstance(part, str)
            else _text(part.get("text"))
            if isinstance(part, Mapping)
            else ""
            for part in value
        )
    return ""


def _messages(row: Mapping[str, object]) -> tuple[Message, ...]:
    for key in ("messages", "conversation", "turns"):
        value = row.get(key)
        if isinstance(value, list):
            return tuple(
                Message(
                    _safe(_text(_first(item, ("role", "type"), str)) or "unknown"),
                    _safe(
                        _message_text(
                            item.get("text")
                            if item.get("text") is not None
                            else item.get("content")
                        )
                    ),
                )
                for item in _rows(value)
            )
    return ()


def conversation(transport: Transport, bc_id: str) -> tuple[Message, ...]:
    return _messages(
        _record(transport.command("getCloudAgentConversation", {"bcId": bc_id}))
    )


def stop(transport: Transport, bc_id: str) -> None:
    transport.command("stopCloudAgent", {"bcId": bc_id})


@dataclass(frozen=True)
class PublishedApp:
    bc_id: str
    slug: str
    apex: str
    visibility: str
    url: str = field(default="", repr=False)


@dataclass(frozen=True)
class AppsState:
    kind: str
    apps: tuple[PublishedApp, ...] = ()

    @property
    def sentence(self) -> str:
        if self.kind == "off":
            return APPS_OFF
        if self.kind == "unknown":
            return APPS_UNKNOWN
        return "" if self.apps else NO_APPS


def _app(row: Mapping[str, object]) -> PublishedApp:
    return PublishedApp(
        _safe(_text(_first(row, ("bcId", "bc_id"), str))),
        _safe(_text(row.get("slug"))),
        _safe(_text(row.get("apex"))),
        _enum(row.get("visibility"), VISIBILITIES),
        _text(row.get("url")),
    )


def apps(transport: Transport) -> AppsState:
    reply = _record(transport.command("listCloudAgentPublishedApps"))
    rows = _first(reply, ("apps", "publishedApps", "items"), list)
    kind = _text(reply.get("kind")).strip().lower()
    if kind in {"off", "disabled"}:
        kind = "off"
    elif kind in {"on", "enabled"} or (not kind and rows is not None):
        kind = "on"
    else:
        kind = "unknown"
    return AppsState(kind, tuple(_app(row) for row in _rows(rows)))


@dataclass(frozen=True)
class AppResult:
    ok: bool
    state: str
    message: str


_FAILED_WORDS = frozenset({"failed", "error", "rejected"})


def _result(reply: object) -> AppResult:
    row = _record(reply)
    error = row.get("error")
    if isinstance(error, Mapping):
        error = error.get("message")
    message = _text(row.get("message")) or _text(error)
    state = _text(_first(row, ("state", "status", "outcome", "kind"), str)).lower()
    # A state word that says the change failed wins over a missing or true `ok`.
    failed = state.rsplit("_", 1)[-1] in _FAILED_WORDS
    ok = row.get("ok")
    ok = (ok if isinstance(ok, bool) else not error) and not failed
    return AppResult(ok, state or ("ok" if ok else "error"), _safe(message)[:300])


def _visibility(value: str) -> str:
    name = _enum(value, VISIBILITIES)
    if name in {"unknown", "unspecified"}:
        raise ValueError("Visibility must be private, team or public.")
    return name


def update_app(
    transport: Transport,
    bc_id: str,
    slug: str,
    apex: str,
    visibility: str,
    *,
    mute_redeploy_prompts: bool = False,
    require_confirmation_for_updates: bool = False,
) -> AppResult:
    return _result(
        transport.command(
            "updateCloudAgentPublishApp",
            {
                "bcId": bc_id,
                "slug": slug,
                "apex": apex,
                "visibility": _visibility(visibility),
                "muteRedeployPrompts": mute_redeploy_prompts,
                "requireConfirmationForUpdates": require_confirmation_for_updates,
            },
        )
    )


def unpublish_app(transport: Transport, bc_id: str, slug: str, apex: str) -> AppResult:
    return _result(
        transport.command(
            "unpublishCloudAgentPublishApp",
            {"bcId": bc_id, "slug": slug, "apex": apex},
        )
    )


def _names(value: object) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        return tuple(str(key) for key in value)
    if isinstance(value, list):
        return tuple(
            item if isinstance(item, str) else _text(_record(item).get("name"))
            for item in value
            if isinstance(item, str) or _text(_record(item).get("name"))
        )
    return ()


def app_secret_names(
    transport: Transport, bc_id: str, project_dir: str
) -> tuple[str, ...]:
    """Names only, whatever the reply shape: any value in the reply is dropped here."""
    reply = _record(
        transport.command(
            "getCloudAgentAppSecrets", {"bcId": bc_id, "projectDir": project_dir}
        )
    )
    if "secrets" in reply:
        found = _names(reply.get("secrets"))
    elif "names" in reply:
        found = _names(reply.get("names"))
    elif reply and all(isinstance(value, str | type(None)) for value in reply.values()):
        # A bare map is taken as names only when every key looks like an env var name.
        found = tuple(str(key) for key in reply if _ENV_NAME.fullmatch(str(key)))
    else:
        found = ()
    return tuple(dict.fromkeys(_safe(name) for name in found if name))


@dataclass(frozen=True)
class SecretRefusal:
    name: str
    kind: str
    message: str
    permanent: bool = False

    def record(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind,
            "message": self.message,
            "permanent": self.permanent,
        }


@dataclass(frozen=True)
class SetResult:
    saved: tuple[str, ...]
    refused: tuple[SecretRefusal, ...]
    apply_needed: bool


def set_app_secrets(
    transport: Transport, bc_id: str, project_dir: str, values: Mapping[str, str]
) -> SetResult:
    names = tuple(values)
    secrets = [{"name": name, "value": value} for name, value in values.items()]
    try:
        reply = _record(
            transport.command(
                "setCloudAgentAppSecrets",
                {"bcId": bc_id, "projectDir": project_dir, "secrets": secrets},
            )
        )
    except Exception as error:  # noqa: BLE001 - secret transport redaction boundary
        # Transport failures may quote the request body: keep only a refusal's own words, minus any value.
        found = refusal(error)
        message = (
            found.message
            if found
            else "App secrets were not saved; no value is displayed."
        )
        raise ValueError(_redact(message, values)) from None
    refused = tuple(
        SecretRefusal(
            _redact(_text(row.get("name")), values),
            _enum(row.get("kind"), REFUSAL_KINDS),
            _redact(_text(row.get("message")), values)[:300],
            row.get("permanent") is True,
        )
        for row in _rows(reply.get("refused"))
    )
    listed = _names(reply.get("saved")) if "saved" in reply else None
    blocked = {item.name for item in refused}
    saved = (
        tuple(name for name in listed if name in values)
        if listed is not None
        else tuple(name for name in names if name not in blocked)
    )
    return SetResult(saved, refused, reply.get("applyNeeded") is True)


def tell_secrets_set(
    transport: Transport,
    bc_id: str,
    project_dir: str,
    names: Sequence[str],
    refused: Sequence[SecretRefusal],
    apply_needed: bool,
) -> object:
    return transport.command(
        "tellCloudAgentAppSecretsSet",
        {
            "bcId": bc_id,
            "projectDir": project_dir,
            "names": list(names),
            "refused": [item.record() for item in refused],
            "applyNeeded": apply_needed,
        },
    )


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    slug: str
    visibility: str
    summary: str


def proposals(transport: Transport, bc_id: str) -> tuple[Proposal, ...]:
    reply = _record(transport.command("getCloudAgentPublishProposals", {"bcId": bc_id}))
    rows = _first(reply, ("proposals", "items"), list)
    return tuple(
        Proposal(
            _safe(_text(_first(row, ("proposalId", "id"), str))),
            _safe(_text(row.get("slug"))),
            _enum(row.get("visibility"), VISIBILITIES),
            _safe(_text(_first(row, ("summary", "description", "title"), str))),
        )
        for row in _rows(rows)
    )


def confirm_proposal(
    transport: Transport,
    bot_id: str,
    bc_id: str,
    proposal_id: str,
    slug: str,
    visibility: str,
    require_confirmation_for_updates: bool = False,
) -> AppResult:
    return _result(
        transport.command(
            "confirmCloudAgentPublishProposal",
            {
                "agentId": bot_id,
                "bcId": bc_id,
                "proposalId": proposal_id,
                "slug": slug,
                "visibility": _visibility(visibility),
                "requireConfirmationForUpdates": require_confirmation_for_updates,
            },
        )
    )


def dismiss_proposal(
    transport: Transport, bc_id: str, proposal_id: str, bot_id: str | None = None
) -> AppResult:
    payload: dict[str, object] = {"bcId": bc_id, "proposalId": proposal_id}
    if bot_id is not None:
        payload["agentId"] = bot_id
    return _result(transport.command("dismissCloudAgentPublishProposal", payload))


DEMO_COMMANDS: dict[str, object] = {
    "getCloudAgentInfo": lambda args: {
        "bcId": args["bcId"],
        "status": "RUNNING",
        "title": "Build the landing page",
        "branch": "cursor/landing-page",
        "repository": "github.com/demo/site",
        "createdAtMs": "1800000000000",
        "files": [{"path": "index.html"}],
        "artifacts": [],
    },
    "getCloudAgentConversation": {
        "messages": [
            {"role": "user", "text": "Build a landing page for the demo."},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "The page is ready to publish."}],
            },
        ]
    },
    "stopCloudAgent": None,
    "listCloudAgentPublishedApps": {
        "kind": "on",
        "apps": [
            {
                "bcId": "bc-demo-1",
                "slug": "landing",
                "apex": "demo.example",
                "visibility": "public",
            },
            {
                "bcId": "bc-demo-2",
                "slug": "dashboard",
                "apex": "demo.example",
                "visibility": "team",
            },
        ],
    },
    "updateCloudAgentPublishApp": {},
    "unpublishCloudAgentPublishApp": {},
    "getCloudAgentAppSecrets": {"secrets": [{"name": "DEMO_API_KEY"}]},
    "setCloudAgentAppSecrets": {},
    "tellCloudAgentAppSecretsSet": {},
    "getCloudAgentPublishProposals": {
        "proposals": [
            {
                "proposalId": "proposal-demo",
                "slug": "landing",
                "visibility": "private",
                "summary": "Publish the landing page",
            }
        ]
    },
    "confirmCloudAgentPublishProposal": {},
    "dismissCloudAgentPublishProposal": {},
}
