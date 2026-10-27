import base64
import json
import struct
import sys
from pathlib import Path

import pytest

from groken import app_archive, auth, checksum, client, config, private_files, winplat

windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows platform APIs")


@windows
@pytest.mark.parametrize("data", [b"", b"test-secret", bytes(range(256))])
def test_dpapi(data: bytes) -> None:
    blob = winplat.protect(data)
    assert blob != data
    assert winplat.unprotect(blob) == data


@windows
def test_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "tokens.json"
    monkeypatch.setattr(auth, "TOKEN_FILE", path)
    tokens: dict[str, object] = {
        "accessToken": "synthetic-access-secret",
        "refreshToken": "synthetic-refresh-secret",
    }
    auth.save_tokens(tokens)
    content = path.read_text()
    assert all(str(value) not in content for value in tokens.values())
    assert json.loads(content)["format"] == "dpapi-v1"
    assert auth.load_tokens() == tokens
    assert not path.with_suffix(".json.tmp").exists()
    path.write_text(json.dumps(tokens))
    assert auth.load_tokens() == tokens
    path.write_text(
        json.dumps(
            {"format": "dpapi-v1", "blob": base64.b64encode(b"invalid").decode()}
        )
    )
    assert auth.load_tokens() is None
    assert auth.clear_tokens()
    assert not path.exists()
    assert not auth.clear_tokens()


def test_data_dir_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    assert winplat.data_dir() == tmp_path


@windows
def test_windows_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GBOT_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert winplat.data_dir() == tmp_path / "grokbot-cli"
    monkeypatch.delenv("LOCALAPPDATA")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert winplat.data_dir() == tmp_path / "AppData" / "Local" / "grokbot-cli"


def test_install_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GBOT_APP_DIR", str(tmp_path / "override"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "programs"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert winplat.app_install_dirs() == [
        tmp_path / "override",
        tmp_path / "programs" / "Grok Bot",
        tmp_path / "local" / "Programs" / "Grok Bot",
    ]
    for variable in ("GBOT_APP_DIR", "ProgramFiles", "LOCALAPPDATA"):
        monkeypatch.delenv(variable)
    assert winplat.app_install_dirs() == []


@windows
def test_exe_version(tmp_path: Path) -> None:
    version = winplat.exe_version(Path(sys.executable))
    assert version is not None
    assert len(version.split(".")) == 3
    assert all(part.isdigit() for part in version.split("."))
    assert winplat.exe_version(tmp_path / "missing.exe") is None


def test_asar(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    resources.mkdir()
    archive = resources / "app.asar"
    payload = json.dumps(
        {
            "files": {
                "packed": {"size": 6, "offset": "0"},
                "unpacked": {"size": 8, "unpacked": True},
            }
        }
    ).encode()
    padding = (-len(payload)) % 4
    string_size = len(payload) + padding + 4
    archive.write_bytes(
        struct.pack("<4I", 4, string_size + 4, string_size, len(payload))
        + payload
        + b"\0" * padding
        + b"packed"
    )
    unpacked = resources / "app.asar.unpacked"
    unpacked.mkdir()
    (unpacked / "unpacked").write_bytes(b"unpacked")
    assert app_archive.resolve_asar(tmp_path) == archive
    assert app_archive.resolve_asar(resources) == archive
    header = app_archive.read_asar_header(archive)
    assert app_archive.read_asar_entry(archive, header, "packed") == b"packed"
    assert app_archive.read_asar_entry(archive, header, "unpacked") == b"unpacked"


@windows
def test_client_version_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    directories = [tmp_path / "missing", tmp_path / "first", tmp_path / "second"]
    for directory in directories[1:]:
        directory.mkdir()
        (directory / "Grok Bot.exe").touch()
    monkeypatch.setattr(winplat, "app_install_dirs", lambda: directories)
    seen: list[Path] = []

    def version(path: Path) -> str:
        seen.append(path)
        return "0.72.1"

    monkeypatch.setattr(winplat, "exe_version", version)
    config.save_config({"client_version": "cached", "other": True})
    monkeypatch.setenv("SAND_CLIENT_VERSION", "override")
    assert client.detect_client_version() == "override"
    assert not seen
    monkeypatch.delenv("SAND_CLIENT_VERSION")
    assert client.detect_client_version() == "0.72.1"
    assert seen == [directories[1] / "Grok Bot.exe"]
    assert config.load_config() == {"client_version": "0.72.1", "other": True}
    monkeypatch.setattr(winplat, "exe_version", lambda _path: None)
    assert client.detect_client_version() == "0.72.1"
    config.save_config({})
    assert client.detect_client_version() == "0.20.0"


@windows
def test_bundle_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Path] = []

    def version(path: Path) -> str:
        seen.append(path)
        return "0.72.1"

    monkeypatch.setattr(winplat, "exe_version", version)
    assert app_archive.read_bundle_version(tmp_path) == "0.72.1"
    assert app_archive.read_bundle_version(tmp_path / "resources") == "0.72.1"
    assert seen == [tmp_path / "Grok Bot.exe"] * 2


@windows
def test_machine_id_no_ioreg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("ioreg must not run on Windows")

    monkeypatch.setattr(checksum.subprocess, "run", forbidden)
    path = tmp_path / "machine_id"
    monkeypatch.setattr(checksum, "_MACHINE_ID_FILE", path)
    first = checksum.get_machine_id()
    assert checksum.get_machine_id() == first == path.read_text()


@windows
@pytest.mark.parametrize("failures", [2, 4])
def test_atomic_replace_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failures: int
) -> None:
    path = tmp_path / "private.txt"
    path.write_text("old")
    real_replace = private_files.os.replace
    attempts: list[int] = []
    delays: list[float] = []

    def replace(source: Path, destination: Path) -> None:
        attempts.append(1)
        assert path.read_text() == "old"
        if len(attempts) <= failures:
            raise PermissionError("synthetic sharing violation")
        real_replace(source, destination)

    monkeypatch.setattr(private_files.os, "replace", replace)
    monkeypatch.setattr(private_files.time, "sleep", delays.append)
    if failures == 4:
        with pytest.raises(PermissionError):
            private_files.write_private_text(path, "new")
        assert path.read_text() == "old"
    else:
        private_files.write_private_text(path, "new")
        assert path.read_text() == "new"
        assert not path.with_suffix(".txt.tmp").exists()
    assert len(attempts) == min(failures + 1, 4)
    assert len(delays) == min(failures, 3)
