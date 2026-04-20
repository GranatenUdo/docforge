# Spec C2 — Quality Harnesses

**Date:** 2026-04-20
**Status:** Approved, ready for implementation plan
**Part of:** Phase 4 Spec C (hardening sprint) — sub-spec 2 of 4. Siblings: C1 (CI + supply-chain, shipped), C3 (security + privacy, pending), C4 (operational readiness, pending).
**Scope:** Ship two quality-measurement tools: (a) a `docforge lint-docs` CLI subcommand that enforces Spec B's authoring guideline rules against a target repo, and (b) a `docforge/scripts/eval_search.py` runner that measures retrieval quality against the live Azure deployment using a DocuWare-specific ground-truth set.

## Context

Spec A added team tagging; Spec B published an authoring guideline; C1 added CI. What's still missing is **measurement**: (1) no tool checks whether a CCL repo's docs conform to the Spec B guideline, and (2) no mechanism measures whether docforge retrieval actually returns relevant sources for realistic colleague queries.

C2 closes both. The two tools are independent — different audiences, different workflows — but they share the "quality harness" theme and ship as one coordinated sub-spec.

## Goals

1. Ship `docforge lint-docs <repo-path>` that scans README + `docs/` for Spec B banned-content rules and missing required topics; exits non-zero on any fail.
2. Ship `docforge/scripts/eval_search.py` that runs a query set against a deployed `/search` endpoint and reports recall@1, recall@5, and MRR.
3. Ship a DocuWare-specific ground-truth query set (`knowledge-hub/rag/eval/ground_truth.yml`, 20-30 entries, user-authored).
4. Maintain the ≥60% coverage gate; add unit tests covering linter logic and eval scorer (pure-function).

Non-goals (deliberate scope limits):
- Do NOT gate CI on the linter — runs only when a human invokes it. Unretrofitted CCL repos fail the lint today; that is information, not a merge block.
- Do NOT gate CI on the eval harness — retrieval quality is measured manually when a human wants to observe regression.
- Do NOT track eval results over time (CSV/DB). Ship the runner; add history later if usage demands.
- Do NOT support multiple acceptable answers per ground-truth query (`expected_title_contains` is a single string). v1 simplicity.
- Do NOT check for Confluence link rot, dead hyperlinks, or image resolution. Pure regex + structural linting.
- Do NOT ship lint severity tiers beyond rule category (each rule is either fail or absent).

## Design principles

- **Two tools, one spec** — they are related, both close the same maturity gap (no way to measure quality), and bundling keeps the Phase 4 decomposition honest.
- **User-invoked, not CI-gated** — both tools are observation-mode at this maturity level. Enforcement via CI is a future concern after team adoption + usage data.
- **docforge owns the tools, knowledge-hub owns the data** — linter is generic Python logic; eval runner is generic; ground truth is DocuWare-specific.
- **Real signal over synthetic** — eval runs against the live Azure deployment, not a local FakeEmbedder. The whole point of the eval is to detect drift in production.

## Linter

### Shape

`docforge lint-docs <repo-path>` — a Typer subcommand on docforge's existing CLI.

### Files

- Create: `docforge/lint.py` — pure Python lint logic, importable, no CLI coupling.
- Modify: `docforge/cli.py` — add `@app.command(name="lint-docs")` wrapper. ~15 lines.
- Test: `tests/unit/test_lint.py` — `tmp_path`-based synthetic markdown fixtures. ~80 lines.
- Test: `tests/unit/test_cli.py` (extend) — CliRunner tests for the new subcommand. ~20 lines.

### `docforge/lint.py` interface

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass
class LintFinding:
    severity: Literal["fail"]     # v1: no "warn" tier
    file: str                      # relative path, or "README + docs/" for topic-level
    line: int | None               # None for topic-level findings
    rule: str                      # short rule name (used for grouping)
    message: str                   # actionable text


BANNED_RULES: list[tuple[str, str, str]] = [
    ("todo-placeholder",  r"TODO.*(Explain|Contribute)",
     "Placeholder TODO — delete and write real content"),
    ("readme-inspiration-link",  r"create-a-readme",
     "Microsoft README inspirational link — delete"),
    ("readme-boilerplate",  r"(ASP\.NET Core|Microsoft/vscode|ChakraCore).*(readme|inspiration)",
     "Azure DevOps default boilerplate — delete whole block"),
    ("lastpass-reference",  r"LastPass",
     "Credential-source reference — move to Teams channel, not indexed docs"),
]


