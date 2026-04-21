"""Tests for docforge.lint."""

from __future__ import annotations

from pathlib import Path

from docforge.lint import (
    LintFinding,
    LintReport,
    format_report,
    lint_repo,
)


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


class TestLintRepo:
    def test_clean_repo_has_no_findings(self, tmp_path: Path):
        _write(tmp_path / "README.md", "# Clean Repo\n\nClean README with real content.\n")
        _write(tmp_path / "CLAUDE.md", "# Working Notes\n\nNormal content.\n")
        _write(tmp_path / "docs" / "arch.md", "# Architecture\n\nReal content.\n")
        report = lint_repo(tmp_path)
        assert report.findings == []
        assert len(report.scanned) == 3

    def test_banned_todo_placeholder(self, tmp_path: Path):
        _write(tmp_path / "README.md", "# Repo\n\nTODO: Explain what this does\n")
        report = lint_repo(tmp_path)
        assert len(report.findings) == 1
        assert report.findings[0].rule == "todo-placeholder"
        assert report.findings[0].line == 3
        assert report.findings[0].file.endswith("README.md")

    def test_banned_create_readme_link(self, tmp_path: Path):
        _write(
            tmp_path / "README.md",
            "# Repo\n\nInspired by https://docs.github.com/create-a-readme/\n",
        )
        findings = lint_repo(tmp_path).findings
        assert len(findings) == 1
        assert findings[0].rule == "readme-inspiration-link"

    def test_banned_lastpass_reference(self, tmp_path: Path):
        _write(tmp_path / "README.md", "# Repo\n\nSee LastPass folder 'Cloud-Ops'.\n")
        findings = lint_repo(tmp_path).findings
        assert len(findings) == 1
        assert findings[0].rule == "lastpass-reference"

    def test_banned_ado_boilerplate(self, tmp_path: Path):
        _write(
            tmp_path / "README.md",
            "# Repo\n\n"
            "- [Visual Studio Code](https://github.com/Microsoft/vscode)\n"
            "- [Chakra Core](https://github.com/Microsoft/ChakraCore)\n",
        )
        findings = lint_repo(tmp_path).findings
        assert len(findings) == 2
        assert all(f.rule == "readme-boilerplate" for f in findings)

    def test_multiple_banned_hits_reported_separately(self, tmp_path: Path):
        _write(
            tmp_path / "README.md",
            "# Repo\n\nTODO: Explain the thing\nAlso see create-a-readme.\nAnd LastPass.\n",
        )
        findings = lint_repo(tmp_path).findings
        assert len(findings) == 3
        rules = {f.rule for f in findings}
        assert rules == {"todo-placeholder", "readme-inspiration-link", "lastpass-reference"}

    def test_docs_subfolder_scanned_recursively(self, tmp_path: Path):
        _write(tmp_path / "README.md", "# Clean\n")
        _write(tmp_path / "docs" / "deep" / "nested.md", "# Nested\n\nSee LastPass.\n")
        findings = lint_repo(tmp_path).findings
        assert len(findings) == 1
        assert findings[0].rule == "lastpass-reference"
        assert findings[0].file.endswith("nested.md")

    def test_empty_repo_has_no_findings(self, tmp_path: Path):
        report = lint_repo(tmp_path)
        assert report.findings == []
        assert report.scanned == []

    def test_line_numbers_are_one_based(self, tmp_path: Path):
        _write(tmp_path / "README.md", "# Title\n\nTODO: Explain this\n")
        findings = lint_repo(tmp_path).findings
        assert findings[0].line == 3


class TestFormatReport:
    def test_clean_report_says_pass(self, tmp_path: Path):
        report = LintReport(scanned=["README.md"], findings=[])
        out = format_report(report, tmp_path)
        assert "PASS" in out
        assert "No banned content" in out
        assert "1 files scanned" in out

    def test_failing_report_lists_findings_grouped_by_file(self, tmp_path: Path):
        findings = [
            LintFinding("README.md", 3, "todo-placeholder", "Placeholder TODO"),
            LintFinding("README.md", 8, "lastpass-reference", "Credential ref"),
            LintFinding("docs/x.md", 2, "lastpass-reference", "Credential ref"),
        ]
        report = LintReport(scanned=["README.md", "docs/x.md"], findings=findings)
        out = format_report(report, tmp_path)
        assert "FAIL" in out
        assert "README.md:3" in out
        assert "README.md:8" in out
        assert "docs/x.md:2" in out
        assert "3 banned-content hits" in out
