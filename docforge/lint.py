"""Lint a repo's README + CLAUDE.md + docs/ for Spec B banned-content patterns.

Pure logic — no CLI coupling. See `docforge.cli.lint_docs` for the user entry point.

Design note: REQUIRED_TOPICS (regex check for ## Architecture, ## Scope, etc.)
was considered and rejected in v1. The cloudstatus exemplar satisfies those
topics structurally (via numbered files in docs/) rather than via H2 headings
in README, so a regex-only check would false-positive on the exemplar. Spec B's
own stance: content principles resist mechanical enforcement. Deferred until
authoring patterns converge; see Spec C2 follow-up items.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class LintFinding:
    severity: Literal["fail"]
    file: str
    line: int | None
    rule: str
    message: str


# (rule_name, pattern, human_message)
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


def _discover_files(repo_root: Path) -> list[Path]:
    """Return paths of README.md (case-insensitive), CLAUDE.md, and all *.md under docs/."""
    found: list[Path] = []
    if repo_root.is_dir():
        for entry in sorted(repo_root.iterdir()):
            if entry.is_file() and entry.name.lower() == "readme.md":
                found.append(entry)
                break
        for entry in sorted(repo_root.iterdir()):
            if entry.is_file() and entry.name == "CLAUDE.md":
                found.append(entry)
                break
    docs_dir = repo_root / "docs"
    if docs_dir.is_dir():
        for md in sorted(docs_dir.rglob("*.md")):
            if md.is_file():
                found.append(md)
    return found


def lint_repo(repo_root: Path) -> list[LintFinding]:
    """Walk the repo's doc surface; return all banned-content findings. Read-only."""
    findings: list[LintFinding] = []
    for file_path in _discover_files(repo_root):
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(file_path.relative_to(repo_root)).replace("\\", "/")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for rule_name, pattern, message in _COMPILED_BANNED_RULES:
                if pattern.search(line):
                    findings.append(
                        LintFinding(
                            severity="fail",
                            file=rel,
                            line=lineno,
                            rule=rule_name,
                            message=message,
                        )
                    )
    return findings


def format_report(findings: list[LintFinding], scanned_files: list[Path], repo_root: Path) -> str:
    """Human-readable stdout string, grouped by file with summary line."""
    lines: list[str] = []
    header = "FAIL" if findings else "PASS"
    lines.append(f"{repo_root} — {header}")
    lines.append(f"  {len(scanned_files)} files scanned")
    if not findings:
        lines.append("  No banned content")
        return "\n".join(lines)

    lines.append("")
    lines.append("  Banned content:")
    by_file: dict[str, list[LintFinding]] = {}
    for f in findings:
        by_file.setdefault(f.file, []).append(f)
    for file_rel, file_findings in by_file.items():
        for f in file_findings:
            location = f"{file_rel}:{f.line}" if f.line is not None else file_rel
            lines.append(f"    FAIL  {location:<30}  {f.rule:<22}  {f.message}")

    lines.append("")
    lines.append(f"  Summary: {len(findings)} banned-content hits")
    return "\n".join(lines)


def has_failures(findings: list[LintFinding]) -> bool:
    return any(f.severity == "fail" for f in findings)
