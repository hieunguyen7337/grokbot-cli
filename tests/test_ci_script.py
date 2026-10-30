import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts import ci


def test_selection_and_unknown_names():
    assert ci.select_stages(None, None, False) == list(ci.STAGES)
    assert ci.select_stages("tests,lint,build", "tests", False) == ["lint", "build"]
    assert ci.select_stages("live", None, True) == ["live"]
    with pytest.raises(ValueError, match="unknown stage.*bad"):
        ci.select_stages("bad", None, False)
    with pytest.raises(ValueError, match="unknown stage.*live"):
        ci.select_stages(None, "live", False)


def test_fail_fast_and_summary(capsys):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1)

    assert ci.execute(ci.STAGES, False, True, run) == 1
    assert calls == [ci.planned_commands()["lint"][0]]
    output = capsys.readouterr().out
    assert "== lint" in output
    assert "lint     FAIL" in output
    assert "format   SKIP" in output


def test_success_and_live_commands(capsys):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            command, 2 if command[4] == "approvals" else 0
        )

    assert ci.execute(["live"], True, False, run) == 0
    assert calls == [
        ["uv", "run", "--no-sync", "gbot", "doctor", "--json"],
        ["uv", "run", "--no-sync", "gbot", "status", "--json"],
        ["uv", "run", "--no-sync", "gbot", "bots", "--json"],
        ["uv", "run", "--no-sync", "gbot", "connectors", "--json"],
        ["uv", "run", "--no-sync", "gbot", "approvals", "--all", "--json"],
    ]
    assert "live     PASS" in capsys.readouterr().out


@pytest.mark.parametrize("windows", [False, True])
@pytest.mark.parametrize("tui_code,tui_output", [(0, "--demo"), (1, "--demo"), (0, "")])
def test_build_commands_and_cleanup(
    tmp_path, monkeypatch, windows, tui_code, tui_output
):
    monkeypatch.setattr(ci.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(ci, "WINDOWS", windows)
    calls = []
    temp_root = None

    def run(command, **kwargs):
        nonlocal temp_root
        calls.append(command)
        if command[:2] == ["uv", "build"]:
            dist = Path(command[-1])
            temp_root = dist.parent
            dist.mkdir()
            with zipfile.ZipFile(dist / "package.whl", "w") as wheel:
                for name in (
                    "skill/SKILL.md",
                    "docs/assets/groken-hero.png",
                    "docs/capabilities-0.30.0.md",
                ):
                    wheel.writestr("pkg.data/data/" + name, "test")
        if command[-2:] == ["install", "codex-skills"]:
            skill = Path(kwargs["env"]["HOME"]) / ".codex/skills/groken/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("test")
        if command[-2:] == ["tui", "--help"]:
            assert kwargs["capture_output"] and kwargs["text"]
            return subprocess.CompletedProcess(command, tui_code, stdout=tui_output)
        return subprocess.CompletedProcess(command, 0)

    success = tui_code == 0 and "--demo" in tui_output
    assert ci.build(run) == success
    assert [cmd[:2] for cmd in calls[:3]] == [
        ["uv", "build"],
        ["uv", "venv"],
        ["uv", "pip"],
    ]
    assert calls[3][-1] == "--help"
    # The upstream groken CLI cannot start on Windows, so its smoke test is POSIX-only.
    assert calls[4][-2:] == ["tui", "--help"]
    assert len(calls) == (5 if windows or not success else 6)
    if not windows and success:
        assert calls[5][-2:] == ["install", "codex-skills"]
    assert temp_root is not None and not temp_root.exists()


def test_workflow_is_manual_only():
    workflow = (ci.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    triggers = workflow.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert "workflow_dispatch:" in triggers
    assert "push:" not in triggers
    assert "pull_request:" not in triggers