REQUIRED_TOPICS: list[tuple[str, str]] = [
    ("title",                      r"^#\s+\S"),
    ("intro-paragraph",            r"^(?!#)\S+.{50,}"),
    ("scope-or-use-cases",         r"(?i)##\s+(scope|use case)"),
    ("architecture",               r"(?i)##\s+architecture"),
    ("communication-or-integration", r"(?i)##\s+(communication|integration|api)"),
    ("operations-or-deploy",       r"(?i)##\s+(operations|deploy|running)"),
]


def lint_repo(repo_root: Path) -> list[LintFinding]:
    """Walk the repo's doc surface; return all findings. Read-only."""
    ...


def format_report(findings: list[LintFinding]) -> str:
    """Human-readable stdout string, grouped by file with summary line."""
    ...


def has_failures(findings: list[LintFinding]) -> bool:
    return any(f.severity == "fail" for f in findings)
```

### CLI integration (`docforge/cli.py` addition)

```python
@app.command(name="lint-docs")
def lint_docs(
    repo_path: Path = typer.Argument(..., help="Path to the repo root"),
) -> None:
    """Lint a repo's README + CLAUDE.md + docs/ against the authoring guideline."""
    from docforge.lint import format_report, has_failures, lint_repo

    if not repo_path.is_dir():
        typer.echo(f"Error: {repo_path} is not a directory", err=True)
        raise typer.Exit(1)

    findings = lint_repo(repo_path)
    typer.echo(format_report(findings))
    if has_failures(findings):
        raise typer.Exit(1)
```

### Doc discovery behavior

`lint_repo` scans:
- Root-level `README.md` (or `readme.md`, case-insensitive)
- Root-level `CLAUDE.md`
- All `*.md` under `docs/` (recursive)

Missing files don't crash — they reduce what can be checked, and can cause topic-level failures (e.g., if the repo has no `README.md`, "title" is missing).

### Required-topics semantics

A topic (e.g., "architecture") is satisfied if ANY of the scanned files contains a matching heading. This reflects Spec B's "README + docs/ together must cover X" principle. The finding's `file` field reads `"README + docs/"` for topic-level findings.

### Output format

Sample clean repo:
```
E:/cloudstatusrepos/cloudstatus — PASS
  3 files scanned (readme.md, CLAUDE.md, 12 under docs/)
  No banned content, all required topics present
```

Sample failing repo:
```
E:/DataCenter.Organization.Creation — FAIL
  2 files scanned (README.md, CLAUDE.md)

  Banned content:
    FAIL  README.md:3   todo-placeholder     Placeholder TODO — delete and write real content
    FAIL  README.md:8   readme-inspiration-link  Microsoft README inspirational link — delete
    FAIL  README.md:12  readme-boilerplate   Azure DevOps default boilerplate — delete whole block

  Required topics (across README + docs/):
    ✗ scope-or-use-cases      missing; add ## heading in README or docs/
    ✗ architecture            missing
    ✗ communication-or-integration  missing
    ✗ operations-or-deploy    missing

  Summary: 3 banned-content hits, 4 missing topics
```

Exit code 1 on any fail, 0 on clean.

### Testing

`tests/unit/test_lint.py` creates a `tmp_path` dir per test, writes synthetic markdown, asserts on findings:

- `test_clean_repo_has_no_findings` — well-formed README + full docs/
- `test_banned_todo_placeholder` — README with `TODO: Explain` → 1 finding
- `test_banned_create_readme_link` — README with `create-a-readme` URL → 1 finding
- `test_banned_lastpass_reference` — README mentioning `LastPass` → 1 finding
- `test_missing_architecture_topic` — README without `## Architecture` AND docs/ without it → topic-level finding
- `test_architecture_satisfied_by_docs` — README missing it but `docs/architecture.md` contains `## Architecture` → no finding
- `test_empty_repo` — no README, no CLAUDE, no docs → multiple topic-level findings
- `test_line_numbers_reported` — finding's `line` matches the actual line of the hit

Plus `tests/unit/test_cli.py` extension:
- `test_lint_docs_clean_exits_zero` (mock `lint_repo` returning [])
- `test_lint_docs_with_failures_exits_one` (mock `lint_repo` returning failing finding)
- `test_lint_docs_missing_directory_errors`

## Eval harness

### Shape

Standalone script, not a CLI subcommand. Too many args (`--api-url`, `--ground-truth`, `--user`, `--team`, `--area`, `--k`) for a user-facing command. Run via `python -m docforge.scripts.eval_search ...`.

### Files

