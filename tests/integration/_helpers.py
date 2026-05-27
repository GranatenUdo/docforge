"""Shared helpers for integration tests against the hybrid-search SQL.

Module-level helpers (not pytest fixtures) so they import cleanly via
`from _helpers import _vec, _insert_source, _insert_chunk`. The
`tests/integration/` directory is on sys.path by virtue of conftest.py
collection — sibling test files can import this directly.
"""

from __future__ import annotations

import numpy as np


def _vec(angle_rad: float) -> np.ndarray:
    """Deterministic 1024-dim unit vector at angle `angle_rad` in axes (0, 1).

    Two vectors at angles a and b have cosine distance 1 - cos(a - b):
        _vec(0.0) and _vec(0.0)       -> distance 0     (identical)
        _vec(0.0) and _vec(0.1)       -> distance ~0.005 (very close)
        _vec(0.0) and _vec(math.pi/2) -> distance 1     (orthogonal)
    """
    v = np.zeros(1024, dtype=np.float32)
    v[0] = float(np.cos(angle_rad))
    v[1] = float(np.sin(angle_rad))
    return v


async def _insert_source(conn, title: str, tags: list[str] | None = None) -> str:
    """Insert a sources row and return its UUID."""
    return await conn.fetchval(
        """
        INSERT INTO sources (type, url, title, source_identifier, status, tags,
                             content_hash, last_crawled_at)
        VALUES ('git_repo', $1, $2, $1, 'active', $3, 'h', now())
        RETURNING id
        """,
        f"file:///{title}",
        title,
        tags or [],
    )


async def _insert_chunk(conn, source_id: str, text: str, vec: np.ndarray) -> None:
    """Insert a chunk with a precomputed embedding vector."""
    await conn.execute(
        """
        INSERT INTO chunks (source_id, chunk_index, text, embedding, section_title)
        VALUES ($1, 0, $2, $3, NULL)
        """,
        source_id,
        text,
        vec,
    )
