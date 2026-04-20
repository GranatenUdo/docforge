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


class TestLintRepo:
    def test_clean_repo_has_no_findings(self, tmp_path: Path):
        _write(tmp_path / "README.md", "# Clean Repo\n\nThis is a clean README with real content.\n")
        _write(tmp_path / "CLAUDE.md", "# Working Notes\n\nNormal content.\n")
        _write(tmp_path / "docs" / "arch.md", "# Architecture\n\nReal content.\n")
        assert lint_repo(tmp_path) == []

    def test_banned_todo_placeholder(self, tmp_path: Path):
        _write(tmp_path / "README.md", "# Repo\n\nTODO: Explain what this does\n")
        findings = lint_repo(tmp_path)
        assert len(findings) == 1
        assert findings[0].rule == "todo-placeholder"
        assert findings[0].line == 3
        assert findings[0].file.endswith("README.md")

    def test_banned_create_readme_link(self, tmp_path: Path):
        _write(
            tmp_path / "README.md",
            "# Repo\n\nInspired by https://docs.github.com/create-a-readme/\n",
        )
        findings = lint_repo(tmp_path)
        assert len(findings) == 1
        assert findings[0].rule == "readme-inspiration-link"

    def test_banned_lastpass_reference(self, tmp_path: Path):
        _write(tmp_path / "README.md", "# Repo\n\nSee LastPass folder 'Cloud-Ops'.\n")
        findings = lint_repo(tmp_path)
        assert len(findings) == 1
        assert findings[0].rule == "lastpass-reference"

    def test_banned_ado_boilerplate(self, tmp_path: Path):
        # Matches the real ADO default README block (links to Microsoft/vscode
        # and Microsoft/ChakraCore as "inspiration").
        _write(
            tmp_path / "README.md",
            "# Repo\n\n"
            "- [Visual Studio Code](https://github.com/Microsoft/vscode)\n"
            "- [Chakra Core](https://github.com/Microsoft/ChakraCore)\n",
        )
        findings = lint_repo(tmp_path)
        assert len(findings) == 2
        assert all(f.rule == "readme-boilerplate" for f in findings)

    def test_multiple_banned_hits_reported_separately(self, tmp_path: Path):
        _write(
            tmp_path / "README.md",
            "# Repo\n\nTODO: Explain the thing\nAlso see create-a-readme.\nAnd LastPass.\n",
        )
        findings = lint_repo(tmp_path)
        assert len(findings) == 3
        rules = {f.rule for f in findings}
        assert rules == {"todo-placeholder", "readme-inspiration-link", "lastpass-reference"}

    def test_docs_subfolder_scanned_recursively(self, tmp_path: Path):
        _write(tmp_path / "README.md", "# Clean\n")
        _write(tmp_path / "docs" / "deep" / "nested.md", "# Nested\n\nSee LastPass.\n")
        findings = lint_repo(tmp_path)
        assert len(findings) == 1
        assert findings[0].rule == "lastpass-reference"
        assert findings[0].file.endswith("nested.md")

    def test_empty_repo_has_no_findings(self, tmp_path: Path):
        # Documented v1 limitation: linter has nothing to fail on.
        assert lint_repo(tmp_path) == []

    def test_line_numbers_are_one_based(self, tmp_path: Path):
        # Line 1 has no match; line 2 is blank; line 3 has the hit.
        _write(tmp_path / "README.md", "# Title\n\nTODO: Explain this\n")
        findings = lint_repo(tmp_path)
        assert findings[0].line == 3


class TestHasFailures:
    def test_empty_list_no_failures(self):
        assert has_failures([]) is False

    def test_any_failure_returns_true(self):
        f = LintFinding(severity="fail", file="x.md", line=1, rule="r", message="m")
        assert has_failures([f]) is True


class TestFormatReport:
    def test_clean_report_says_pass(self, tmp_path: Path):
        _write(tmp_path / "README.md", "# Clean\n")
        scanned = [tmp_path / "README.md"]
        out = format_report([], scanned, tmp_path)
        assert "PASS" in out
        assert "No banned content" in out
        assert "1 files scanned" in out

    def test_failing_report_lists_findings_grouped_by_file(self, tmp_path: Path):
        findings = [
            LintFinding("fail", "README.md", 3, "todo-placeholder", "Placeholder TODO"),
            LintFinding("fail", "README.md", 8, "lastpass-reference", "Credential ref"),
            LintFinding("fail", "docs/x.md", 2, "lastpass-reference", "Credential ref"),
        ]
        scanned = [tmp_path / "README.md", tmp_path / "docs" / "x.md"]
        out = format_report(findings, scanned, tmp_path)
        assert "FAIL" in out
        assert "README.md:3" in out
        assert "README.md:8" in out
        assert "docs/x.md:2" in out
        assert "3 banned-content hits" in out
