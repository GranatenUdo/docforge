# Spec C1 — CI + Supply-Chain

**Date:** 2026-04-20
**Status:** Approved, ready for implementation plan
**Part of:** Phase 4 Spec C (hardening sprint) — sub-spec 1 of 4. Subsequent sub-specs: C2 (quality harnesses), C3 (security + privacy), C4 (operational readiness).
**Scope:** Add a minimal CI for docforge (GitHub Actions), a minimal config-validation pipeline for knowledge-hub (ADO), and Dependabot for docforge. Zero changes to production code; zero changes to the Azure deployment.

## Context

Neither docforge nor knowledge-hub has CI today. Every change reaches master with only local verification. Phase 4's maturity target is L3-across-the-board; "no CI" caps Quality readiness at L2. C1 closes that gap with a deliberately minimal approach.

An earlier draft proposed a 5-job CI with pyright, bandit, pip-licenses, and interrogate. That was theatre for a ~1000-line solo-maintainer Python project — each tool would produce near-zero useful findings while adding config surface and PR runtime. This spec ships the two checks that would actually block a bad merge (lint, test+coverage), plus Dependabot.

## Goals

1. Every docforge PR runs lint + test+coverage in GitHub Actions before merge.
2. Weekly Dependabot PRs for Python deps + GitHub Actions version pins.
3. Every knowledge-hub PR touching `rag/sources.yml`, `rag/teams.yml`, or `rag/scripts/**` validates YAML well-formedness + tag-vocabulary conformance before merge.

Non-goals (deliberate strip-down):
- No type-checking (pyright) — Phase 3's type-hint pass was correctness-driven; CI enforcement would find near-zero new bugs.
- No security linter (bandit) — codebase uses parameterized SQL + `SecretStr` throughout; findings would be ~0.
- No license scanner (pip-licenses) — docforge is private; license policy has no audience until public release. Deferred to the public-release checklist.
- No docstring-coverage linter (interrogate) — Phase 3 was a deliberate docstring audit; re-measuring adds no information.
- No Docker base-image Dependabot — low-frequency value, PR noise tradeoff unclear. Revisit if needed.
- No integration-test runs in CI — integration tests require Docker + testcontainers; out of scope for free GitHub Actions runners. They remain runnable locally via `pytest -m integration`.
- No auto-merge rules for Dependabot PRs — keep human review at current maturity level.
- No Bicep what-if in the knowledge-hub pipeline — the user opted for config-validation-only (option A in brainstorm).
- No docforge test runs from the knowledge-hub pipeline — docforge CI gates docforge quality independently.

## Design principles

- **Signal over ritual.** Every check has an observable failure mode. No tools that exist to tick a box.
- **Match the codebase.** A ~1000-line solo-maintainer project does not need a 6-job CI. It needs the two checks that would catch real mistakes.
- **Defer public-release concerns.** License scanning, wider version matrices, SBOM generation, etc. belong to a separate future public-release checklist — not this spec.

## docforge CI (GitHub Actions)

### File: `.github/workflows/ci.yml`

```yaml
name: CI

on:
  pull_request:
    branches: [master]
  push:
    branches: [master]

permissions:
  contents: read

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      - run: pip install -e ".[dev]"
      - run: ruff check docforge tests
      - run: ruff format --check docforge tests

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      - run: pip install -e ".[dev]"
      - run: pytest -m "not integration"
      # pytest-cov enforces fail_under=60 via pyproject [tool.coverage.report]
```

**Design notes:**
- Two parallel jobs. Both must pass for PR merge.
- Python 3.12 only (what Azure runs). Multi-version matrix deferred.
- pip cache keyed on OS + Python version. Adequate for a project with ~15 direct deps.
- No secrets, no artifacts, no deploys. Read-only permissions.

### File: `.github/dependabot.yml`

```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule:
      interval: weekly
      day: monday
    open-pull-requests-limit: 5
    groups:
      production:
        dependency-type: production
        update-types: [minor, patch]
      development:
        dependency-type: development
        update-types: [minor, patch]
    labels: [dependencies]
    commit-message:
      prefix: deps
      include: scope

  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
      day: monday
    open-pull-requests-limit: 3
    labels: [dependencies, ci]
    commit-message:
      prefix: ci(deps)
```

**Design notes:**
- Monday weekly for both ecosystems. Patches + minors grouped per dependency-type to cap PR count.
- Major bumps arrive individually (default behaviour; needs explicit review).
- Labels enable filtering in the GitHub PR list.

### Branch protection (GitHub Settings — not in this repo)

Document these settings so they can be applied one-click after the workflow lands. **Not part of the spec's committed artifacts** — GitHub repo settings, not files:

- Require pull request before merging to master
- Require status checks to pass: `lint`, `test`
- Do not allow force pushes

## knowledge-hub pipeline (Azure DevOps)

### File: `.pipelines/config-validation.yml`

```yaml
trigger:
  branches:
    include: ['master']
  paths:
    include:
      - 'rag/sources.yml'
      - 'rag/teams.yml'
      - 'rag/scripts/**'

pr:
  branches:
    include: ['master']
  paths:
    include:
      - 'rag/sources.yml'
      - 'rag/teams.yml'
      - 'rag/scripts/**'

pool:
  vmImage: ubuntu-latest

steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.12'

  - script: pip install pyyaml
    displayName: Install deps

  - script: python rag/scripts/validate_sources.py
    displayName: Validate sources.yml + teams.yml
```

