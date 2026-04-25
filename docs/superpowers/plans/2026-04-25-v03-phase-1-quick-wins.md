# docforge v0.3 Phase 1 — Quick Wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the four Phase 1 quick-wins from
`docs/superpowers/specs/2026-04-25-v03-hardening-design.md` — README threat-model
link, dependency upper bounds + Gemma license note, and the Embedder dimension
guard — as small, low-risk PRs that prepare the foundation for Phases 2–5.

**Architecture:** Three independent code-touching tasks; each is its own commit.
Plus one manual pre-Phase-4 prep step (capture an eval baseline against the
maintainer's deployment) that does not produce code changes — described at the
bottom.

**Tech Stack:** Python 3.12+, pytest, ruff, pydantic-settings, sentence-transformers.

**Spec mapping:**

| Spec item | Plan task |
|---|---|
| README → threat-model link (Finding 6) | Task 1 |
| Dependency upper bounds + Gemma license note (Finding 7) | Task 2 |
| Embedder dimension guard (Finding 8 partial) | Task 3 |
| Capture pre-refactor eval baseline (Finding 2 free pre-step) | Manual prep — see "Pre-Phase-4 manual prep" |

**Spec-text correction:** the spec says
`model.get_sentence_embedding_dimension()`, but the existing codebase uses the
shorter alias `model.get_embedding_dimension()` (see
`src/docforge/processors/embedder.py:29,42`). The plan matches the codebase.

---

### Task 1: Add threat-model link to README "wrong choice" section

**Files:**
- Modify: `README.md` (one inserted paragraph, between the last bullet of
  "When docforge is the wrong choice" and the "## Quick Start" heading).

- [ ] **Step 1: Apply the README edit**

In `README.md`, locate the last bullet of the "When docforge is the wrong choice"
section. The current text ends with:

```markdown
- You need multilingual search evaluated → EmbeddingGemma is multilingual, but docforge has no eval coverage on non-English corpora yet.

## Quick Start
```

Replace that two-line region with:

```markdown
- You need multilingual search evaluated → EmbeddingGemma is multilingual, but docforge has no eval coverage on non-English corpora yet.

For the full trust model, accepted risks, and assumptions docforge makes about its operating environment, see [`docs/threat-model.md`](docs/threat-model.md).

## Quick Start
```

- [ ] **Step 2: Verify the link target exists**

Run: `ls docs/threat-model.md`
Expected: file is listed (no "No such file" error).

- [ ] **Step 3: Verify the README still renders**

Run: `python -c "import pathlib; t = pathlib.Path('README.md').read_text(encoding='utf-8'); assert 'docs/threat-model.md' in t; print('OK')"`
Expected: prints `OK`.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs: link threat model from README "wrong choice" section

External adopters comparing docforge against alternatives benefit from
the threat model's explicit trust assumptions. Surface it from the
competitive section, not just docs/.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Add dependency upper bounds + Gemma license note

**Files:**
- Modify: `pyproject.toml` (lines 12–26 dependencies; lines 39–51
  optional-dependencies — add `,<NEXT_MAJOR.0` to each constraint).
- Modify: `README.md` (insert a new "## License compatibility" section between
  the existing "## License" and "## Credits" headings).

- [ ] **Step 1: Edit `pyproject.toml` — runtime dependencies**

Replace the `dependencies = [...]` block (lines 12–26) with:

```toml
dependencies = [
    "typer>=0.12,<1.0",
    "asyncpg>=0.30,<1.0",
    "httpx>=0.27,<1.0",
    "pydantic>=2.9,<3.0",
    "pydantic-settings>=2.6,<3.0",
    "beautifulsoup4>=4.12,<5.0",
    "sentence-transformers>=5.0,<6.0",
    "pgvector>=0.3,<1.0",
    "pyyaml>=6.0,<7.0",
    "fastmcp>=2.0,<3.0",
    "fastapi>=0.115,<1.0",
    "uvicorn>=0.34,<1.0",
    "numpy>=1.26,<3.0",
]
```

Rationale for each ceiling: floor-major + 1, matching the strict-major
convention the spec calls for. `numpy>=1.26,<3.0` covers both 1.x (current
floor) and 2.x (already released and works in our test suite); 3.x will be
re-tested explicitly when it ships.

- [ ] **Step 2: Edit `pyproject.toml` — optional dependencies**

Replace the `[project.optional-dependencies]` block (lines 38–51) with:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0,<9.0",
    "pytest-asyncio>=0.24,<1.0",
    "pytest-cov>=7.0,<8.0",
    "ruff>=0.8,<1.0",
    "testcontainers[postgres]>=4.0,<5.0",
]
entra = [
    "fastapi-azure-auth>=5.0,<6.0",
    "azure-identity>=1.19,<2.0",
    # aiohttp is required by azure-identity.aio's async pipeline
    "aiohttp>=3.10,<4.0",
]
```

- [ ] **Step 3: Verify dependencies still resolve**

Run: `pip install -e ".[dev,entra]" --dry-run 2>&1 | tail -20`
Expected: no `ResolutionImpossible` errors. Some "Would install" lines listing
existing satisfied versions is fine.

If a real conflict surfaces (rare on a working venv), narrow the relevant
ceiling — e.g., if `sentence-transformers` 6.x doesn't exist yet but we are on
5.1, `<6.0` is correct; if a transitive constraint forces a downgrade, log it
as a follow-up rather than relaxing the ceiling here.

- [ ] **Step 4: Add the License compatibility section to README**

In `README.md`, find the existing structure:

```markdown
## License

