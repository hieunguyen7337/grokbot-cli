import base64
import json

import pytest

from gbot import cli, context
from gbot.service import avatar_voice as av
from gbot.service import templates
from gbot.service.transport import FakeTransport


def setup_cli(monkeypatch, harness="box"):
    fake = FakeTransport(
        {
            **av.DEMO_COMMANDS,
            **templates.DEMO_COMMANDS,
            "listAgents": [
                {
                    "id": "bot",
                    "name": "Alpha",
                    "harness": harness,
                    "avatarShape": "blob",
                    "avatarColor": "blue",
                    "voiceId": "ara",
                }
            ],
        },
        {**av.DEMO_RPCS, **templates.DEMO_RPCS},
    )
    monkeypatch.setattr(context, "manager_factory", lambda: fake)

    class Backend:
        def unary(self, service, name, payload):
            return fake.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    return fake


@pytest.mark.parametrize(
    "argv,key",
    [
        (["avatar", "Alpha"], "has_image"),
        (["voice", "Alpha"], "voice_id"),
        (["voice", "--list"], "voices"),
        (["templates"], "listings"),
        (["templates", "show", "demo-template"], "expected_active_version"),
    ],
)
def test_read_json(monkeypatch, capsys, argv, key):
    setup_cli(monkeypatch)
    assert cli.main([*argv, "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert key in result


@pytest.mark.parametrize(
    "argv",
    [
        ["avatar", "Alpha", "--clear"],
        ["avatar", "Alpha", "--generate", "Star"],
        ["voice", "Alpha", "--voice", "ara"],
        ["templates", "use", "demo-template"],
    ],
)
def test_requires_yes(monkeypatch, capsys, argv):
    fake = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main([*argv, "--json"]) == 1
    assert "--yes" in json.loads(capsys.readouterr().err)["error"]["message"]
    assert not fake.calls


def test_mutation_json_and_routing(monkeypatch, capsys, tmp_path):
    fake = setup_cli(monkeypatch, "temporal")
    file = tmp_path / "avatar.png"
    file.write_bytes(av._PNG)
    for argv in (
        ["avatar", "Alpha", "--file", str(file)],
        ["avatar", "Alpha", "--clear"],
        ["avatar", "Alpha", "--generate", "Star"],
        ["voice", "Alpha", "--voice", "ara", "--speed", "1.4", "--language", "en"],
        ["templates", "use", "demo-template"],
    ):
        assert cli.main([*argv, "--yes", "--json"]) == 0
        assert isinstance(json.loads(capsys.readouterr().out), dict)
    calls = [call for call in fake.calls if call[1] == "SetGrokBotAgentVoice"]
    assert calls[0][2] == {
        "id": "bot",
        "voiceId": "ara",
        "voiceSpeed": 1.5,
        "voiceLanguage": "en",
    }


def test_save_no_overwrite(monkeypatch, capsys, tmp_path):
    fake = setup_cli(monkeypatch)
    fake.commands["getAgentAvatar"] = {
        "dataUrl": "data:image/png;base64," + base64.b64encode(av._PNG).decode()
    }
    dest = tmp_path / "saved.png"
    argv = ["avatar", "Alpha", "--save-to", str(dest), "--json"]
    assert cli.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["saved_to"] == str(dest)
    assert dest.read_bytes() == av._PNG
    assert cli.main(argv) == 1
    assert "already exists" in capsys.readouterr().err
    assert dest.read_bytes() == av._PNG


def test_generated_png_only(monkeypatch, capsys, tmp_path):
    fake = setup_cli(monkeypatch)
    fake.commands["generateAgentAvatarImage"] = {
        "imageBase64": base64.b64encode(b"jpeg").decode(),
        "mimeType": "image/jpeg",
    }
    assert cli.main(["avatar", "Alpha", "--generate", "Star", "--yes", "--json"]) == 1
    assert "not PNG" in capsys.readouterr().err
    assert not any(call[1] == "setAgentAvatarBytes" for call in fake.calls)
    fake.commands["generateAgentAvatarImage"] = av.DEMO_COMMANDS[
        "generateAgentAvatarImage"
    ]
    dest = tmp_path / "generated.png"
    assert (
        cli.main(
            [
                "avatar",
                "Alpha",
                "--generate",
                "Star",
                "--save-to",
                str(dest),
                "--yes",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["saved_to"] == str(dest)
    assert dest.read_bytes() == av._PNG


def test_terminal_confirmation_decline_and_accept(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "no")
    assert cli.main(["avatar", "Alpha", "--clear", "--json"]) == 1
    capsys.readouterr()
    assert not any(call[1] == "setAgentAvatarBytes" for call in fake.calls)
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    assert cli.main(["avatar", "Alpha", "--clear", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["has_image"] is False


def test_safe_template_text(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    fake.rpcs["GetGrokBotTemplateImportDetails"] = {
        "template": {
            "shareId": "share",
            "name": "Name\x1b[2J",
            "description": "Text\rhidden",
        },
        "expectedActiveVersion": 1,
        "creatorDisplayName": "Maker\u202e",
    }
    assert cli.main(["templates", "show", "share"]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\u202e" not in out and "\\u001b" in out
