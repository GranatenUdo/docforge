"""Tests that `python -m docforge` dispatches to the Typer app."""

from __future__ import annotations

import subprocess
import sys


def test_module_entrypoint_help_exits_zero():
    result = subprocess.run(
        [sys.executable, "-m", "docforge", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "Forge searchable context" in result.stdout or "Usage" in result.stdout
