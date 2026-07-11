"""Unit-test-wide fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_prefs(monkeypatch, tmp_path):
    """Redirect the user-prefs store to tmp_path and clear DOCFORGE_TEAM_IDS
    for EVERY unit test.

    Without this, any test that touches RemoteBackend.search (also outside
    test_remote_client.py, e.g. test_mcp_tool_timeout.py) would read — and the
    nudge bookkeeping would WRITE — the developer's real prefs.json, and a
    machine-configured DOCFORGE_TEAM_IDS would flip nudge behavior and break
    byte-exact request-body assertions.
    """
    import docforge.user_prefs as up

    monkeypatch.setattr(up, "prefs_path", lambda: tmp_path / "prefs.json")
    monkeypatch.delenv("DOCFORGE_TEAM_IDS", raising=False)
