"""Tests for docforge.ranking.compute_boosted_score."""

from __future__ import annotations

import pytest

from docforge.ranking import compute_boosted_score


class TestComputeBoostedScore:
    def test_no_overlap_is_identity(self):
        assert compute_boosted_score(
            similarity=0.8,
            source_tags=["other"],
            user_tags=["platform"],
            tag_weight=0.1,
        ) == pytest.approx(0.8)

    def test_one_overlap(self):
        assert compute_boosted_score(
            similarity=0.8,
            source_tags=["platform"],
            user_tags=["platform"],
            tag_weight=0.1,
        ) == pytest.approx(0.8 * 1.1)

    def test_two_overlap(self):
        assert compute_boosted_score(
            similarity=0.8,
            source_tags=["platform", "cloud"],
            user_tags=["platform", "cloud"],
            tag_weight=0.1,
        ) == pytest.approx(0.8 * 1.2)

    def test_org_tag_no_longer_boosts(self):
        # 'org' is just an ordinary tag now (the Organization team); with no
        # overlap against user_tags it must NOT change the score.
        assert compute_boosted_score(
            similarity=0.8,
            source_tags=["org"],
            user_tags=["platform"],
            tag_weight=0.1,
        ) == pytest.approx(0.8)

    def test_configurable_weight_honored(self):
        assert compute_boosted_score(
            similarity=1.0,
            source_tags=["platform"],
            user_tags=["platform"],
            tag_weight=0.5,
        ) == pytest.approx(1.5)

    def test_duplicate_tags_counted_once(self):
        assert compute_boosted_score(
            similarity=1.0,
            source_tags=["platform", "platform"],
            user_tags=["platform"],
            tag_weight=0.1,
        ) == pytest.approx(1.1)

    def test_empty_tags_is_identity(self):
        assert compute_boosted_score(
            similarity=0.9,
            source_tags=[],
            user_tags=[],
            tag_weight=0.1,
        ) == pytest.approx(0.9)

    def test_org_in_user_tags_boosts_normally(self):
        # 'org' is now an ordinary team tag (the Organization team): when it is
        # the user's team AND the source carries it, it boosts like any overlap.
        assert compute_boosted_score(
            similarity=0.8,
            source_tags=["org"],
            user_tags=["org"],
            tag_weight=0.1,
        ) == pytest.approx(0.8 * 1.1)
