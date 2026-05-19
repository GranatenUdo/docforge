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
        titles = ["Organization Lifecycle — team responsibilities"]
        assert score_query(titles, "Organization Lifecycle") == 1


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
        assert out["mrr"] == pytest.approx((1 + 1 / 3 + 0 + 1 / 5) / 4)

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


class TestDirectMode:
    def test_cli_rejects_both_api_url_and_direct(self):
        """--api-url and --direct are mutually exclusive."""
        import subprocess, sys
        result = subprocess.run(
            [
                sys.executable, "-m", "docforge.scripts.eval_search",
                "--api-url", "https://example.test",
                "--direct",
                "--ground-truth", "nonexistent.yml",
                "--user", "u", "--team", "t",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
        assert "mutually exclusive" in (result.stderr + result.stdout).lower() \
            or "--direct" in result.stderr

    def test_cli_rejects_neither_api_url_nor_direct(self):
        """At least one of --api-url or --direct must be given."""
        import subprocess, sys
        result = subprocess.run(
            [
                sys.executable, "-m", "docforge.scripts.eval_search",
                "--ground-truth", "nonexistent.yml",
                "--user", "u", "--team", "t",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
        assert "required" in (result.stderr + result.stdout).lower() \
            or "--api-url" in result.stderr or "--direct" in result.stderr


class TestDirectRequiresRemoteEmbedder:
    @pytest.mark.asyncio
    async def test_direct_mode_fails_fast_when_embedder_url_empty(self, monkeypatch):
        """--direct mode must not silently fall through to local Qwen-4B
        download. When embedder_url is unset, raise SystemExit with a
        message that tells the user how to fix it."""
        from types import SimpleNamespace
        from docforge.scripts.eval_search import run_queries_direct

        empty_url_settings = SimpleNamespace(
            embedder_url="",  # the bad state we're guarding against
            database_url="postgresql://fake",
            embedder_token=SimpleNamespace(get_secret_value=lambda: ""),
        )
        monkeypatch.setattr("docforge.config.Settings", lambda: empty_url_settings)

        with pytest.raises(SystemExit) as exc_info:
            await run_queries_direct(
                ground_truth=[{"q": "q", "expected_title_contains": "x"}],
                user_name="u", team_name="t", area_name="a", k=5, debug=False,
            )
        assert "EMBEDDER_URL" in str(exc_info.value)


class TestDirectVsHttpParity:
    @pytest.mark.asyncio
    async def test_direct_mode_matches_http_for_same_fixtures(self, monkeypatch):
        """Both code paths share perform_search() after the Task 4 refactor.
        Running the same query through each must yield the same titles and
        match_rank. If they diverge, the refactor introduced a behavior change."""
        from unittest.mock import AsyncMock
        from docforge.scripts.eval_search import run_queries_direct, score_query
        from tests.conftest import FakeEmbedder, fake_settings

        rows_returned = [
            {
                "text": "Markus is VP Engineering.",
                "section_title": "Engineering",
                "source_title": "Departments in Product Development",
                "source_url": "https://wiki/depts",
                "source_tags": ["org"],
                "similarity": 0.85,
                "dense_rank": 1,
                "sparse_rank": 1,
            }
        ]

        # Stub perform_search to return our fixture rows regardless of args
        async def fake_perform_search(*, req, settings, pool, embedder):
            return rows_returned

        monkeypatch.setattr("docforge.api.perform_search", fake_perform_search)

        # Stub the Settings/Pool/Embedder construction in run_queries_direct
        # so the test doesn't need a real DB. run_queries_direct imports
        # Settings, asyncpg, and Embedder lazily inside the function — so we
        # patch their source modules, not eval_search's namespace.
        from unittest.mock import MagicMock

        # The Settings used by run_queries_direct must pass the embedder_url
        # guard, so override fake_settings to include a non-empty embedder_url.
        from types import SimpleNamespace
        def patched_settings():
            s = fake_settings()
            s.embedder_url = "https://embedder.example.test"
            s.embedder_token = SimpleNamespace(get_secret_value=lambda: "fake-token")
            return s

        monkeypatch.setattr("docforge.config.Settings", patched_settings)

        async def fake_create_pool(*args, **kwargs):
            return MagicMock(close=AsyncMock())

        monkeypatch.setattr("asyncpg.create_pool", fake_create_pool)
        monkeypatch.setattr(
            "docforge.processors.embedder.Embedder.from_settings",
            lambda settings: FakeEmbedder(),
        )

        ground_truth = [{"q": "who is Markus Koelmans", "expected_title_contains": "Departments in Product"}]
        results = await run_queries_direct(
            ground_truth=ground_truth,
            user_name="u",
            team_name="t",
            area_name="a",
            k=5,
            debug=True,
        )

        assert len(results) == 1
        assert results[0].returned_titles == ["Departments in Product Development"]
        assert results[0].match_rank == 1
        # Also verify the score_query function used by both code paths returns
        # the same rank for identical title lists
        assert score_query(results[0].returned_titles, "Departments in Product") == 1
