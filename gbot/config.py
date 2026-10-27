import json
from pathlib import Path
from typing import cast

from groken import winplat
from groken.private_files import write_private_text

from .output import Output

_warned: set[Path] = set()


def load() -> dict[str, object]:
    path = winplat.data_dir() / "gbot.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("expected an object")
        default = value.get("default_bot")
        if default is not None and (
            not isinstance(default, dict)
            or not all(
                isinstance(default.get(key), str) and default[key]
                for key in ("id", "name")
            )
        ):
            raise ValueError("invalid default bot")
        return cast(dict[str, object], value)
    except FileNotFoundError:
        return {}
    except (ValueError, TypeError, UnicodeError):
        if path not in _warned:
            _warned.add(path)
            Output().error(
                ValueError(
                    "Ignoring corrupt gbot.json; select a bot with: gbot use <name>"
                )
            )
        return {}


def default_bot() -> dict[str, str] | None:
    value = load().get("default_bot")
    return cast(dict[str, str], value) if isinstance(value, dict) else None


def set_default(bot: tuple[str, str] | None) -> None:
    value = load()
    if bot is None:
        value.pop("default_bot", None)
    else:
        value["default_bot"] = dict(zip(("id", "name"), bot))
    write_private_text(winplat.data_dir() / "gbot.json", json.dumps(value, indent=2))
