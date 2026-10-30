import argparse
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = os.name == "nt"
STAGES = ("lint", "format", "types", "tests", "build")
LIVE_COMMANDS = (
    ("doctor", "--json"),
    ("status", "--json"),
    ("bots", "--json"),
    ("connectors", "--json"),
    ("approvals", "--all", "--json"),
)
Run = Callable[..., subprocess.CompletedProcess[str]]


def planned_commands() -> dict[str, list[list[str]]]:
    prefix = ["uv", "run", "--no-sync"]
    return {
        "lint": [prefix + ["ruff", "check", "groken", "gbot", "tests"]],
        "format": [prefix + ["ruff", "format", "--check", "gbot", "tests/gbot_suite"]],
        "types": [prefix + ["basedpyright", "--level", "error"]],
        "tests": [prefix + ["pytest", "tests/", "-q", "-p", "no:cacheprovider"]],
        "live": [prefix + ["gbot", *command] for command in LIVE_COMMANDS],
    }


def select_stages(only: str | None, skip: str | None, live: bool) -> list[str]:
    available = (*STAGES, "live") if live else STAGES

    def names(value: str | None) -> set[str]:
        if value is None:
            return set()
        result = {name.strip() for name in value.split(",")}
        unknown = result - set(available)
        if unknown:
            raise ValueError(f"unknown stage(s): {', '.join(sorted(unknown))}")
        return result

    selected = names(only) if only is not None else set(available)
    selected -= names(skip)
    return [stage for stage in available if stage in selected]


def build(run: Run) -> bool:
    with tempfile.TemporaryDirectory(prefix="gbot-ci-") as temp:
        base = Path(temp)
        dist, venv, home = base / "dist", base / "venv", base / "home"
        commands = [["uv", "build", "--out-dir", str(dist)], ["uv", "venv", str(venv)]]
        for command in commands[:1]:
            if run(command, cwd=ROOT).returncode:
                return False
        wheels = list(dist.glob("*.whl"))
        if len(wheels) != 1:
            print("Build must produce exactly one wheel", flush=True)
            return False
        with zipfile.ZipFile(wheels[0]) as wheel:
            names = set(wheel.namelist())
        required = {
            "skill/SKILL.md",
            "docs/assets/groken-hero.png",
            "docs/capabilities-0.30.0.md",
        }
        forbidden = {"docs/painpoints-2026-08-19.md", "docs/capabilities-0.27.0.md"}

        def shipped(path: str) -> bool:
            return any(name.endswith(".data/data/" + path) for name in names)

        if any(not shipped(path) for path in required) or any(
            shipped(path) for path in forbidden
        ):
            print(
                "Wheel contents failed the required/forbidden asset check", flush=True
            )
            return False
        if run(commands[1], cwd=ROOT).returncode:
            return False
        bindir = venv / ("Scripts" if os.name == "nt" else "bin")
        python = bindir / ("python.exe" if os.name == "nt" else "python")
        gbot = bindir / ("gbot.exe" if os.name == "nt" else "gbot")
        groken = bindir / ("groken.exe" if os.name == "nt" else "groken")
        if run(
            ["uv", "pip", "install", "--python", str(python), str(wheels[0])], cwd=ROOT
        ).returncode:
            return False
        if run([str(gbot), "--help"], cwd=base).returncode:
            return False
        tui_help = run(
            [str(gbot), "tui", "--help"], cwd=base, capture_output=True, text=True
        )
        if tui_help.returncode or "--demo" not in (tui_help.stdout or ""):
            return False
        if WINDOWS:
            # The upstream groken CLI is POSIX-only (fcntl); gbot is the Windows entry point.
            return True
        (home / ".codex").mkdir(parents=True)
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
        if run([str(groken), "install", "codex-skills"], cwd=base, env=env).returncode:
            return False
        return (home / ".codex" / "skills" / "groken" / "SKILL.md").is_file()


def execute(
    selected: Sequence[str], live: bool, fail_fast: bool, run: Run = subprocess.run
) -> int:
    stages = (*STAGES, "live") if live else STAGES
    commands = planned_commands()
    results: list[tuple[str, str, float]] = []
    stopped = False
    for stage in stages:
        if stage not in selected or stopped:
            results.append((stage, "SKIP", 0.0))
            continue
        print(f"== {stage}", flush=True)
        start = time.monotonic()
        passed = True
        try:
            if stage == "build":
                passed = build(run)
            else:
                for command in commands[stage]:
                    code = run(command, cwd=ROOT).returncode
                    ok = code == 0 or (
                        stage == "live" and command[4] == "approvals" and code == 2
                    )
                    if stage == "live":
                        print(
                            f"{' '.join(command[4:])}: {'PASS' if ok else 'FAIL'} (exit {code})",
                            flush=True,
                        )
                    passed = passed and ok
        except (OSError, zipfile.BadZipFile) as exc:
            print(f"{stage}: {exc}", flush=True)
            passed = False
        results.append((stage, "PASS" if passed else "FAIL", time.monotonic() - start))
        if not passed and fail_fast:
            stopped = True
    print("\nStage    Result  Seconds")
    for stage, status, seconds in results:
        print(f"{stage:<8} {status:<7} {seconds:.2f}")
    return 1 if any(status == "FAIL" for _, status, _ in results) else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local CI gates")
    parser.add_argument("--only", help="comma-separated stages to run")
    parser.add_argument("--skip", help="comma-separated stages to skip")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument(
        "--live", action="store_true", help="enable read-only live account checks"
    )
    args = parser.parse_args(argv)
    try:
        selected = select_stages(args.only, args.skip, args.live)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        return execute(selected, args.live, args.fail_fast)
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
