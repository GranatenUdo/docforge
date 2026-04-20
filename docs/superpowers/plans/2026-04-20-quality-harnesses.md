# Quality Harnesses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship two quality-measurement tools for docforge: (1) a `docforge lint-docs` CLI subcommand that flags Spec B banned-content patterns in a target repo, and (2) a `docforge/scripts/eval_search.py` runner that measures retrieval quality (recall@1, recall@5, MRR) against the live Azure deployment using a DocuWare-authored ground-truth set.

**Architecture:** `docforge/lint.py` is pure, importable Python — file discovery + regex rules + formatting. The CLI wraps it with `typer`. The eval runner is a standalone script at `docforge/scripts/eval_search.py` (not a CLI subcommand — too many flags) using `httpx` + `pyyaml`. DocuWare-specific ground truth + first-run baseline live in the `knowledge-hub` repo, keeping generic engine (docforge) separate from company data (knowledge-hub). Per the post-critical-review revision of the spec: linter v1 enforces **banned-content only** (no required-topics check); eval harness v1 **sets a baseline** instead of gating on an arbitrary recall threshold.

**Tech Stack:** Python 3.12+, Typer (CLI), httpx (HTTP), pyyaml (ground-truth loading), pytest + pytest-asyncio (tests), ruff (format + lint). Live Azure endpoint: `https://docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io`.

**Spec:** `docs/superpowers/specs/2026-04-20-quality-harnesses-design.md`

---

## File Structure

**docforge repo (generic engine):**
- `docforge/lint.py` — NEW. Pure linter logic. `LintFinding` dataclass, `BANNED_RULES` table, `lint_repo()`, `format_report()`, `has_failures()`. ~100 LoC.
- `docforge/cli.py` — MODIFY. Add `lint-docs` subcommand after line 125 (after `status` command). +~15 LoC.
- `docforge/scripts/__init__.py` — NEW. Empty package marker.
- `docforge/scripts/eval_search.py` — NEW. Standalone runner. Pure `score_query` + `summarize`, async `run_queries`, `format_report`, `main` (argparse). ~140 LoC.
- `docforge/scripts/README.md` — NEW. Operator doc for running the eval harness. ~40 LoC.
- `tests/unit/test_lint.py` — NEW. `tmp_path`-based fixtures. ~100 LoC.
- `tests/unit/test_eval_search.py` — NEW. Pure-function tests for `score_query` + `summarize`. ~80 LoC.
- `tests/unit/test_cli.py` — MODIFY. Extend with `TestLintDocsCommand` class. +~30 LoC.

**knowledge-hub repo (DocuWare consumer):**
- `rag/eval/ground_truth.yml` — NEW. 20-30 user-authored `(q, expected_title_contains)` pairs.
- `rag/eval/baseline.md` — NEW. Baseline metrics recorded after first live-Azure run.
- `rag/eval/README.md` — NEW. Operator doc explaining how to run the harness, record a baseline, re-baseline when `sources.yml` changes.

**Total:** 7 new files + 2 modifications in docforge; 3 new files in knowledge-hub.

---

## Phase 1 — Linter

### Task 1: Scaffold `docforge/lint.py` with data types + rules table

**Files:**
- Create: `E:/docforge/docforge/lint.py`

- [ ] **Step 1: Create the module with `LintFinding` dataclass and `BANNED_RULES` table**

Write `docforge/lint.py`:

```python
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
```

- [ ] **Step 2: Verify the module imports**

Run:
```bash
cd /e/docforge && python -c "from docforge.lint import LintFinding, BANNED_RULES, has_failures; print(len(BANNED_RULES))"
```
Expected: prints `4`

- [ ] **Step 3: Commit**

```bash
cd /e/docforge && git add docforge/lint.py && git -c commit.gpgsign=false commit -m "Scaffold docforge.lint module with LintFinding + BANNED_RULES"
```

---

### Task 2: Write failing test for `_discover_files`

**Files:**
- Create: `E:/docforge/tests/unit/test_lint.py`

- [ ] **Step 1: Write the first failing test**

Create `tests/unit/test_lint.py`:

```python
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:
```bash
cd /e/docforge && pytest tests/unit/test_lint.py::TestDiscoverFiles -v
```
Expected: All 4 tests fail with `NotImplementedError`.

- [ ] **Step 3: Implement `_discover_files`**

Replace `_discover_files` in `docforge/lint.py`:

```python
def _discover_files(repo_root: Path) -> list[Path]:
    """Return absolute paths of README.md (case-insensitive), CLAUDE.md, and all *.md under docs/."""
    found: list[Path] = []
    for name in ("README.md", "readme.md", "Readme.md"):
        p = repo_root / name
        if p.is_file():
            found.append(p)
            break  # accept only one README variant
    claude = repo_root / "CLAUDE.md"
    if claude.is_file():
        found.append(claude)
    docs_dir = repo_root / "docs"
    if docs_dir.is_dir():
        for md in sorted(docs_dir.rglob("*.md")):
            if md.is_file():
                found.append(md)
    return found
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /e/docforge && pytest tests/unit/test_lint.py::TestDiscoverFiles -v
```
Expected: All 4 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /e/docforge && git add docforge/lint.py tests/unit/test_lint.py && git -c commit.gpgsign=false commit -m "Implement lint._discover_files with tests"
```

