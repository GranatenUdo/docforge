"""Ranking helpers — pure Python mirror of the boost formula in search SQL."""

from __future__ import annotations


def compute_boosted_score(
    similarity: float,
    source_tags: list[str],
    user_tags: list[str],
    tag_weight: float,
    org_weight: float,
) -> float:
    """Apply tag-overlap + org-tag boost to a similarity score.

    Formula mirrors the SQL used in mcp_server.py and api.py search queries.
    Kept in a pure function so the ranking math is unit-testable without SQL.
    """
    overlap = len(set(source_tags) & set(user_tags))
    has_org = "org" in source_tags
    return similarity * (1 + tag_weight * overlap + org_weight * (1 if has_org else 0))
