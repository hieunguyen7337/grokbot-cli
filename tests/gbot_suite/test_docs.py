import argparse
import importlib
import pkgutil
import re
from pathlib import Path

from gbot import cli, commands

ROOT = Path(__file__).resolve().parents[2]


def _options(parser: argparse.ArgumentParser) -> set[str]:
    # A command's flags include those of its subcommands (gbot channels slack ...).
    found = set(parser._option_string_actions)
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                found |= _options(child)
    return found


def command_options() -> dict[str, set[str]]:
    parser = cli.Parser(prog="gbot")
    subparsers = parser.add_subparsers(dest="command")
    for module in pkgutil.iter_modules(commands.__path__):
        importlib.import_module(f"{commands.__name__}.{module.name}").register(
            subparsers
        )
    return {name: _options(command) for name, command in subparsers.choices.items()}


def test_reference_flags_match_parser() -> None:
    options = command_options()
    reference = (ROOT / "docs/gbot.md").read_text(encoding="utf-8")
    sections = re.split(r"^## (\w+)\s*$", reference, flags=re.MULTILINE)
    found = set()
    for name, section in zip(sections[1::2], sections[2::2]):
        if name not in options:
            continue
        found.add(name)
        flags = set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", section))
        assert flags <= options[name], (name, flags - options[name])
    assert found == set(options)


def test_guide_and_skill_example_flags_match_parser() -> None:
    options = command_options()
    for path in (ROOT / "docs/agents.md", ROOT / "skills/gbot/SKILL.md"):
        content = path.read_text(encoding="utf-8")
        examples = re.findall(r"\bgbot (\w+)[^\n`]*", content)
        assert examples
        for example in examples:
            name = example.split()[0]
            if name not in options:
                continue
            flags = set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", example))
            assert flags <= options[name], (path, name, flags - options[name])


def test_guide_exit_codes_match_help(capsys) -> None:
    try:
        cli.main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    help_text = capsys.readouterr().out
    epilog = help_text.split("Exit codes:", 1)[1]
    expected = set(
        re.findall(
            r"\b(\d+)\s+(?:ok|error|needs attention|not signed in|still working|interrupted)",
            epilog,
        )
    )
    guide = (ROOT / "docs/agents.md").read_text(encoding="utf-8")
    exit_list = guide.split("Exit codes:", 1)[1].split("\n\n", 2)[1]
    actual = set(re.findall(r"^- (\d+):", exit_list, flags=re.MULTILINE))
    assert actual == expected == {"0", "1", "2", "3", "4", "130"}