- Create: `docforge/scripts/__init__.py` — package marker, empty.
- Create: `docforge/scripts/eval_search.py` — runner + scorer + main. ~130 lines.
- Create: `docforge/scripts/README.md` — operator doc. ~40 lines.
- Test: `tests/unit/test_eval_search.py` — scorer + summarize unit tests. ~60 lines.

### `eval_search.py` structure

```python
"""Evaluate docforge retrieval quality against a ground-truth query set.

Usage:
    python -m docforge.scripts.eval_search \
      --api-url https://<fqdn> \
      --ground-truth rag/eval/ground_truth.yml \
      --user tobias.ens --team ccl --area cloud \
      --k 5
"""
from dataclasses import dataclass


@dataclass
class QueryResult:
    query: str
    expected_substring: str
    returned_titles: list[str]
    match_rank: int | None   # 1-based; None if not in top-k


def score_query(
    returned_titles: list[str],
    expected_substring: str,
) -> int | None:
    """Return 1-based rank where expected_substring is contained in any title,
    case-insensitively; or None if no match. Pure function."""


async def run_queries(
    api_url: str,
    ground_truth: list[dict],
    user_name: str,
    team_name: str,
    area_name: str | None,
    k: int,
) -> list[QueryResult]:
    """POST each query to <api_url>/search via httpx; collect results."""


def summarize(results: list[QueryResult], k: int) -> dict[str, float | int]:
    """Return {queries, recall@1, recall@k, mrr}. Pure function."""


def format_report(results: list[QueryResult], summary: dict, k: int) -> str:
    """Per-query detail + summary. Human-readable stdout."""


def main() -> int:
    """argparse → load YAML → asyncio.run(run_queries) → score → report → return exit."""
```

### Ground-truth loading

Reads the YAML file at `--ground-truth` path:

```yaml
queries:
  - q: "how do retries work"
    expected_title_contains: "HTTP error handling guidelines"
  # ...
```

Validates: file exists, parses, has `queries` key, each entry has `q` and `expected_title_contains`. Fails with a clear error if malformed.

### HTTP call shape

For each query:
```python
response = await httpx_client.post(
    f"{api_url}/search",
    json={
        "query": q,
        "user_name": user_name,
        "team_name": team_name,
        "area_name": area_name,
        "limit": k,
    },
    timeout=30.0,
)
```

Uses a single `AsyncClient` for all queries (connection reuse). Queries run sequentially — 20-30 of them; parallelism is not worth the complexity and risks overwhelming the single-replica deployment.

### Scoring

`score_query` iterates returned titles; returns the 1-based rank where `expected_substring.lower() in title.lower()`, or None if not found within `k` results.

### Summary

```python
{
    "queries": total,
    "recall@1": hits_at_1 / total,
    "recall@5": hits_at_k / total,     # key set by --k arg
    "mrr": sum(1/r.match_rank for r in hits) / total,
}
```

### Output format

```
Query: "how do retries work"
  Expected: contains "HTTP error handling guidelines"
  Top 5:
    1. [0.63] DataCenter.Organization.SubscriptionPlan/docs/DOMAIN_ARCHITECTURE.md
    2. [0.59] knowledge-hub/docs/superpowers/plans/...
    3. [0.54] HTTP error handling guidelines          ← MATCH @ 3
    4. [0.51] [Tech Paper] Cluster Infrastructure
    5. [0.48] Domain - Cloud Status
  recall@5: HIT  rank: 3

...

Summary:
  queries:               N
  recall@1:              X/N (X%)
  recall@5:              Y/N (Y%)
  mean reciprocal rank:  Z

  Missed (no match in top 5):
    - "query text"  (expected "substring")
```

### Testing

`tests/unit/test_eval_search.py`:
- `test_score_query_hits_at_rank_1` — first result matches
- `test_score_query_hits_at_rank_3` — third result matches
- `test_score_query_no_match_returns_none`
- `test_score_query_case_insensitive_match`
- `test_summarize_empty_returns_zero_metrics`
- `test_summarize_computes_recall_and_mrr` — parameterized with fixtures

No test for `run_queries` — HTTP wrapper, tested by manual runs against live Azure.

### Dependencies

No new deps:
- `httpx` — already in docforge deps
- `pyyaml` — transitively available via `sentence-transformers`

## Ground truth (knowledge-hub)

### Files

- Create: `knowledge-hub/rag/eval/ground_truth.yml` — 20-30 user-authored pairs
- Create: `knowledge-hub/rag/eval/README.md` — 1-page operator doc explaining how to run the harness

