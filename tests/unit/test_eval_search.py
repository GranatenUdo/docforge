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
