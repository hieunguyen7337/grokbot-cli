import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from groken import winplat
from groken.private_files import write_private_text


@dataclass(frozen=True)
class Prefs:
    pins: tuple[str, ...] = ()
    order: tuple[str, ...] = ()
    collapsed: frozenset[str] = frozenset()
    group_by: str = "state"
    last_seen: Mapping[str, int] = field(default_factory=dict)


def path() -> Path:
    return winplat.data_dir() / "tui.json"


def load(path: Path) -> Prefs:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return Prefs()
    if not isinstance(data, dict):
        return Prefs()

    def strings(key: str) -> tuple[str, ...]:
        value = data.get(key)
        return (
            tuple(value)
            if isinstance(value, list) and all(isinstance(v, str) for v in value)
            else ()
        )

    group_by = data.get("group_by")
    seen = data.get("last_seen")
    if not isinstance(seen, dict) or not all(
        isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v >= 0
        for k, v in seen.items()
    ):
        seen = {}
    return Prefs(
        strings("pins"),
        strings("order"),
        frozenset(strings("collapsed")),
        group_by if group_by in ("state", "team") else "state",
        seen,
    )


def save(path: Path, prefs: Prefs) -> None:
    data = {
        "pins": list(prefs.pins),
        "order": list(prefs.order),
        "collapsed": sorted(prefs.collapsed),
        "group_by": prefs.group_by,
        "last_seen": dict(prefs.last_seen),
    }
    write_private_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def toggle_pin(prefs: Prefs, bot_id: str) -> Prefs:
    return replace(
        prefs,
        pins=tuple(i for i in prefs.pins if i != bot_id)
        if bot_id in prefs.pins
        else (*prefs.pins, bot_id),
    )


def move_in_order(
    prefs: Prefs, bot_id: str, delta: int, visible_ids: Sequence[str]
) -> Prefs:
    visible = list(dict.fromkeys(visible_ids))
    if bot_id not in visible:
        return prefs
    index = visible.index(bot_id)
    target = max(0, min(len(visible) - 1, index + delta))
    visible.insert(target, visible.pop(index))
    return replace(
        prefs, order=tuple(visible + [i for i in prefs.order if i not in visible])
    )


def toggle_collapsed(prefs: Prefs, section_key: str) -> Prefs:
    return replace(prefs, collapsed=prefs.collapsed ^ {section_key})


def set_group_by(prefs: Prefs, group_by: str) -> Prefs:
    if group_by not in ("state", "team"):
        raise ValueError("Unknown grouping")
    return replace(prefs, group_by=group_by)


def mark_seen(prefs: Prefs, bot_id: str, seq: int) -> Prefs:
    return replace(
        prefs,
        last_seen={**prefs.last_seen, bot_id: max(seq, prefs.last_seen.get(bot_id, 0))},
    )


def first_run(prefs: Prefs, latest: Mapping[str, int]) -> Prefs:
    return prefs if prefs.last_seen else replace(prefs, last_seen=dict(latest))
