"""Tests for docforge.ranking.compute_boosted_score."""

from __future__ import annotations

import pytest

from docforge.ranking import compute_boosted_score


class TestComputeBoostedScore:
    def test_no_overlap_no_org_is_identity(self):
        assert compute_boosted_score(
            similarity=0.8,
            source_tags=["other"],
            user_tags=["platform"],
            tag_weight=0.1,
            org_weight=0.05,
        ) == pytest.approx(0.8)

    def test_one_overlap_no_org(self):
        assert compute_boosted_score(
            similarity=0.8,
            source_tags=["platform"],
            user_tags=["platform"],
            tag_weight=0.1,
            org_weight=0.05,
        ) == pytest.approx(0.8 * 1.1)

    def test_two_overlap_no_org(self):
        assert compute_boosted_score(
            similarity=0.8,
            source_tags=["platform", "cloud"],
            user_tags=["platform", "cloud"],
            tag_weight=0.1,
            org_weight=0.05,
        ) == pytest.approx(0.8 * 1.2)

    def test_zero_overlap_has_org(self):
        assert compute_boosted_score(
            similarity=0.8,
            source_tags=["org"],
            user_tags=["platform"],
            tag_weight=0.1,
            org_weight=0.05,
        ) == pytest.approx(0.8 * 1.05)

    def test_one_overlap_plus_org(self):
        assert compute_boosted_score(
            similarity=0.8,
            source_tags=["platform", "org"],
            user_tags=["platform"],
            tag_weight=0.1,
            org_weight=0.05,
        ) == pytest.approx(0.8 * 1.15)

    def test_configurable_weights_honored(self):
        assert compute_boosted_score(
            similarity=1.0,
            source_tags=["platform"],
            user_tags=["platform"],
            tag_weight=0.5,
            org_weight=0.0,
        ) == pytest.approx(1.5)

    def test_duplicate_tags_counted_once(self):
        assert compute_boosted_score(
            similarity=1.0,
            source_tags=["platform", "platform"],
            user_tags=["platform"],
            tag_weight=0.1,
            org_weight=0.0,
        ) == pytest.approx(1.1)

    def test_empty_tags_is_identity(self):
        assert compute_boosted_score(
            similarity=0.9,
            source_tags=[],
            user_tags=[],
            tag_weight=0.1,
            org_weight=0.05,
        ) == pytest.approx(0.9)
