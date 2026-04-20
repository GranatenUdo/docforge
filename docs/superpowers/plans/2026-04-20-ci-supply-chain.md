# CI + Supply-Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a minimal PR-blocking CI for docforge (lint + test on GitHub Actions), weekly Dependabot (pip + github-actions), and a knowledge-hub ADO pipeline that validates `sources.yml` + `teams.yml` tag vocabulary.

**Architecture:** Cross-repo plan. docforge gains two config files under `.github/` + a one-time `ruff format` sweep of existing code. knowledge-hub gains a `.pipelines/` YAML and a standalone Python validator script. Branch protection and ADO pipeline registration are manual UI steps, documented here.

**Tech Stack:** GitHub Actions, Dependabot v2, Azure DevOps Pipelines, ruff, pytest, Python 3.12, PyYAML.

---

## File structure

**docforge — create:**
- `.github/workflows/ci.yml` — 2-job workflow (lint, test)
- `.github/dependabot.yml` — pip + github-actions ecosystems

**docforge — modify (format sweep, no semantic changes):**
- 22 files under `docforge/` and `tests/` — mechanical one-arg-per-line reformatting

**knowledge-hub — create:**
- `rag/scripts/validate_sources.py` — standalone validator (no docforge dep)
- `.pipelines/config-validation.yml` — ADO pipeline definition

**Manual (UI — not code):**
- GitHub repo settings: branch protection on `master`, require `lint` + `test` status checks
- ADO project: register `.pipelines/config-validation.yml` as a pipeline

---

## Task 1: Ruff-format sweep (docforge prep)

**Why first:** `ruff format --check` currently fails on 22 files. CI would go red on day one otherwise. This is mechanical, purely one-arg-per-line reformatting — no semantic changes.

**Files:** 22 files under `docforge/` and `tests/`; listed by `ruff format --check docforge tests`.

- [ ] **Step 1: Confirm current diff is purely formatting**

Run:
```bash
cd /e/docforge
source .venv/Scripts/activate
ruff format --check docforge tests 2>&1 | grep "Would reformat" | wc -l
```
Expected: `22`.

Spot-check one file:
```bash
ruff format --check --diff docforge/query_log.py | head -20
```
Expected: only whitespace / line-break changes (no variable renames, no logic changes).

- [ ] **Step 2: Apply the format**

```bash
ruff format docforge tests
```

- [ ] **Step 3: Verify tests still pass**

```bash
pytest -m "not integration"
```
Expected: `99 passed`, coverage 80%, gate 60% satisfied.

- [ ] **Step 4: Commit**

```bash
git add docforge tests
git commit -m "style: apply ruff format across tree (prep for CI)"
```

---

## Task 2: docforge CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create the workflow file**

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
```

- [ ] **Step 2: Verify YAML is well-formed**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo OK
```
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions workflow (lint + test on PR)"
```

---

## Task 3: docforge Dependabot config

**Files:**
- Create: `.github/dependabot.yml`

- [ ] **Step 1: Create the config**

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

- [ ] **Step 2: Verify YAML**

```bash
python -c "import yaml; yaml.safe_load(open('.github/dependabot.yml'))" && echo OK
```
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add .github/dependabot.yml
git commit -m "ci: add Dependabot for pip + github-actions ecosystems (weekly)"
```

---

## Task 4: docforge — push and confirm CI runs green

**Files:** None (git + GitHub UI).

- [ ] **Step 1: Push docforge branch / master**

If you're working on master directly, push:
```bash
cd /e/docforge
git push origin master
```

If on a feature branch:
```bash
git push -u origin <branch-name>
```

- [ ] **Step 2: Watch the CI run**

Open `https://github.com/GranatenUdo/docforge/actions` in a browser. The workflow named "CI" should trigger on the push (or on your PR).

Expected result:
- `lint` — green
- `test` — green

- [ ] **Step 3: If red, fix and push**

Likely failure modes + fixes:
- **`ruff check` reports an issue**: run `ruff check docforge tests` locally; fix the reported issue; commit.
- **`ruff format --check` reports a diff**: Task 1 should have prevented this. If it happens on a file added/modified between Task 1 and Task 2, run `ruff format docforge tests`, commit.
- **`pytest` fails**: reproduce locally with `pytest -m "not integration"`; fix.
- **`pip install` fails**: check `pyproject.toml` dev deps resolved; unlikely issue.

- [ ] **Step 4: No commit — verification only.**

---

## Task 5: knowledge-hub validator script

**Files:**
- Create: `knowledge-hub/rag/scripts/validate_sources.py`

- [ ] **Step 1: Create the script**

```python
"""Validate sources.yml + teams.yml well-formedness and tag vocabulary.

Called by the ADO pipeline on PR touching rag/*.yml. Fails non-zero on
any issue so the PR can't merge red. Also runnable locally:
    python rag/scripts/validate_sources.py
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

- [ ] **Step 2: Run against current sources.yml + teams.yml**

```bash
cd /e/knowledge-hub
python rag/scripts/validate_sources.py
```
Expected: `OK: 72 sources validated against N-tag vocabulary` where N matches the current teams.yml entry count (today: 4 — ccl, cloud, org, cross-team).

- [ ] **Step 3: Test the failure path by temporarily breaking a tag**

```bash
# Introduce an invalid tag temporarily
python -c "
import yaml
with open('rag/sources.yml') as f: data = yaml.safe_load(f)
data['sources'][0]['tags'] = ['bogus-tag']
with open('rag/sources.yml', 'w') as f: yaml.dump(data, f)
"

