# docforge v0.3 Phase 2 — Test-Depth Bedrock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the testing safety net the Phase 4 async/sidecar refactor will need — gate `pytest -m integration` on every PR via a new CI job, and add a real-model `Embedder` smoke test that exercises the contract the FakeEmbedder mocks.

**Architecture:** A new `integration` job in `.github/workflows/ci.yml` runs the existing testcontainer-based integration suite (`tests/integration/`) on `ubuntu-latest` (Docker is preinstalled, so testcontainers-python works out of the box). A new test file `tests/integration/test_embedder_real_model.py` loads the ungated `sentence-transformers/all-MiniLM-L6-v2` (384-d, ~80 MB, no HF token needed) and asserts on dimension correctness, non-degeneracy, and the dimension-guard contract added in Phase 1.

**Tech Stack:** GitHub Actions, pytest, testcontainers-python, sentence-transformers, pgvector.

**Spec mapping:**

| Spec item | Plan task |
|---|---|
| Integration tests in CI (Finding 2A) | Task 1 |
| Real-model embedder smoke test (Finding 2C) | Task 2 |
| mypy + bandit (Optional 2D) | **Deferred** — separate phase or one-off PR; not Phase 2's goal |

**Out-of-band housekeeping (not a code change, listed at the bottom):**

After this PR merges, the new `integration` check shows up in the GitHub UI. The repository's branch-protection rule for `master` currently requires `lint` + `test` (the "2 of 2 required status checks" the v0.3 push attempt earlier surfaced). Add `integration` as a third required check via the GitHub UI so future PRs cannot bypass the new safety net.

---

### Task 1: Add `integration` job to CI

**Files:**
- Modify: `.github/workflows/ci.yml` — append a new job after the existing `test` job.

- [ ] **Step 1: Verify integration tests pass locally (Docker required)**

Run from `E:/docforge`:

```bash
python -m pytest -m integration --tb=short 2>&1 | tail -10
```

Expected: 10 tests pass (the existing testcontainer-based suite). The first run takes ~30 s because testcontainers pulls `pgvector/pgvector:pg16` and runs the schema. Subsequent runs reuse the cached image, ~10 s.

If Docker isn't running locally, you'll see `DockerException: Error while fetching server API version`. That's only a local-environment problem — CI's `ubuntu-latest` has Docker preinstalled. If you want to skip this step locally, proceed to Step 2 and trust CI to validate.

- [ ] **Step 2: Edit `.github/workflows/ci.yml` — add the integration job**

The current file ends with the `test` job:

```yaml
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'
          cache: 'pip'
      - run: pip install -e ".[dev,entra]"
      - run: pytest -m "not integration"
```

Append a new `integration` job after it (keep the existing `test` job unchanged so the unit suite stays at the ~30 s feedback target):

```yaml
  integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'
          cache: 'pip'
      - name: Cache HuggingFace models
        uses: actions/cache@v4
        with:
          path: ~/.cache/huggingface
          key: hf-${{ runner.os }}-all-minilm-l6-v2
      - run: pip install -e ".[dev,entra]"
      - run: pytest -m integration
```

The deliberate split between `test` (`-m "not integration"`, ~30 s, fast
feedback) and `integration` (`-m integration`, ~3 min, real Postgres + real
model load from Task 2) keeps the unit job snappy while the heavier checks
run alongside.

The HuggingFace cache step uses a static key (`hf-<os>-all-minilm-l6-v2`)
because the model is immutable — only invalidate by changing the key when
the smoke test references a different model. Saves ~10 s per run after the
first.

- [ ] **Step 3: Run lint locally to confirm no spillover**

```bash
python -m ruff check src/docforge tests && python -m ruff format --check src/docforge tests
```