MIT. See [LICENSE](LICENSE).

## Credits
```

Replace those four lines with:

```markdown
## License

MIT. See [LICENSE](LICENSE).

## License compatibility

docforge is MIT-licensed; the default embedding model,
[EmbeddingGemma-300M](https://huggingface.co/google/embeddinggemma-300m), is
distributed under the [Gemma Terms of Use](https://ai.google.dev/gemma/terms),
which restrict harmful use and building products that compete with Gemma. Swap
to a permissively-licensed alternative via `embedding_model` in `docforge.yml`
if those constraints don't fit your use case (see
[microsite FAQ — Can I use a different embedding model?](https://GranatenUdo.github.io/docforge/faq/#can-i-use-a-different-embedding-model)).

## Credits
```

- [ ] **Step 5: Run the full unit test suite to confirm no regressions**

Run: `python -m pytest -m "not integration" -q --no-header --tb=short 2>&1 | tail -10`
Expected: `154 passed, 10 deselected` (or higher pass count if more tests
landed since this plan was written). No failures.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml README.md
git commit -m "$(cat <<'EOF'
chore: upper-bound major versions for runtime + dev deps; document Gemma license

Dependabot already covers minor/patch CVE risk. Adding strict-major ceilings
prevents fresh-install adopters from pulling an untested next-major version
of fastapi, pydantic, sentence-transformers, etc.

Surfaces the Gemma license restriction (no harmful use, no Gemma-derivative
competitors) in a dedicated README section so adopters considering
redistribution don't have to dig into the threat model to find it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Embedder dimension guard + caller updates

**Files:**
- Modify: `src/docforge/processors/embedder.py` — add an `expected_dimensions`
  parameter and a post-load assertion.
- Modify: `tests/unit/test_embedder.py` — add four new tests covering the
  guard's behavior.
- Modify: `src/docforge/api.py:90`, `src/docforge/mcp_server.py:46-48`,
  `src/docforge/ingest.py:54`, `src/docforge/cli.py:220` — pass
  `expected_dimensions=settings.embedding_dimensions` at every Embedder
  construction site.

- [ ] **Step 1: Write the failing tests**

Append four new test methods to the `TestEmbedderInit` class in
`tests/unit/test_embedder.py` (after the existing
`test_passes_none_when_no_token_available` method, before the closing of the
class):

```python
    def test_raises_when_loaded_dim_does_not_match_expected(self):
        """Guard fires when configured embedding_dimensions disagrees with model."""
        fake = _fake_st_model(dim=384)
        with patch("sentence_transformers.SentenceTransformer", return_value=fake):
            from docforge.processors.embedder import Embedder

            with pytest.raises(RuntimeError, match="dimension mismatch"):
                Embedder("primary/model", hf_token="tok", expected_dimensions=768)

    def test_loads_when_loaded_dim_matches_expected(self):
        """No guard fire when expected dim matches model."""
        fake = _fake_st_model(dim=768)
        with patch("sentence_transformers.SentenceTransformer", return_value=fake):
            from docforge.processors.embedder import Embedder

            emb = Embedder("primary/model", hf_token="tok", expected_dimensions=768)
            assert emb.dimensions == 768

    def test_no_check_when_expected_dim_omitted(self):
        """expected_dimensions defaults to None — guard skipped, backwards compat."""
        fake = _fake_st_model(dim=384)
        with patch("sentence_transformers.SentenceTransformer", return_value=fake):
            from docforge.processors.embedder import Embedder

            emb = Embedder("primary/model", hf_token="tok")
            # Loads even though dim differs from EmbeddingGemma's 768 — no
            # expected_dim passed, so the guard is dormant.
            assert emb.dimensions == 384

    def test_guard_fires_after_fallback_with_wrong_dim(self):
        """Fallback model has dim 384; if config expects 768, guard fires."""
        fake_fallback = _fake_st_model(dim=384)
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("primary exploded")
            return fake_fallback

        with patch("sentence_transformers.SentenceTransformer", side_effect=side_effect):
            from docforge.processors.embedder import Embedder

            with pytest.raises(RuntimeError, match="dimension mismatch"):
                Embedder("primary/broken", expected_dimensions=768)
```

- [ ] **Step 2: Run the new tests — verify they fail**

Run: `python -m pytest tests/unit/test_embedder.py::TestEmbedderInit -v --tb=short 2>&1 | tail -30`

Expected: the four new tests fail because `Embedder` does not yet accept
`expected_dimensions`. The pre-existing five tests still pass.

The failure message should look like
`TypeError: __init__() got an unexpected keyword argument 'expected_dimensions'`
or — for `test_no_check_when_expected_dim_omitted` — pass already (since it
doesn't pass the new arg). That single test passing on red is fine.

- [ ] **Step 3: Implement the guard in `embedder.py`**

Replace the current `Embedder.__init__` body
(`src/docforge/processors/embedder.py` lines 18–53) with:

```python
    def __init__(
        self,
        model_name: str = "google/embeddinggemma-300m",
        hf_token: str = "",
        expected_dimensions: int | None = None,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        # Use provided token, fall back to environment variable
        if not hf_token:
            hf_token = os.environ.get("HF_TOKEN", "")

        try:
            logger.info("Loading embedding model: %s", model_name)
            self._model = SentenceTransformer(model_name, token=hf_token or None)
            self.model_name = model_name
            self.dimensions = self._model.get_embedding_dimension()
            logger.info("Model loaded: %s (%d dimensions)", self.model_name, self.dimensions)
        except Exception:
            fallback = "sentence-transformers/all-MiniLM-L6-v2"
            logger.warning(
                "Failed to load %s, falling back to %s",
                model_name,
                fallback,
                exc_info=True,
            )
            try:
                self._model = SentenceTransformer(fallback)
                self.model_name = fallback
                self.dimensions = self._model.get_embedding_dimension()
                logger.info(
                    "Fallback model loaded: %s (%d dimensions)",
                    self.model_name,
                    self.dimensions,
                )
            except Exception:
                logger.error("Failed to load fallback model %s", fallback, exc_info=True)
                raise RuntimeError(
                    f"No embedding model available. "
                    f"Primary ({model_name}) and fallback ({fallback}) both failed."
                )

        # Dimension guard. When the caller supplies expected_dimensions (e.g.
        # from settings.embedding_dimensions), verify the loaded model agrees.
        # Catches the silent-mismatch case where the fallback model loads with a
        # different dimensionality than the schema expects.
        if expected_dimensions is not None and self.dimensions != expected_dimensions:
            raise RuntimeError(
                f"Embedding dimension mismatch: model {self.model_name!r} reports "
                f"{self.dimensions}-d, but config requires {expected_dimensions}-d. "
                f"Either change embedding_model in docforge.yml to a "
                f"{expected_dimensions}-d model, or update embedding_dimensions "
                f"and run a schema migration to vector({self.dimensions})."
            )
```

- [ ] **Step 4: Run the embedder tests — verify they all pass**

Run: `python -m pytest tests/unit/test_embedder.py -v --tb=short 2>&1 | tail -30`

Expected: every test in `tests/unit/test_embedder.py` passes (existing 9-ish
+ the 4 new ones).

- [ ] **Step 5: Update each caller to pass `expected_dimensions`**

There are four call sites. Each gets the same change shape: add
`expected_dimensions=settings.embedding_dimensions` to the `Embedder(...)`
construction.

In `src/docforge/api.py`, replace line 90:

```python
    _embedder = Embedder(settings.embedding_model, hf_token=settings.hf_token.get_secret_value())
```

with:

```python
    _embedder = Embedder(
        settings.embedding_model,
        hf_token=settings.hf_token.get_secret_value(),
        expected_dimensions=settings.embedding_dimensions,
    )
```

In `src/docforge/mcp_server.py`, replace lines 46–48:

```python
        _embedder = Embedder(
            settings.embedding_model, hf_token=settings.hf_token.get_secret_value()
        )
```

with:

```python
        _embedder = Embedder(
            settings.embedding_model,
            hf_token=settings.hf_token.get_secret_value(),
            expected_dimensions=settings.embedding_dimensions,
        )
```

In `src/docforge/ingest.py`, replace line 54:

```python
    embedder = Embedder(settings.embedding_model, hf_token=settings.hf_token.get_secret_value())
```

with:

```python
    embedder = Embedder(
        settings.embedding_model,
        hf_token=settings.hf_token.get_secret_value(),
        expected_dimensions=settings.embedding_dimensions,
    )
```

In `src/docforge/cli.py`, replace line 220:

```python
        embedder = Embedder(settings.embedding_model, hf_token=settings.hf_token.get_secret_value())
```

with:

```python
        embedder = Embedder(
            settings.embedding_model,
            hf_token=settings.hf_token.get_secret_value(),
            expected_dimensions=settings.embedding_dimensions,
        )
```

- [ ] **Step 6: Run the full unit suite**

Run: `python -m pytest -m "not integration" -q --no-header --tb=short 2>&1 | tail -15`

Expected: `158 passed, 10 deselected` (the 154 pre-existing + the 4 new
embedder tests). No failures, no errors.

If anything fails, the most likely culprit is a caller test that mocks
`Embedder` without accommodating the new kwarg. Fix the test to include
`expected_dimensions` in the mock's allowed kwargs (the `MagicMock`-based fakes
in `test_api.py` and `test_auth.py` should not need changes; they patch
`Embedder` entirely).

- [ ] **Step 7: Run lint to keep CI green**

Run: `ruff check src/docforge tests && ruff format --check src/docforge tests`
Expected: no errors, no formatting violations. If `ruff format --check`
disagrees with your indentation on the multiline `Embedder(...)` calls, run
`ruff format src/docforge tests` to auto-fix and re-stage.

- [ ] **Step 8: Commit**

```bash
git add src/docforge/processors/embedder.py tests/unit/test_embedder.py src/docforge/api.py src/docforge/mcp_server.py src/docforge/ingest.py src/docforge/cli.py
git commit -m "$(cat <<'EOF'
feat(embedder): add dimension guard + thread expected_dimensions through callers

Catches the silent-mismatch case where the fallback model loads with a
different dim than the schema expects. Raises RuntimeError with a clear
remediation message ("change embedding_model, or migrate the schema") instead
of letting pgvector reject the eventual INSERT with a confusing error.

Backwards-compat: expected_dimensions defaults to None (guard dormant).
Callers in api.py, mcp_server.py, ingest.py, and cli.py now pass
settings.embedding_dimensions explicitly.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Pre-Phase-4 manual prep — capture eval baseline

This is **not a code change** and not part of the Phase 1 PR. It is a one-time
operator activity that the maintainer should perform after Phase 1 ships and
before Phase 4 work begins, to capture a reference recall@k / MRR snapshot of
the v0.2.x architecture against which Phase 5's regression gate will compare.

- [ ] **Step 1: Identify your ground-truth YAML**

This file lives in your deployment's own state, not in docforge. Confirm its
path. It should follow the format in
`src/docforge/scripts/README.md#ground-truth-format`.

- [ ] **Step 2: Run the eval harness against current production**

```bash
python -m docforge.scripts.eval_search \
  --api-url https://<your-production-api> \
  --ground-truth /path/to/ground_truth.yml \
  --user <your-name> --team <your-team> --area <your-area> \
  --audience api://<your-app-id> \
  --k 5 \
  > eval-baseline-v0.2.x.txt
```

- [ ] **Step 3: Stamp the report**

Edit `eval-baseline-v0.2.x.txt` to prepend three lines:

```text
# docforge eval baseline — v0.2.x architecture
# Captured: <today's date>
# docforge git SHA: <output of `git rev-parse HEAD`>
```

- [ ] **Step 4: Save it where Phase 5 will find it**

Store the file in your deployment's eval directory (alongside the
ground_truth.yml). Phase 5's plan will reference it explicitly when wiring the
baseline-comparison gate into CI; until then, it is reference material only.

There is no commit step for this prep — the file does not belong in the public
docforge repo (the ground-truth YAML it depends on is deployment-specific).
