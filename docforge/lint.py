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
        r"(ASP\.NET Core|Microsoft/vscode|ChakraCore).*(readme|inspiration)",
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
    """Return absolute paths of README.md (case-insensitive), CLAUDE.md, and all *.md under docs/."""
    raise NotImplementedError


def lint_repo(repo_root: Path) -> list[LintFinding]:
    """Walk the repo's doc surface; return all banned-content findings. Read-only."""
    raise NotImplementedError


def format_report(findings: list[LintFinding], scanned_files: list[Path], repo_root: Path) -> str:
    """Human-readable stdout string, grouped by file with summary line."""
    raise NotImplementedError


def has_failures(findings: list[LintFinding]) -> bool:
    return any(f.severity == "fail" for f in findings)