### File: `rag/scripts/validate_sources.py`

```python
"""Validate sources.yml + teams.yml well-formedness and tag vocabulary.

Called by the ADO pipeline on PR touching rag/*.yml. Fails non-zero on
any issue so the PR can't merge red.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

RAG_DIR = Path(__file__).parent.parent


def main() -> int:
    errors: list[str] = []

    teams_path = RAG_DIR / "teams.yml"
    sources_path = RAG_DIR / "sources.yml"

    try:
        teams_data = yaml.safe_load(teams_path.read_text()) or {}
    except yaml.YAMLError as e:
        print(f"teams.yml parse error: {e}", file=sys.stderr)
        return 1

    try:
        sources_data = yaml.safe_load(sources_path.read_text()) or {}
    except yaml.YAMLError as e:
        print(f"sources.yml parse error: {e}", file=sys.stderr)
        return 1

    vocabulary = {
        *(t["id"] for t in teams_data.get("teams", [])),
        *(a["id"] for a in teams_data.get("areas", [])),
        *(s["id"] for s in teams_data.get("special_tags", [])),
    }

    for i, src in enumerate(sources_data.get("sources", [])):
        title = src.get("title", f"<source #{i}>")
        tags = src.get("tags", [])
        if not tags:
            errors.append(f"{title}: no tags")
            continue
        unknown = [t for t in tags if t not in vocabulary]
        if unknown:
            errors.append(f"{title}: unknown tags {unknown} (not in teams.yml)")

    if errors:
        print("Validation errors:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    src_count = len(sources_data.get("sources", []))
    print(f"OK: {src_count} sources validated against {len(vocabulary)}-tag vocabulary")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Design notes:**
- Standalone — no docforge dependency. Pipeline cold-install is `pip install pyyaml`. Runs in ~5s.
- Validates three things: YAML parses, every source has ≥1 tag, every tag is in `teams.yml`'s declared vocabulary.
- Standalone Python script makes it trivially runnable locally: `python rag/scripts/validate_sources.py`. Dev loop feedback before pushing.
- Future rules go here (e.g., require `type`-specific tags, warn on duplicate source IDs). Single file, single entry point.

### ADO pipeline registration

One-time: register `.pipelines/config-validation.yml` in the ADO UI as a pipeline for the knowledge-hub repo. Not a file artifact. Documented for the implementation plan as a manual step.

## Expected first-run behavior

On first merge with CI enabled:

**docforge `lint` job:** expected green. Phase 3's ruff pass made the code conformant; `ruff format --check` will pass because `ruff format` was part of that pass.

**docforge `test` job:** expected green. `pytest -m "not integration"` currently passes 99/99, coverage 80%, gate 60%.

**docforge Dependabot:** first weekly run (Monday) opens ~0-3 PRs. Dep versions are fresh (Phase 4 recent).

**knowledge-hub pipeline:** expected green. `sources.yml` has 72 entries, all tagged (`ccl` + `org` + `cross-team`). `teams.yml` vocabulary covers those.

If any of these fail on first run: fix inline. Most likely failure is a `ruff format --check` diff if `ruff format` was never run on a file added post-Phase-3; resolution is `ruff format docforge tests`.

## Success criteria

- [ ] `docforge/.github/workflows/ci.yml` exists, two jobs (`lint`, `test`), both block PR merge on failure
- [ ] `docforge/.github/dependabot.yml` exists, covers pip + github-actions ecosystems
- [ ] `knowledge-hub/.pipelines/config-validation.yml` exists, triggered on YAML + script changes
- [ ] `knowledge-hub/rag/scripts/validate_sources.py` exists, validates vocabulary + well-formedness, exits non-zero on issues
- [ ] Branch protection configured on GitHub master (documented as a manual setup step in the plan)
- [ ] ADO pipeline registered for knowledge-hub (documented as a manual setup step)
- [ ] First CI run on both repos: green, or red with fixes applied inline

## Out of scope (deferred to later sub-specs or separate work)

- Type checking — Phase 3 was the type-hint pass; no CI enforcement.
- Security linting — deferred; SQL is parameterized, secrets via `SecretStr`, surface is small.
- License scanning — deferred to public-release checklist.
- Docstring-coverage linting — Phase 3 was the docstring pass.
- Docker base-image Dependabot — deferred.
- Integration-test runs in CI — stays local (needs Docker).
- Auto-merge for Dependabot PRs — stays human-reviewed.
- CI/CD for docforge image (push master → build + push to ACR) — Spec C4 or separate.
- Monitoring / alerting / dashboards — Spec C4.
- Bicep what-if in knowledge-hub pipeline — user chose validation-only (option A).

## Dependencies

- Spec A and Spec B both shipped — provides `sources.yml` tag structure that the validator checks.

## Risks

- **Risk: first CI run reveals latent issues not caught by local pytest.** Mitigation: run `ruff check` + `ruff format --check` + `pytest -m "not integration"` locally before pushing the CI workflow file; resolve any findings in the same PR.
- **Risk: Dependabot PRs overwhelm the solo maintainer.** Mitigation: grouped minor+patch updates cap weekly PRs at ~2-3. Major bumps arrive individually and can be deferred (unreviewed PRs don't block anything).
- **Risk: knowledge-hub's ADO pipeline needs UI-level registration that a future maintainer misses.** Mitigation: document the registration step in the plan; also noted in `knowledge-hub/rag/infrastructure/README.md` as part of the setup runbook.