---

### Task 3: Implement `lint_repo` with banned-content scanning

**Files:**
- Modify: `E:/docforge/docforge/lint.py`
- Modify: `E:/docforge/tests/unit/test_lint.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_lint.py`:

```python
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
        _write(
            tmp_path / "README.md",
            "# Repo\n\nAlternatively, for great examples of readme inspiration check "
            "ASP.NET Core, Microsoft/vscode, or ChakraCore.\n",
        )
        findings = lint_repo(tmp_path)
        assert len(findings) == 1
        assert findings[0].rule == "readme-boilerplate"

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
```

- [ ] **Step 2: Run tests and verify they fail**

Run:
```bash
cd /e/docforge && pytest tests/unit/test_lint.py::TestLintRepo tests/unit/test_lint.py::TestHasFailures -v
```
Expected: All `TestLintRepo` tests fail with `NotImplementedError`; `TestHasFailures` tests pass (already implemented).

- [ ] **Step 3: Implement `lint_repo`**

Replace `lint_repo` in `docforge/lint.py`:

```python
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
```

- [ ] **Step 4: Run tests and verify they pass**

Run:
```bash
cd /e/docforge && pytest tests/unit/test_lint.py -v
```
Expected: All 13 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /e/docforge && git add docforge/lint.py tests/unit/test_lint.py && git -c commit.gpgsign=false commit -m "Implement lint_repo with banned-content scanning"
```

---

### Task 4: Implement `format_report`

**Files:**
- Modify: `E:/docforge/docforge/lint.py`
- Modify: `E:/docforge/tests/unit/test_lint.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_lint.py`:

```python
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
```

- [ ] **Step 2: Run tests and verify they fail**

Run:
```bash
cd /e/docforge && pytest tests/unit/test_lint.py::TestFormatReport -v
```
Expected: Both tests fail with `NotImplementedError`.

- [ ] **Step 3: Implement `format_report`**

Replace `format_report` in `docforge/lint.py`:

```python
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
    # Group by file, preserving first-seen order.
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
```

- [ ] **Step 4: Run tests and verify they pass**

Run:
```bash
cd /e/docforge && pytest tests/unit/test_lint.py -v
```
Expected: All 15 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /e/docforge && git add docforge/lint.py tests/unit/test_lint.py && git -c commit.gpgsign=false commit -m "Implement lint.format_report"
```

---

### Task 5: Add `lint-docs` CLI subcommand

**Files:**
- Modify: `E:/docforge/docforge/cli.py` (insert after line 125, i.e. after the `status` command)
- Modify: `E:/docforge/tests/unit/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cli.py`:

```python
class TestLintDocsCommand:
    def test_clean_repo_exits_zero(self, tmp_path, monkeypatch):
        (tmp_path / "README.md").write_text("# Clean repo\n", encoding="utf-8")
        result = runner.invoke(app, ["lint-docs", str(tmp_path)])
        assert result.exit_code == 0
        assert "PASS" in result.output

    def test_failing_repo_exits_one(self, tmp_path, monkeypatch):
        (tmp_path / "README.md").write_text(
            "# Repo\n\nTODO: Explain\n", encoding="utf-8"
        )
        result = runner.invoke(app, ["lint-docs", str(tmp_path)])
        assert result.exit_code == 1
        assert "FAIL" in result.output
        assert "todo-placeholder" in result.output

    def test_missing_directory_exits_one(self, tmp_path):
        missing = tmp_path / "does-not-exist"
        result = runner.invoke(app, ["lint-docs", str(missing)])
        assert result.exit_code == 1
        assert "not a directory" in (result.output + (result.stderr or ""))
```

- [ ] **Step 2: Run tests and verify they fail**

Run:
```bash
cd /e/docforge && pytest tests/unit/test_cli.py::TestLintDocsCommand -v
```
Expected: All 3 tests fail (`No such command 'lint-docs'`).

- [ ] **Step 3: Add the CLI subcommand**

Edit `docforge/cli.py`. After the `status()` function (ends at line 125) and before `_setup_logging()` (line 127), insert:

```python
@app.command(name="lint-docs")
def lint_docs(
    repo_path: Path = typer.Argument(..., help="Path to the repo root to lint"),
) -> None:
    """Lint a repo's README + CLAUDE.md + docs/ for banned-content rules from the authoring guideline."""
    from docforge.lint import _discover_files, format_report, has_failures, lint_repo

    if not repo_path.is_dir():
        typer.echo(f"Error: {repo_path} is not a directory", err=True)
        raise typer.Exit(1)

    scanned = _discover_files(repo_path)
    findings = lint_repo(repo_path)
    typer.echo(format_report(findings, scanned, repo_path))
    if has_failures(findings):
        raise typer.Exit(1)
```

- [ ] **Step 4: Run tests and verify they pass**

Run:
```bash
cd /e/docforge && pytest tests/unit/test_cli.py::TestLintDocsCommand tests/unit/test_lint.py -v
```
Expected: All tests pass.

- [ ] **Step 5: Run the full unit suite to catch regressions**

Run:
```bash
cd /e/docforge && pytest tests/unit/ -q
```
Expected: All tests pass; coverage gate ≥60% preserved (check the summary line).

- [ ] **Step 6: Commit**

