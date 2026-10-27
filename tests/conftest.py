# Windows collection is an audited allowlist; POSIX collection stays unchanged.
# To add a module, run .venv/Scripts/python -m pytest -q -p no:cacheprovider
# tests/test_<module>.py on Windows, then add its filename after it passes.
# tests/gbot_suite/ is always collected; required modules stay listed while being fixed.
import sys
from pathlib import Path

import pytest

WINDOWS_TEST_MODULES = {
    "test_auth.py",
    "test_bot_provisioning_payloads.py",
    "test_capabilities.py",
    "test_chaos.py",
    "test_cli_plugin_tools.py",
    "test_client.py",
    "test_config.py",
    "test_controller_app.py",
    "test_controller_store.py",
    "test_doctor.py",
    "test_env_capture_gateway.py",
    "test_env_native_capture.py",
    "test_env_native_failures.py",
    "test_errors.py",
    "test_events_ask.py",
    "test_exec_service.py",
    "test_gateway.py",
    "test_gateway_command_audit.py",
    "test_guardrails.py",
    "test_inspect_app.py",
    "test_inspect_contracts.py",
    "test_inspector_version_drift.py",
    "test_installers.py",
    "test_native_client_wait.py",
    "test_native_controller.py",
    "test_native_mcp_direct.py",
    "test_native_poller.py",
    "test_native_wait_http.py",
    "test_parsing.py",
    "test_poller.py",
    "test_provisioning.py",
    "test_status.py",
    "test_swarm_worker.py",
    "test_team_alerts.py",
    "test_vnc.py",
    "test_vnc_proxy.py",
    "test_vnc_ready.py",
    "test_windows_platform.py",
    "test_wire.py",
}

_WINDOWS_FAILURE_REASONS = {
    "tests/test_status.py::test_status_continues_after_corrupt_local_routine": (
        "Windows Path.home() uses USERPROFILE, so the HOME-based routine fixture "
        "is not found and the corrupt routine count is missing."
    ),
    "tests/test_status.py::test_status_never_renders_malicious_corrupt_routine_name": (
        "Windows rejects the malicious routine directory name with WinError 123 "
        "before status rendering can be tested."
    ),
    "tests/test_errors.py::test_mcp_ask_translates_connect_error": (
        "Importing mcp_server reaches env_restore_lock, which imports the "
        "unavailable POSIX fcntl module on Windows."
    ),
    "tests/test_errors.py::test_mcp_does_not_swallow_unexpected_errors": (
        "Importing mcp_server reaches env_restore_lock, which imports the "
        "unavailable POSIX fcntl module on Windows."
    ),
}
WINDOWS_KNOWN_FAILURES = set(_WINDOWS_FAILURE_REASONS)


def pytest_ignore_collect(collection_path: Path) -> bool | None:
    if sys.platform != "win32":
        return None
    relative = collection_path.relative_to(Path(__file__).resolve().parent)
    if relative.parts[0] == "gbot_suite":
        return None
    if collection_path.suffix == ".py":
        return relative.as_posix() not in WINDOWS_TEST_MODULES
    return None


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if sys.platform != "win32":
        return
    for item in items:
        if item.nodeid in WINDOWS_KNOWN_FAILURES:
            item.add_marker(
                pytest.mark.xfail(
                    strict=False, reason=_WINDOWS_FAILURE_REASONS[item.nodeid]
                )
            )