Expected: clean (this task only touches `.github/workflows/ci.yml`, which ruff doesn't check, but confirm in case of stale state).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "$(cat <<'EOF'
ci: add integration job that runs pytest -m integration

Phase 2 of v0.3 hardening — get the testcontainer-based integration
suite (Postgres + pgvector) gating every PR, so the Phase 4 async and
sidecar refactor has a real safety net beyond the mock-driven unit
suite.

Kept the existing "test" job (-m "not integration") untouched so the
unit feedback loop stays at ~30 s. Integration runs in parallel; both
jobs use ubuntu-latest, which has Docker preinstalled for
testcontainers.

Branch protection on master will need the new "integration" check
added to the required-checks list once this lands; that's a
GitHub-UI step, not part of this PR.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Real-model `Embedder` smoke test + marker description update

**Files:**
- Create: `tests/integration/test_embedder_real_model.py`
- Modify: `pyproject.toml` — update the `integration` marker description, since the marker now covers both Docker-based and network-based tests.

The test file is auto-marked `@pytest.mark.integration` by
`tests/integration/conftest.py:18-22`, so it runs in the new integration CI
job from Task 1 (and is gated out of the unit `test` job).

- [ ] **Step 1: Create the smoke test file**

Write the new file at `tests/integration/test_embedder_real_model.py` with
this exact content. A module-scoped fixture loads the model once for the
two tests that share it; the third test (mismatch case) constructs its own
Embedder because it needs a different `expected_dimensions`.

```python
"""Real-model smoke test for the Embedder.

Loads the ungated `sentence-transformers/all-MiniLM-L6-v2` (384-d, ~80 MB)
and asserts on the contract the unit-test FakeEmbedder mocks:

- the loaded model reports the dimension we expect,
- two distinct texts produce two distinct vectors,
- the dimension guard from Phase 1 fires when config disagrees with the
  loaded model.

Catches dim-drift and degenerate-embedding bugs that the mock-based unit
suite (`tests/unit/test_embedder.py`) cannot — without depending on the
HF-gated EmbeddingGemma. No HF token required.
"""

from __future__ import annotations

import pytest

from docforge.processors.embedder import Embedder

UNGATED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@pytest.fixture(scope="module")
def real_embedder() -> Embedder:
    """Loaded once per module — model load is the expensive part (~5 s after HF cache).

    Constructed with expected_dimensions=384 so the guard is exercised on the
    happy path. The mismatch test below builds its own Embedder because it
    needs a different expected_dimensions.
    """
    return Embedder(UNGATED_MODEL, expected_dimensions=384)


def test_real_model_loads_with_expected_dimension(real_embedder: Embedder) -> None:
    """The 384-d ungated model loads and reports dim=384."""
    assert real_embedder.dimensions == 384
    assert real_embedder.model_name == UNGATED_MODEL


def test_real_model_produces_different_embeddings_for_different_text(
    real_embedder: Embedder,
) -> None:
    """Non-degenerate: two distinct texts get two distinct 384-d vectors."""
    a = real_embedder.embed_query("hello")
    b = real_embedder.embed_query("world")
    assert a != b
    assert len(a) == 384
    assert len(b) == 384


def test_real_model_dimension_guard_fires_on_mismatch() -> None:
    """If config requires 768 but the loaded model is 384, the Phase-1 guard raises."""
    with pytest.raises(RuntimeError, match="dimension mismatch"):
        Embedder(UNGATED_MODEL, expected_dimensions=768)
```

- [ ] **Step 1b: Update the `integration` marker description in `pyproject.toml`**

The current marker description claims "requires Docker (pgvector container)"
— accurate before this task, inaccurate after (the new tests need network,
not Docker). Update the line in `pyproject.toml`:

Replace:

```toml
markers = [
    "integration: requires Docker (pgvector container)",
]
```

with:

```toml
markers = [
    "integration: tests requiring real external resources (Docker for Postgres, network for embedding model)",
]
```

- [ ] **Step 2: Run the new tests locally — verify they pass**

```bash
python -m pytest tests/integration/test_embedder_real_model.py -v --tb=short 2>&1 | tail -15
```

Expected: 3 tests pass. First run downloads ~80 MB from Hugging Face (~10 s
on a fast connection); subsequent runs reuse `~/.cache/huggingface/`. With
the module-scoped fixture, the model is loaded twice in total per run
(once for the fixture shared by tests 1 + 2, once more for test 3's
own `Embedder`). After the HF cache is warm, total run time is ~5–10 s.

If `test_real_model_loads_with_expected_dimension` fails with the loaded model reporting a different dimension, the model on Hugging Face has changed contract — investigate before relaxing the assertion.

If `test_real_model_produces_different_embeddings_for_different_text` fails (vectors equal), something is broken in the embedder pipeline (e.g. normalisation collapsed both vectors to zero, tokenizer pre-pre-processing returned the same tokens). Don't relax — fix.

- [ ] **Step 3: Verify the full integration suite still passes**

```bash
python -m pytest -m integration --tb=short 2>&1 | tail -10
```

Expected: 13 tests pass (the 10 pre-existing testcontainer-based tests + the 3 new real-model smokes).

- [ ] **Step 4: Run lint to keep CI green**

```bash
python -m ruff check src/docforge tests && python -m ruff format --check src/docforge tests
```

Expected: clean. If `ruff format --check` complains about the new file, run `python -m ruff format tests/integration/test_embedder_real_model.py` and re-stage.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_embedder_real_model.py pyproject.toml
git commit -m "$(cat <<'EOF'
test(embedder): add real-model smoke test using all-MiniLM-L6-v2

Mock-based unit tests can't catch dim-drift or degenerate-embedding
bugs because the FakeEmbedder is deterministic by construction. This
real-model smoke uses the ungated 384-d all-MiniLM-L6-v2 and asserts:

- the loaded model's dimension matches expectations,
- two distinct texts produce two distinct 384-d vectors,
- the Phase-1 dimension guard raises on mismatch.

No HF token needed. Auto-marked @pytest.mark.integration via the
tests/integration/conftest.py auto-marker, so it runs in the
integration CI job (Task 1) and is gated out of the fast unit job.

Also updates the integration marker description in pyproject.toml —
the marker now covers both Docker-based (testcontainers/pgvector) and
network-based (HF model) tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Branch-protection housekeeping (post-merge, manual GitHub UI)

After the Phase 2 PR merges, add `integration` to the list of required status checks for the `master` branch.

- [ ] **Step 1: Open repo settings → Branches → master → Edit rule**

Navigate to `https://github.com/GranatenUdo/docforge/settings/branches`. The `master` branch protection rule should already exist (the v0.3 push attempt earlier surfaced "2 of 2 required status checks").

- [ ] **Step 2: Add `integration` to "Require status checks to pass before merging"**

In the "Status checks that are required" search box, type `integration` and select it from the suggestions. Save the rule.

- [ ] **Step 3: Verify by opening any subsequent PR**

The PR's checks panel should now show `lint`, `test`, **and** `integration` as required. The PR cannot merge until `integration` passes.

This step is the closing of the loop: without it, the integration job runs but PRs can still be merged before it finishes — defeating the purpose of Phase 2.
