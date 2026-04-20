"""Tests for docforge.lint."""

from __future__ import annotations

from pathlib import Path

import pytest

from docforge.lint import (
    BANNED_RULES,
    LintFinding,
    _discover_files,
    format_report,
    has_failures,
    lint_repo,
)


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


class TestDiscoverFiles:
    def test_finds_readme_claude_and_docs(self, tmp_path: Path):
        _write(tmp_path / "README.md", "# Title\n")
        _write(tmp_path / "CLAUDE.md", "# Title\n")
        _write(tmp_path / "docs" / "arch.md", "# Arch\n")
        _write(tmp_path / "docs" / "deep" / "nested.md", "# Deep\n")

        found = {p.name for p in _discover_files(tmp_path)}
        assert found == {"README.md", "CLAUDE.md", "arch.md", "nested.md"}

    def test_readme_case_insensitive(self, tmp_path: Path):
        _write(tmp_path / "readme.md", "# Title\n")
        found = {p.name for p in _discover_files(tmp_path)}
        assert found == {"readme.md"}

    def test_empty_repo_finds_nothing(self, tmp_path: Path):
        assert _discover_files(tmp_path) == []

    def test_ignores_non_markdown(self, tmp_path: Path):
        _write(tmp_path / "README.md", "# Title\n")
        _write(tmp_path / "docs" / "notes.txt", "not markdown")
        found = {p.name for p in _discover_files(tmp_path)}
        assert found == {"README.md"}