```bash
cd /e/docforge && git add docforge/cli.py tests/unit/test_cli.py && git -c commit.gpgsign=false commit -m "Add 'docforge lint-docs' CLI subcommand"
```

---

### Task 6: Manual verification against real exemplar + unretrofitted repos

**Files:**
- No code changes. Smoke-test only.

- [ ] **Step 1: Run linter against the Spec B exemplar (cloudstatus)**

Run:
```bash
cd /e/docforge && python -m docforge.cli lint-docs E:/cloudstatusrepos/cloudstatus
```
Expected: exit code 0, output contains `PASS`. Note the exact count shown in `N files scanned` — it should include readme.md, CLAUDE.md, and all `docs/*.md`.

If the exit code is 1, inspect the reported findings. Possible causes:
- Content drift since the spec was written (real banned pattern introduced)
- Overly broad regex matching something benign — in that case, tighten the regex with a more specific pattern, add a unit test that captures the false-positive case, then repeat this step.

- [ ] **Step 2: Run linter against an unretrofitted CCL repo**

Run:
```bash
cd /e/docforge && python -m docforge.cli lint-docs E:/DataCenter.Organization.Creation
```
Expected: exit code 1 with banned-content hits reported (Azure DevOps default README boilerplate). This validates that the linter actually catches the content Spec B targets.

If exit code is 0, the regex may be too narrow for the real content. Read the repo's `README.md` manually, identify the boilerplate, then tighten/adjust the `readme-boilerplate` or `readme-inspiration-link` pattern and add a test fixture captured from the real content.

- [ ] **Step 3: Record the smoke-test output in a scratch note and commit (no code change needed)**

No commit — Task 5 already committed the working linter. This task is verification only. If steps 1 or 2 forced a regex tweak, commit that separately:

```bash
cd /e/docforge && git add docforge/lint.py tests/unit/test_lint.py && git -c commit.gpgsign=false commit -m "Refine linter regex after smoke test against real repos"
```

---

## Phase 2 — Eval harness

### Task 7: Scaffold `docforge/scripts/` package and write `score_query`

**Files:**
- Create: `E:/docforge/docforge/scripts/__init__.py`
- Create: `E:/docforge/docforge/scripts/eval_search.py`
- Create: `E:/docforge/tests/unit/test_eval_search.py`

- [ ] **Step 1: Create the package marker**

Write `docforge/scripts/__init__.py`:

```python
"""Operator scripts for docforge (run via `python -m docforge.scripts.<name>`)."""
```

- [ ] **Step 2: Scaffold the eval_search module with data types + stubs**

Write `docforge/scripts/eval_search.py`:

