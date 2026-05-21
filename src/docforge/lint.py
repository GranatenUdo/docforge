"""Lint a repo's README + CLAUDE.md + docs/ for Spec B banned-content patterns.

Pure logic — see `docforge.cli.lint_docs` for the user entry point. Banned-content
only in v1; structural/required-topics linting is deferred (see Spec C2 follow-ups).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from docforge.crawlers.git import crawl_repo


@dataclass(frozen=True)
class LintFinding:
    file: str
    line: int
    rule: str
    message: str


@dataclass(frozen=True)
class LintReport:
    scanned: list[str] = field(default_factory=list)
    findings: list[LintFinding] = field(default_factory=list)


BANNED_RULES: list[tuple[str, str, str]] = [
    (
        "todo-placeholder",
        r"TODO.*(Explain|Contribute)",
        "Placeholder TODO — delete and write real content",
    ),
    (
        "readme-inspiration-link",
        r"create-a-readme",
        "Microsoft README inspirational link — delete",
    ),
    (
        "readme-boilerplate",
        r"(github\.com/aspnet/Home|Microsoft/vscode|Microsoft/ChakraCore)",
        "Azure DevOps default boilerplate — delete whole block",
    ),
    (
        "lastpass-reference",
        r"LastPass",
        "Credential-source reference — move to Teams channel, not indexed docs",
    ),
]

_COMPILED_BANNED_RULES = [(name, re.compile(pat), msg) for name, pat, msg in BANNED_RULES]


def lint_repo(repo_root: Path) -> LintReport:
    """Walk the repo's doc surface and scan for banned-content patterns. Read-only."""
    files = crawl_repo(str(repo_root))
    scanned = [f.file_path for f in files]
    findings: list[LintFinding] = []
    for f in files:
        rel = f.file_path
        for lineno, line in enumerate(f.content.splitlines(), start=1):
            for rule_name, pattern, message in _COMPILED_BANNED_RULES:
                if pattern.search(line):
                    findings.append(LintFinding(rel, lineno, rule_name, message))
    return LintReport(scanned=scanned, findings=findings)


def format_report(report: LintReport, repo_root: Path) -> str:
    """Human-readable stdout, grouped by file with summary line."""
    lines: list[str] = []
    header = "FAIL" if report.findings else "PASS"
    lines.append(f"{repo_root} — {header}")
    lines.append(f"  {len(report.scanned)} files scanned")
    if not report.findings:
        lines.append("  No banned content")
        return "\n".join(lines)

    lines.append("")
    lines.append("  Banned content:")
    by_file: dict[str, list[LintFinding]] = {}
    for f in report.findings:
        by_file.setdefault(f.file, []).append(f)
    for file_rel, file_findings in by_file.items():
        for f in file_findings:
            location = f"{file_rel}:{f.line}"
            lines.append(f"    FAIL  {location:<30}  {f.rule:<22}  {f.message}")

    lines.append("")
    lines.append(f"  Summary: {len(report.findings)} banned-content hits")
    return "\n".join(lines)
