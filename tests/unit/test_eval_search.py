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
