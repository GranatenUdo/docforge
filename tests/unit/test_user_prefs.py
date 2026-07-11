"""Tests for the per-user prefs store used by `serve --remote-api`."""

from __future__ import annotations

import json

# --- prefs_path -------------------------------------------------------------


def test_prefs_path_windows_prefers_localappdata(monkeypatch, tmp_path):
    monkeypatch.setattr("docforge.user_prefs._os_name", lambda: "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    from docforge.user_prefs import prefs_path

    p = prefs_path()
    assert str(tmp_path / "local") in str(p)
    assert p.name == "prefs.json"
    assert p.parent.name == "docforge"


def test_prefs_path_windows_falls_back_to_appdata(monkeypatch, tmp_path):
    monkeypatch.setattr("docforge.user_prefs._os_name", lambda: "nt")
    monkeypatch.setenv("LOCALAPPDATA", "")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    from docforge.user_prefs import prefs_path

    assert str(tmp_path / "roaming") in str(prefs_path())


def test_prefs_path_windows_falls_back_to_home(monkeypatch):
    monkeypatch.setattr("docforge.user_prefs._os_name", lambda: "nt")
    monkeypatch.setenv("LOCALAPPDATA", "")
    monkeypatch.setenv("APPDATA", "")
    from docforge.user_prefs import prefs_path

    p = prefs_path()
    assert ".docforge" in str(p)
    assert p.name == "prefs.json"


def test_prefs_path_posix_uses_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setattr("docforge.user_prefs._os_name", lambda: "posix")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    from docforge.user_prefs import prefs_path

    p = prefs_path()
    assert str(tmp_path / "xdg") in str(p)
    assert p.parent.name == "docforge"


def test_prefs_path_posix_defaults_to_dot_config(monkeypatch):
    monkeypatch.setattr("docforge.user_prefs._os_name", lambda: "posix")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    from docforge.user_prefs import prefs_path

    assert ".config" in str(prefs_path())


# --- load_prefs -------------------------------------------------------------


def test_load_prefs_missing_file_returns_defaults(tmp_path):
    from docforge.user_prefs import UserPrefs, load_prefs

    prefs = load_prefs(tmp_path / "nope" / "prefs.json")
    assert prefs == UserPrefs()
    assert prefs.team == ""
    assert prefs.declined is False
    assert prefs.nudge_count == 0


def test_load_prefs_corrupt_json_returns_defaults(tmp_path):
    p = tmp_path / "prefs.json"
    p.write_text("{not json", encoding="utf-8")
    from docforge.user_prefs import UserPrefs, load_prefs

    assert load_prefs(p) == UserPrefs()


def test_load_prefs_non_dict_json_returns_defaults(tmp_path):
    p = tmp_path / "prefs.json"
    p.write_text('["a", "b"]', encoding="utf-8")
    from docforge.user_prefs import UserPrefs, load_prefs

    assert load_prefs(p) == UserPrefs()


def test_load_prefs_wrong_types_returns_defaults(tmp_path):
    p = tmp_path / "prefs.json"
    p.write_text('{"team": 5, "declined": "maybe"}', encoding="utf-8")
    from docforge.user_prefs import UserPrefs, load_prefs

    assert load_prefs(p) == UserPrefs()


# --- save_prefs -------------------------------------------------------------


def test_save_load_roundtrip(tmp_path):
    from docforge.user_prefs import UserPrefs, load_prefs, save_prefs

    p = tmp_path / "sub" / "prefs.json"  # parent dir must be created
    prefs = UserPrefs(team="ccl", declined=False, nudge_count=2)
    assert save_prefs(prefs, p) is True

    loaded = load_prefs(p)
    assert loaded.team == "ccl"
    assert loaded.nudge_count == 2
    assert loaded.updated_at != ""  # stamped on save


def test_save_prefs_decline_roundtrip(tmp_path):
    from docforge.user_prefs import UserPrefs, load_prefs, save_prefs

    p = tmp_path / "prefs.json"
    save_prefs(UserPrefs(declined=True), p)
    assert load_prefs(p).declined is True


def test_save_prefs_leaves_no_tmp_files(tmp_path):
    from docforge.user_prefs import UserPrefs, save_prefs

    p = tmp_path / "prefs.json"
    assert save_prefs(UserPrefs(team="cis"), p) is True
    leftovers = [f.name for f in tmp_path.iterdir() if f.name != "prefs.json"]
    assert leftovers == []
    # file is valid JSON with the schema fields
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["team"] == "cis"
    assert data["version"] == 1


def test_save_prefs_failure_returns_false_never_raises(tmp_path):
    from docforge.user_prefs import UserPrefs, save_prefs

    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file", encoding="utf-8")
    # parent "directory" is actually a file -> mkdir fails with OSError
    p = blocker / "prefs.json"
    assert save_prefs(UserPrefs(team="ccl"), p) is False


# --- valid_team_ids ---------------------------------------------------------


def test_valid_team_ids_parses_and_normalizes(monkeypatch):
    monkeypatch.setenv("DOCFORGE_TEAM_IDS", " ccl, CIS ,,workflow ")
    from docforge.user_prefs import valid_team_ids

    assert valid_team_ids() == ["ccl", "cis", "workflow"]


def test_valid_team_ids_empty_when_unset(monkeypatch):
    monkeypatch.delenv("DOCFORGE_TEAM_IDS", raising=False)
    from docforge.user_prefs import valid_team_ids

    assert valid_team_ids() == []


def test_os_environ_not_leaked_between_calls(monkeypatch):
    """valid_team_ids must read the env at call time (kill-switch semantics:
    removing DOCFORGE_TEAM_IDS from the deployment disables the nudge)."""
    monkeypatch.setenv("DOCFORGE_TEAM_IDS", "ccl")
    from docforge.user_prefs import valid_team_ids

    assert valid_team_ids() == ["ccl"]
    monkeypatch.delenv("DOCFORGE_TEAM_IDS")
    assert valid_team_ids() == []


def test_load_prefs_default_path_never_raises(monkeypatch, tmp_path):
    """load_prefs() with no explicit path must survive a broken prefs_path."""
    import docforge.user_prefs as up

    monkeypatch.setattr(up, "prefs_path", lambda: tmp_path / "x" / "prefs.json")
    assert up.load_prefs() == up.UserPrefs()