### `ground_truth.yml` format

```yaml
# Ground truth for docforge eval harness.
# Authored 2026-04-20 against sources.yml commit <sha>.
#
# Authoring guidance:
#   - Natural colleague phrasing ("how do retries work") NOT title-matching ("HTTP error handling guidelines").
#   - Mix specific + domain-named + ambiguous queries.
#   - Use DocuWare-specific nouns: organization, shard, trial, smartupdate.
#   - Every expected_title_contains MUST match a real title in sources.yml.

queries:
  - q: "how do retries work"
    expected_title_contains: "HTTP error handling guidelines"
  # ... 19-29 more
```

### `knowledge-hub/rag/eval/README.md` shape

1-page operator doc. Primary content:

- Run command with env-var-sourced identity
- Expected output (recall@5 ≥ 50% sanity bar; target ≥70%)
- When to update `ground_truth.yml` (sources.yml changes, query drift)

## File summary

| Path | Status | Purpose | Approx LoC |
|---|---|---|---|
| `docforge/lint.py` | NEW | Lint logic | ~100 |
| `docforge/cli.py` | MODIFY | Add `lint-docs` subcommand | +15 |
| `docforge/scripts/__init__.py` | NEW | Package marker | 0 |
| `docforge/scripts/eval_search.py` | NEW | Eval runner | ~130 |
| `docforge/scripts/README.md` | NEW | Operator notes | ~40 |
| `tests/unit/test_lint.py` | NEW | Linter unit tests | ~80 |
| `tests/unit/test_eval_search.py` | NEW | Eval scorer unit tests | ~60 |
| `tests/unit/test_cli.py` | MODIFY | Tests for `lint-docs` | +20 |
| `knowledge-hub/rag/eval/ground_truth.yml` | NEW | DocuWare query set | ~80 (data) |
| `knowledge-hub/rag/eval/README.md` | NEW | Operator doc | ~50 |

7 new + 2 modified files across both repos.

## Success criteria

- [ ] `docforge lint-docs <path>` exits 1 on banned-content hits or missing required topics; exits 0 on clean.
- [ ] `docforge lint-docs E:/cloudstatusrepos/cloudstatus` exits 0 (exemplar repo passes).
- [ ] `docforge lint-docs E:/DataCenter.Organization.Creation` exits 1 (unretrofitted repo with ADO-default README fails).
- [ ] `python -m docforge.scripts.eval_search ...` runs end-to-end, prints per-query detail + summary with recall@1, recall@5, MRR.
- [ ] `knowledge-hub/rag/eval/ground_truth.yml` has 20-30 user-authored entries; every `expected_title_contains` matches a real source title in current `sources.yml`.
- [ ] First live-Azure eval run achieves **recall@5 ≥ 50%**. (Below this suggests ground-truth mis-specification or ingest drift — investigate before claiming the harness works.)
- [ ] All new unit tests pass. Coverage gate ≥60% preserved (projected ~78-82% with additions).

## Out of scope (deferred)

- **Results history** — track runs over time in CSV/DB. Future enhancement; ship the tool first.
- **Lint-as-CI-check** — gating CCL repo PRs on lint pass. Needs org-wide adoption first.
- **Multiple acceptable answers per query** — `expected_title_contains` as list. v1 is single-string.
- **Latency/cost measurement** — separate concern.
- **Confluence link resolution / dead-link detection in linter** — significant additional scope.
- **Lint severity tiers** beyond rule category — v1 is all-fail.

## Risks

- **Risk: first eval run's recall@5 is disappointingly low (< 50%).** Mitigation: treat it as signal — either ground truth is phrased too far from indexed content (rewrite), or there's a real retrieval issue to investigate.
- **Risk: linter produces noise on CCL repos that haven't opted in.** Mitigation: linter is user-invoked only. Running it on an un-retrofitted repo is an explicit choice; the noise is the point.
- **Risk: ground truth decays as `sources.yml` changes.** Mitigation: the YAML header comments the sources.yml SHA at authoring time. When eval results drift, check that first.

## Follow-up items (noted for future specs)

- Extend linter with additional rules: Confluence link validation, link-rot detection, diagram-file presence check, section-length heuristics, Title capitalization consistency.
- Eval harness: CSV output + `--baseline <file>` for regression detection.
- Eval harness: support multiple valid answers per query (list form).
- Integrate linter into a discoverable place: `docforge --help` already lists it; consider a badge in the Spec B guideline pointing at `docforge lint-docs`.