python rag/scripts/validate_sources.py
echo "exit: $?"
```
Expected: stderr reports `unknown tags ['bogus-tag']`, exit code `1`.

- [ ] **Step 4: Restore sources.yml**

```bash
git checkout rag/sources.yml
python rag/scripts/validate_sources.py
```
Expected: back to `OK: 72 sources validated...`.

- [ ] **Step 5: Run ruff format on the new file**

Even though knowledge-hub has no CI enforcing ruff, keeping the new Python file format-clean:
```bash
cd /e/docforge
source .venv/Scripts/activate
ruff format /e/knowledge-hub/rag/scripts/validate_sources.py
```

- [ ] **Step 6: Commit**

```bash
cd /e/knowledge-hub
git add rag/scripts/validate_sources.py
git commit -m "ci(rag): add sources.yml + teams.yml tag validator"
```

---

## Task 6: knowledge-hub ADO pipeline YAML

**Files:**
- Create: `knowledge-hub/.pipelines/config-validation.yml`

- [ ] **Step 1: Create the pipeline file**

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

- [ ] **Step 2: Verify YAML**

```bash
python -c "import yaml; yaml.safe_load(open('.pipelines/config-validation.yml'))" && echo OK
```
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
cd /e/knowledge-hub
git add .pipelines/config-validation.yml
git commit -m "ci(rag): add ADO pipeline for sources.yml validation"
```

---

## Task 7: knowledge-hub — push and register pipeline in ADO

**Files:** None (git + ADO UI).

- [ ] **Step 1: Push**

```bash
cd /e/knowledge-hub
git push origin master
```

- [ ] **Step 2: Register the pipeline in ADO**

Manual UI step — ADO doesn't auto-register YAML pipelines:

1. Navigate to https://dwcr.visualstudio.com/CloudCL/_build
2. Click "New pipeline"
3. Choose "Azure Repos Git"
4. Select the `knowledge-hub` repo
5. Choose "Existing Azure Pipelines YAML file"
6. Select `/pipelines/config-validation.yml` (ADO's "Path" picker should offer it)
7. Click "Save" (not "Run" — the trigger rules will start it on the next matching commit)

Optionally rename the pipeline in ADO UI to something like "knowledge-hub / config-validation" for clarity.

- [ ] **Step 3: Trigger a test run**

Make a trivial change to `rag/sources.yml` (e.g., reorder two entries), commit + push to a feature branch, open PR. The pipeline should run automatically.

Alternatively, run once manually from the ADO UI ("Run pipeline" button on the pipeline detail page).

Expected: green build, log reports `OK: 72 sources validated against 4-tag vocabulary`.

- [ ] **Step 4: No commit — verification + registration.**

---

## Task 8: Branch protection on docforge master (GitHub UI)

**Files:** None (GitHub repo settings UI).

- [ ] **Step 1: Configure branch protection**

1. Navigate to https://github.com/GranatenUdo/docforge/settings/branches
2. Click "Add branch protection rule"
3. Branch name pattern: `master`
4. Check: **Require a pull request before merging**
   - (Solo maintainer — "Require approvals" can be 0 or 1; 0 lets you self-merge, 1 requires another reviewer you don't have. Set to 0.)
5. Check: **Require status checks to pass before merging**
   - Search for and add: `lint`, `test`
   - Optionally: **Require branches to be up to date before merging** (prevents stale PRs merging)
6. Check: **Do not allow bypassing the above settings** (applies rules to admins too)
7. Uncheck: **Allow force pushes**, **Allow deletions**
8. Click "Create" (or "Save changes" if updating)

- [ ] **Step 2: Verify protection by attempting a prohibited action**

```bash
cd /e/docforge
git commit --allow-empty -m "test: verify branch protection"
git push origin master
```

Expected: push rejected with a message like:
```
remote: error: GH006: Protected branch update failed for refs/heads/master.
remote: Required status check "lint" is expected.
```

If accepted: branch protection isn't active; revisit Step 1.

- [ ] **Step 3: Discard the test commit**

```bash
git reset --hard HEAD~1
```

- [ ] **Step 4: No commit — verification only.**

---

## Task 9: Final verification

- [ ] **Step 1: docforge CI gate is active**

Open https://github.com/GranatenUdo/docforge — README shield or the latest commit should show a green check from the CI workflow.

- [ ] **Step 2: Dependabot is enabled**

Open https://github.com/GranatenUdo/docforge/security/dependabot — should show Dependabot status as enabled, with a weekly schedule. First batch of PRs (if any deps need updates) arrives next Monday.

- [ ] **Step 3: knowledge-hub pipeline is registered + green**

Open the ADO pipeline URL from Task 7. Latest run should be green.

- [ ] **Step 4: Summary commit check**

```bash
cd /e/docforge && git log --oneline origin/master..master 2>&1 | wc -l
cd /e/knowledge-hub && git log --oneline origin/master..master 2>&1 | wc -l
```

Both should print `0` (everything pushed).

- [ ] **Step 5: No commit — summary.**

---

## Done

docforge has PR-blocking CI (lint + test). knowledge-hub has config validation. Dependabot starts its weekly cadence on Monday.

**What the maturity assessment (Spec D) can now claim:**
- Quality L2 → L3 — PRs gated on ruff + pytest + coverage ≥60%
- Security L2 → L2+ — Dependabot supply-chain monitoring in place (full L3 waits for Spec C3 threat model + log privacy policy)

**Follow-up items tracked, not executed here:**
- After first Dependabot PR arrives, review and merge. If `pyproject.toml` upper bounds block minor updates, loosen them.
- Consider adding `ruff format` to pre-commit if you find the CI feedback loop slow.
- knowledge-hub pipeline can later be extended to run `docforge init-db --dry-run` on schema changes if the schema migrations become more complex (Spec C4 or later).