```python
"""Evaluate docforge retrieval quality against a ground-truth query set.

Usage:
    python -m docforge.scripts.eval_search \\
      --api-url https://<fqdn> \\
      --ground-truth rag/eval/ground_truth.yml \\
      --user tobias.ens --team ccl --area cloud \\
      --k 5

Prints per-query detail + summary (recall@1, recall@k, MRR) to stdout. Exits 0
on successful run regardless of retrieval quality — this tool measures, it does
not gate.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml


@dataclass(frozen=True)
class QueryResult:
    query: str
    expected_substring: str
    returned_titles: list[str]
    returned_scores: list[float]
    match_rank: int | None  # 1-based; None if not in top-k


def score_query(returned_titles: list[str], expected_substring: str) -> int | None:
    """Return 1-based rank where expected_substring is contained in any title,
    case-insensitively; or None if no match. Pure function."""
    raise NotImplementedError


def summarize(results: list[QueryResult], k: int) -> dict[str, float | int]:
    """Return {queries, recall@1, recall@k, mrr}. Pure function."""
    raise NotImplementedError


async def run_queries(
    api_url: str,
    ground_truth: list[dict],
    user_name: str,
    team_name: str,
    area_name: str | None,
    k: int,
) -> list[QueryResult]:
    """POST each query to <api_url>/search via httpx; collect results. Sequential."""
    raise NotImplementedError


def format_report(results: list[QueryResult], summary: dict[str, float | int], k: int) -> str:
    """Per-query detail + summary. Human-readable stdout."""
    raise NotImplementedError


def _load_ground_truth(path: Path) -> list[dict]:
    """Load, validate, and return the `queries` list from a ground-truth YAML file."""
    if not path.is_file():
        raise FileNotFoundError(f"Ground truth file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    queries = data.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError(f"{path}: missing or empty 'queries' list")
    for i, q in enumerate(queries):
        if "q" not in q or "expected_title_contains" not in q:
            raise ValueError(
                f"{path}: entry {i} must have 'q' and 'expected_title_contains' keys"
            )
    return queries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-url", required=True, help="Base URL of the search API (no trailing slash)")
    parser.add_argument("--ground-truth", required=True, type=Path, help="Path to ground_truth.yml")
    parser.add_argument("--user", required=True, help="Your identity — forwarded as user_name")
    parser.add_argument("--team", required=True, help="Your team tag — forwarded as team_name")
    parser.add_argument("--area", default=None, help="Optional area tag — forwarded as area_name")
    parser.add_argument("--k", type=int, default=5, help="Top-k cutoff for recall@k")
    args = parser.parse_args()

    try:
        ground_truth = _load_ground_truth(args.ground_truth)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    results = asyncio.run(
        run_queries(
            api_url=args.api_url.rstrip("/"),
            ground_truth=ground_truth,
            user_name=args.user,
            team_name=args.team,
            area_name=args.area,
            k=args.k,
        )
    )
    summary = summarize(results, args.k)
    print(format_report(results, summary, args.k))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Write the failing test for `score_query`**

Write `tests/unit/test_eval_search.py`:

```python
"""Tests for docforge.scripts.eval_search pure functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from docforge.scripts.eval_search import (
    QueryResult,
    _load_ground_truth,
    score_query,
    summarize,
)


class TestScoreQuery:
    def test_hits_at_rank_1(self):
        assert score_query(["HTTP error handling guidelines", "other"], "HTTP error") == 1

    def test_hits_at_rank_3(self):
        titles = ["other1", "other2", "HTTP error handling guidelines", "other3"]
        assert score_query(titles, "HTTP error") == 3

    def test_no_match_returns_none(self):
        assert score_query(["foo", "bar"], "baz") is None

    def test_case_insensitive_match(self):
        assert score_query(["HTTP ERROR HANDLING"], "http error") == 1

    def test_empty_title_list_returns_none(self):
        assert score_query([], "anything") is None

    def test_expected_substring_as_whole_word_substring(self):
        assert score_query(["Organization Lifecycle — team responsibilities"], "Organization Lifecycle") == 1
```

- [ ] **Step 4: Run tests and verify they fail**

Run:
```bash
cd /e/docforge && pytest tests/unit/test_eval_search.py::TestScoreQuery -v
```
Expected: All 6 tests fail with `NotImplementedError`.

- [ ] **Step 5: Implement `score_query`**

Replace `score_query` in `docforge/scripts/eval_search.py`:

```python
def score_query(returned_titles: list[str], expected_substring: str) -> int | None:
    """Return 1-based rank where expected_substring is contained in any title,
    case-insensitively; or None if no match. Pure function."""
    needle = expected_substring.lower()
    for rank, title in enumerate(returned_titles, start=1):
        if needle in title.lower():
            return rank
    return None
```

- [ ] **Step 6: Run tests and verify they pass**

Run:
```bash
cd /e/docforge && pytest tests/unit/test_eval_search.py::TestScoreQuery -v
```
Expected: All 6 tests pass.

- [ ] **Step 7: Commit**

```bash
cd /e/docforge && git add docforge/scripts/ tests/unit/test_eval_search.py && git -c commit.gpgsign=false commit -m "Scaffold eval_search package; implement score_query"
```

---

### Task 8: Implement `summarize` and `_load_ground_truth` tests

**Files:**
- Modify: `E:/docforge/docforge/scripts/eval_search.py`
- Modify: `E:/docforge/tests/unit/test_eval_search.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_eval_search.py`:

```python
def _qr(query: str, expected: str, match_rank: int | None) -> QueryResult:
    return QueryResult(
        query=query,
        expected_substring=expected,
        returned_titles=[],
        returned_scores=[],
        match_rank=match_rank,
    )


class TestSummarize:
    def test_empty_results_returns_zero_metrics(self):
        out = summarize([], k=5)
        assert out == {"queries": 0, "recall@1": 0.0, "recall@5": 0.0, "mrr": 0.0}

    def test_all_hits_at_rank_1(self):
        results = [_qr("q1", "x", 1), _qr("q2", "x", 1)]
        out = summarize(results, k=5)
        assert out["queries"] == 2
        assert out["recall@1"] == 1.0
        assert out["recall@5"] == 1.0
        assert out["mrr"] == pytest.approx(1.0)

    def test_mixed_ranks(self):
        # 4 queries: ranks 1, 3, None, 5. k=5.
        # recall@1 = 1/4, recall@5 = 3/4, mrr = (1/1 + 1/3 + 0 + 1/5) / 4
        results = [
            _qr("q1", "x", 1),
            _qr("q2", "x", 3),
            _qr("q3", "x", None),
            _qr("q4", "x", 5),
        ]
        out = summarize(results, k=5)
        assert out["queries"] == 4
        assert out["recall@1"] == pytest.approx(0.25)
        assert out["recall@5"] == pytest.approx(0.75)
        assert out["mrr"] == pytest.approx((1 + 1/3 + 0 + 1/5) / 4)

    def test_recall_key_uses_k(self):
        out = summarize([_qr("q", "x", 1)], k=10)
        assert "recall@10" in out
        assert "recall@5" not in out


class TestLoadGroundTruth:
    def test_valid_file(self, tmp_path: Path):
        p = tmp_path / "gt.yml"
        p.write_text(
            "queries:\n"
            "  - q: 'how do retries work'\n"
            "    expected_title_contains: 'HTTP error handling'\n",
            encoding="utf-8",
        )
        out = _load_ground_truth(p)
        assert len(out) == 1
        assert out[0]["q"] == "how do retries work"

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            _load_ground_truth(tmp_path / "nope.yml")

    def test_empty_queries_raises(self, tmp_path: Path):
        p = tmp_path / "gt.yml"
        p.write_text("queries: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing or empty"):
            _load_ground_truth(p)

    def test_missing_required_keys_raises(self, tmp_path: Path):
        p = tmp_path / "gt.yml"
        p.write_text("queries:\n  - q: 'only q key'\n", encoding="utf-8")
        with pytest.raises(ValueError, match="must have"):
            _load_ground_truth(p)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:
```bash
cd /e/docforge && pytest tests/unit/test_eval_search.py::TestSummarize tests/unit/test_eval_search.py::TestLoadGroundTruth -v
```
Expected: `TestSummarize` tests fail with `NotImplementedError`; `TestLoadGroundTruth` tests pass (already implemented).

- [ ] **Step 3: Implement `summarize`**

Replace `summarize` in `docforge/scripts/eval_search.py`:

```python
def summarize(results: list[QueryResult], k: int) -> dict[str, float | int]:
    """Return {queries, recall@1, recall@k, mrr}. Pure function."""
    total = len(results)
    if total == 0:
        return {"queries": 0, "recall@1": 0.0, f"recall@{k}": 0.0, "mrr": 0.0}
    hits_at_1 = sum(1 for r in results if r.match_rank == 1)
    hits_at_k = sum(1 for r in results if r.match_rank is not None and r.match_rank <= k)
    mrr = sum(1.0 / r.match_rank for r in results if r.match_rank is not None) / total
    return {
        "queries": total,
        "recall@1": hits_at_1 / total,
        f"recall@{k}": hits_at_k / total,
        "mrr": mrr,
    }
```

- [ ] **Step 4: Run tests and verify they pass**

Run:
```bash
cd /e/docforge && pytest tests/unit/test_eval_search.py -v
```
Expected: All tests pass (score_query + summarize + load_ground_truth).

- [ ] **Step 5: Commit**

```bash
cd /e/docforge && git add docforge/scripts/eval_search.py tests/unit/test_eval_search.py && git -c commit.gpgsign=false commit -m "Implement eval_search.summarize + _load_ground_truth tests"
```

---

### Task 9: Implement `run_queries` and `format_report`

**Files:**
- Modify: `E:/docforge/docforge/scripts/eval_search.py`

No unit test — `run_queries` is a thin HTTP wrapper tested by the manual live-Azure run in Task 11. `format_report` is also verified by eyeballing the live-run output; unit-testing string formatting against hardcoded expected output is brittle and low-value here.

- [ ] **Step 1: Implement `run_queries`**

Replace `run_queries` in `docforge/scripts/eval_search.py`:

```python
async def run_queries(
    api_url: str,
    ground_truth: list[dict],
    user_name: str,
    team_name: str,
    area_name: str | None,
    k: int,
) -> list[QueryResult]:
    """POST each query to <api_url>/search via httpx; collect results. Sequential."""
    results: list[QueryResult] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for entry in ground_truth:
            q: str = entry["q"]
            expected: str = entry["expected_title_contains"]
            try:
                resp = await client.post(
                    f"{api_url}/search",
                    json={
                        "query": q,
                        "user_name": user_name,
                        "team_name": team_name,
                        "area_name": area_name,
                        "limit": k,
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
                hits = payload.get("results", [])
            except (httpx.HTTPError, ValueError) as e:
                print(f"  Query failed ({q!r}): {e}", file=sys.stderr)
                hits = []
            titles = [h.get("source_title", "") for h in hits]
            scores = [float(h.get("score", 0.0)) for h in hits]
            results.append(
                QueryResult(
                    query=q,
                    expected_substring=expected,
                    returned_titles=titles,
                    returned_scores=scores,
                    match_rank=score_query(titles, expected),
                )
            )
    return results
```

Note on API payload shape: `docforge/api.py`'s `/search` endpoint returns `{"results": [{"source_title": ..., "score": ..., ...}, ...]}`. If the real response uses different keys, adjust the `.get()` calls — this is why Task 11 (live smoke) comes next.

- [ ] **Step 2: Implement `format_report`**

Replace `format_report` in `docforge/scripts/eval_search.py`:

```python
def format_report(results: list[QueryResult], summary: dict[str, float | int], k: int) -> str:
    """Per-query detail + summary. Human-readable stdout."""
    lines: list[str] = []
    for r in results:
        lines.append(f"Query: {r.query!r}")
        lines.append(f"  Expected: contains {r.expected_substring!r}")
        if r.returned_titles:
            lines.append(f"  Top {len(r.returned_titles)}:")
            for i, (title, score) in enumerate(zip(r.returned_titles, r.returned_scores, strict=False), start=1):
                marker = "  ← MATCH" if r.match_rank == i else ""
                lines.append(f"    {i}. [{score:.2f}] {title}{marker}")
        else:
            lines.append("  Top: (no results)")
        if r.match_rank is not None and r.match_rank <= k:
            lines.append(f"  recall@{k}: HIT  rank: {r.match_rank}")
        else:
            lines.append(f"  recall@{k}: MISS")
        lines.append("")

    lines.append("Summary:")
    lines.append(f"  queries:               {summary['queries']}")
    recall1 = summary["recall@1"]
    recall_k = summary[f"recall@{k}"]
    total = summary["queries"] or 1
    lines.append(f"  recall@1:              {int(recall1 * total)}/{total} ({recall1 * 100:.0f}%)")
    lines.append(f"  recall@{k}:              {int(recall_k * total)}/{total} ({recall_k * 100:.0f}%)")
    lines.append(f"  mean reciprocal rank:  {summary['mrr']:.3f}")

    misses = [r for r in results if r.match_rank is None or r.match_rank > k]
    if misses:
        lines.append("")
        lines.append(f"  Missed (no match in top {k}):")
        for r in misses:
            lines.append(f"    - {r.query!r}  (expected {r.expected_substring!r})")

    return "\n".join(lines)
```

- [ ] **Step 3: Smoke-test the module imports and argparse --help works**

Run:
```bash
cd /e/docforge && python -m docforge.scripts.eval_search --help
```
Expected: argparse prints the module docstring + argument list; exit code 0.

- [ ] **Step 4: Run full suite to confirm no regression**

Run:
```bash
cd /e/docforge && pytest tests/unit/ -q
```
Expected: all tests pass; coverage ≥60%.

- [ ] **Step 5: Commit**

```bash
cd /e/docforge && git add docforge/scripts/eval_search.py && git -c commit.gpgsign=false commit -m "Implement eval_search.run_queries + format_report"
```

---

### Task 10: Operator README for the eval harness

**Files:**
- Create: `E:/docforge/docforge/scripts/README.md`

- [ ] **Step 1: Write the operator doc**

Write `docforge/scripts/README.md`:

```markdown
# docforge scripts

Operator scripts. Run with `python -m docforge.scripts.<name>`.

## eval_search — retrieval quality measurement

Measures how well docforge retrieves the expected source for each query in a
ground-truth set. Reports recall@1, recall@k, and mean reciprocal rank.

### Run against the live Azure deployment

```bash
python -m docforge.scripts.eval_search \
  --api-url https://docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io \
  --ground-truth path/to/ground_truth.yml \
  --user your.name --team your-team --area your-area \
  --k 5
```

### Ground truth format

YAML with a `queries` list. Each entry is a natural colleague query and a
substring expected to appear in the matching source's title:

```yaml
queries:
  - q: "how do retries work"
    expected_title_contains: "HTTP error handling guidelines"
```

See `knowledge-hub/rag/eval/ground_truth.yml` for the DocuWare-specific set.

### Interpreting results

There is **no pass/fail threshold**. Recall magnitude depends on the authoring
style of the ground-truth set — a query set that matches source titles word-for-word
will score ~100% regardless of retrieval quality; a query set in natural colleague
phrasing will score lower even on a perfect system.

**First run → record the baseline.** Commit the reported recall@1, recall@5, MRR
and the current `sources.yml` commit SHA to `rag/eval/baseline.md`.

**Future runs → compare against the baseline.** If metrics drop materially,
investigate: did `sources.yml` change? Did ingest drift? Did embeddings change?
If metrics rise, consider re-baselining.

### When to re-baseline

- `sources.yml` changed (additions, removals, tag edits)
- Embedding model changed
- Ranking weights (`tag_match_weight`, `org_tag_weight`) changed
- Ground truth rewritten
```

- [ ] **Step 2: Commit**

```bash
cd /e/docforge && git add docforge/scripts/README.md && git -c commit.gpgsign=false commit -m "Add operator README for docforge.scripts.eval_search"
```

---

## Phase 3 — Knowledge-hub: ground truth + baseline

### Task 11: First live-Azure eval run — verify the harness works end-to-end

**Files:**
- No code changes. Verification run only.

This task validates the API payload shape assumption (`results[*].source_title`, `results[*].score`) before the user invests effort in authoring 20-30 ground-truth entries.

- [ ] **Step 1: Write a tiny 2-entry scratch ground-truth file**

Create `E:/docforge/_scratch_gt.yml` (not committed — will be deleted at end of task):

```yaml
queries:
  - q: "how do retries work"
    expected_title_contains: "HTTP error handling"
  - q: "which team owns organization lifecycle"
    expected_title_contains: "Organization Lifecycle"
```

- [ ] **Step 2: Run the harness against live Azure**

Run (replace `your.name` / `your-team` if different):
```bash
cd /e/docforge && python -m docforge.scripts.eval_search \
  --api-url https://docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io \
  --ground-truth _scratch_gt.yml \
  --user tobias.ens --team ccl --area cloud \
  --k 5
```

Expected outcomes:
- **A (happy path):** Per-query output shows top-5 titles with scores; summary prints recall@1, recall@5, MRR; exit 0. Proceed.
- **B (empty results for all queries):** The `results[*].source_title` / `results[*].score` keys in `run_queries` don't match what the API returns. Inspect the raw API response by hand:
  ```bash
  curl -X POST https://docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io/search \
    -H "Content-Type: application/json" \
    -d '{"query":"test","user_name":"tobias.ens","team_name":"ccl","area_name":"cloud","limit":3}'
  ```
  Adjust the `.get("source_title", ...)` / `.get("score", ...)` lines in `run_queries` to match the actual field names, add a note in the commit, re-run.
- **C (HTTP errors):** Log shows `Query failed ...` for every query. The API may be cold-starting; wait 30 seconds and re-run. If the error is 4xx/5xx after warm-up, check that `user_name` / `team_name` are spelled correctly.

- [ ] **Step 3: Delete the scratch file**

```bash
rm /e/docforge/_scratch_gt.yml
```

- [ ] **Step 4: Commit any API-shape fixes required in Step 2**

If Step 2 required editing `run_queries`:
```bash
cd /e/docforge && git add docforge/scripts/eval_search.py && git -c commit.gpgsign=false commit -m "Align eval_search with live API response shape"
```

Otherwise no commit.

---

### Task 12: Author DocuWare ground truth (user task)

**Files:**
- Create: `E:/knowledge-hub/rag/eval/ground_truth.yml`

**This task is authored by the user (Tobias), not automatable.** The plan's job is to scaffold the file, document the authoring rules, and provide a starting list of query-shape hints pulled from `rag/sources.yml`.

- [ ] **Step 1: Read current sources.yml to produce authoring hints**

Run:
```bash
cd /e/knowledge-hub && cat rag/sources.yml | grep -E "^\s+-\s+title:" | head -30
```
Expected: prints ~30 source titles. These are the universe of valid `expected_title_contains` values.

- [ ] **Step 2: Scaffold `ground_truth.yml` with header + 5 seed entries**

First, capture the current sources.yml SHA:
```bash
cd /e/knowledge-hub && git rev-parse HEAD
```
Use that SHA in the file header below (placeholder `<SHA>`).

Write `E:/knowledge-hub/rag/eval/ground_truth.yml`:

```yaml
# Ground truth for docforge eval harness.
#
# Authored: 2026-04-20
# sources.yml SHA at authoring: <SHA>  # replace with output of `git rev-parse HEAD`
#
# Authoring guidance:
#   - Natural colleague phrasing ("how do retries work") NOT title-matching
#     ("HTTP error handling guidelines").
#   - Mix specific + domain-named + ambiguous queries (40/40/20 rough split).
#   - Use DocuWare-specific nouns: organization, shard, trial, smartupdate,
#     lifecycle, cloudstatus, cohort.
#   - Every `expected_title_contains` MUST match a real title in sources.yml
#     (substring, case-insensitive). Run the eval harness after edits to catch
#     typos — a query that returns 0 matches for its expected substring almost
#     always means the expected substring is misspelled or that title no
#     longer exists.
#
# Target: 20-30 entries. Edit this file, add entries, commit.

queries:
  # Seed entries — replace / extend.
  - q: "how do retries work"
    expected_title_contains: "HTTP error handling"

  - q: "which team owns organization lifecycle"
    expected_title_contains: "Organization Lifecycle"

  - q: "how does smartupdate propagate"
    expected_title_contains: "SmartUpdate"

  - q: "what is a cohort"
    expected_title_contains: "Cohort"

  - q: "how do I deploy to staging"
    expected_title_contains: "Deployment"
```

- [ ] **Step 3: (USER) Extend to 20-30 entries**

The user reviews the seed entries, replaces any where `expected_title_contains` doesn't match a real source title, and adds 15-25 more queries covering:
- Team-responsibility lookups ("which team owns X")
- Architecture / pattern queries ("how does Y work")
- Specific how-to queries ("how do I do Z")
- A few ambiguous / broad queries to probe recall breadth

**Do not invent titles.** Every `expected_title_contains` value must be a substring (case-insensitive) of some `title:` in `rag/sources.yml`.

- [ ] **Step 4: Validate by running the harness**

```bash
cd /e/docforge && python -m docforge.scripts.eval_search \
  --api-url https://docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io \
  --ground-truth /e/knowledge-hub/rag/eval/ground_truth.yml \
  --user tobias.ens --team ccl --area cloud \
  --k 5
```
Scan the output: any query that reports `MISS` AND the top-5 titles contain NO obvious related result is a signal to check the `expected_title_contains` for a typo against `sources.yml`. If it's a typo, fix it. If the retrieval really missed, that's fine — keep the entry; it's signal for the baseline.

- [ ] **Step 5: Commit the ground truth**

```bash
cd /e/knowledge-hub && git add rag/eval/ground_truth.yml && git -c commit.gpgsign=false commit -m "Add DocuWare ground truth for docforge eval harness"
```

---

### Task 13: Record the first-run baseline

**Files:**
- Create: `E:/knowledge-hub/rag/eval/baseline.md`

- [ ] **Step 1: Run the harness with the final ground truth and capture output**

```bash
cd /e/docforge && python -m docforge.scripts.eval_search \
  --api-url https://docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io \
  --ground-truth /e/knowledge-hub/rag/eval/ground_truth.yml \
  --user tobias.ens --team ccl --area cloud \
  --k 5 \
  > /e/knowledge-hub/rag/eval/_run_output.txt
```
Read the summary at the bottom. Capture the three numbers: recall@1, recall@5, MRR.

- [ ] **Step 2: Capture the sources.yml SHA**

```bash
cd /e/knowledge-hub && git rev-parse HEAD
```

- [ ] **Step 3: Write the baseline**

Write `E:/knowledge-hub/rag/eval/baseline.md`:

```markdown
# docforge eval baseline

First-run baseline for retrieval quality. This is the reference point for
future regression detection — there is no fixed pass/fail bar.

## Baseline run

- **Date:** 2026-04-20
- **sources.yml SHA:** `<SHA_FROM_STEP_2>`
- **ground_truth.yml entries:** <N>
- **API:** https://docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io
- **Embedding model:** EmbeddingGemma-300M
- **Ranking weights:** tag_match_weight=<check docforge.yml>, org_tag_weight=<check>

## Metrics

| Metric   | Value |
|----------|-------|
| recall@1 | X/N (X%) |
| recall@5 | Y/N (Y%) |
| MRR      | Z.ZZZ |

## How to compare future runs

Re-run with the same `--k 5`, same ground truth, same identity args. If
metrics drop by more than ~5 points absolute, investigate:

1. Did `sources.yml` change? If titles changed, `expected_title_contains`
   values may now mismatch. Fix ground truth; re-baseline.
2. Did ingest drift? Check `docforge status` for chunk counts.
3. Did embeddings change? Re-ingest is required.
4. Did ranking weights change? Revert or re-baseline.

## When to re-baseline

- `sources.yml` materially changed (new sources, renamed titles)
- Embedding model changed
- Ranking weights changed
- Ground truth extended / rewritten
```

Fill in the `<...>` placeholders with real numbers from Step 1.

- [ ] **Step 4: Delete the temp output file**

```bash
rm /e/knowledge-hub/rag/eval/_run_output.txt
```

- [ ] **Step 5: Commit**

```bash
cd /e/knowledge-hub && git add rag/eval/baseline.md && git -c commit.gpgsign=false commit -m "Record first-run baseline for docforge eval harness"
```

---

### Task 14: Operator doc for knowledge-hub eval directory

**Files:**
- Create: `E:/knowledge-hub/rag/eval/README.md`

- [ ] **Step 1: Write the operator doc**

Write `E:/knowledge-hub/rag/eval/README.md`:

```markdown
# docforge eval — DocuWare operator notes

This directory holds the DocuWare-specific inputs and outputs for the docforge
eval harness. The harness itself lives in the docforge repo
(`docforge/scripts/eval_search.py`).

## Files

- `ground_truth.yml` — 20-30 colleague-phrased queries with expected title substrings.
- `baseline.md` — first-run metrics. Reference point for regression detection.
- `README.md` — this file.

## Running the harness

From a clone of the docforge repo:

```bash
python -m docforge.scripts.eval_search \
  --api-url https://docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io \
  --ground-truth /path/to/knowledge-hub/rag/eval/ground_truth.yml \
  --user your.name --team your-team --area your-area \
  --k 5
```

## Interpreting metrics

**Absolute numbers are not meaningful; deltas against `baseline.md` are.**

Recall magnitude depends on how `ground_truth.yml` is phrased. A query set that
echoes source titles word-for-word will hit near 100% regardless of retrieval
quality. The DocuWare ground truth deliberately uses natural colleague phrasing,
so recall@5 in the 40-70% range is plausible on a healthy system.

## When to re-baseline

See `baseline.md` for conditions. Broadly: any change that materially moves the
needle on retrieval (sources, embeddings, weights, ground truth) requires a
fresh baseline.
```

- [ ] **Step 2: Commit**

```bash
cd /e/knowledge-hub && git add rag/eval/README.md && git -c commit.gpgsign=false commit -m "Add README for rag/eval directory"
```

---

## Final verification

### Task 15: End-to-end verification

- [ ] **Step 1: Linter passes on exemplar**

```bash
cd /e/docforge && python -m docforge.cli lint-docs E:/cloudstatusrepos/cloudstatus
```
Expected: exit 0, output contains `PASS`.

- [ ] **Step 2: Linter fails on unretrofitted repo**

```bash
cd /e/docforge && python -m docforge.cli lint-docs E:/DataCenter.Organization.Creation
```
Expected: exit 1, output contains `FAIL` with banned-content hits listed.

- [ ] **Step 3: Unit tests pass + coverage gate preserved**

```bash
cd /e/docforge && pytest tests/unit/ -q --cov=docforge --cov-report=term-missing:skip-covered
```
Expected: all tests pass; coverage ≥60% (projected ~78-82%).

- [ ] **Step 4: Ruff format + lint clean**

```bash
cd /e/docforge && ruff format --check . && ruff check .
```
Expected: both exit 0.

If ruff format reports changes needed, run `ruff format .` and commit with `style: ruff format sweep`.

- [ ] **Step 5: Eval harness reports the baseline metrics from `baseline.md`**

Re-run the harness (same command as Task 13 Step 1) and visually confirm the metrics match what's in `baseline.md`. This proves the harness is deterministic against the live API for a given ground-truth + sources.yml combo.

- [ ] **Step 6: Final commit (if needed) and push**

If there are uncommitted tweaks:
```bash
cd /e/docforge && git status
```
Commit anything outstanding, then push both repos:
```bash
cd /e/docforge && git push origin master
cd /e/knowledge-hub && git push origin master
```

---

## Success criteria recap (from spec)

- [x] `docforge lint-docs <path>` exits 1 on banned-content hits; exits 0 on clean. (Task 5)
- [x] `docforge lint-docs E:/cloudstatusrepos/cloudstatus` exits 0. (Task 6, Task 15 Step 1)
- [x] `docforge lint-docs E:/DataCenter.Organization.Creation` exits 1. (Task 6, Task 15 Step 2)
- [x] `python -m docforge.scripts.eval_search ...` runs end-to-end, prints per-query detail + summary. (Tasks 9–11)
- [x] `rag/eval/ground_truth.yml` has 20-30 user-authored entries; every `expected_title_contains` matches a real source title. (Task 12)
- [x] First live-Azure eval run produces a recorded baseline committed to `rag/eval/baseline.md`. No pass/fail bar. (Task 13)
- [x] All new unit tests pass. Coverage ≥60% preserved. (Task 15 Step 3)
