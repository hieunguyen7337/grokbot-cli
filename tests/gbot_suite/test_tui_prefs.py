import json

from gbot.tui.prefs import (
    Prefs,
    first_run,
    load,
    mark_seen,
    move_in_order,
    path,
    save,
    set_group_by,
    toggle_collapsed,
    toggle_pin,
)


def test_roundtrip_and_helpers(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    assert path() == tmp_path / "tui.json"
    prefs = toggle_pin(Prefs(), "a")
    prefs = toggle_pin(prefs, "b")
    prefs = move_in_order(prefs, "b", -1, ["a", "b"])
    prefs = toggle_collapsed(prefs, "idle")
    prefs = set_group_by(prefs, "team")
    prefs = first_run(prefs, {"a": 5})
    prefs = mark_seen(prefs, "a", 3)
    assert prefs.last_seen == {"a": 5} and prefs.order == ("b", "a")
    assert first_run(prefs, {"b": 8}) == prefs
    save(path(), prefs)
    assert load(path()) == prefs
    assert json.loads(path().read_text(encoding="utf-8"))["last_seen"] == {"a": 5}
    assert toggle_pin(prefs, "a").pins == ("b",)
    assert not toggle_collapsed(prefs, "idle").collapsed


def test_bad_files(tmp_path):
    file = tmp_path / "prefs.json"
    assert load(file) == Prefs()
    file.write_text("{", encoding="utf-8")
    assert load(file) == Prefs()
    file.write_text(
        json.dumps(
            {
                "pins": [1],
                "order": "x",
                "collapsed": [False],
                "group_by": [],
                "last_seen": {"a": True},
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert load(file) == Prefs()
