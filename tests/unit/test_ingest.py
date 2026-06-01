"""Tests for docforge.ingest — the end-to-end ingest pipeline.

All heavy dependencies are mocked: the Embedder is replaced via the
fake_embedder fixture; asyncpg pool/connection are fakes; crawlers are
monkeypatched to return in-memory objects.
"""

from __future__ import annotations

import pytest

from docforge import ingest as ingest_mod
from docforge.ingest import _parse_markdown, _purge_orphans, ingest_all


class TestParseMarkdown:
    def test_parses_headings_and_body(self):
        content = "# Title\n\nIntro text.\n\n## Details\n\nBody text."
        sections = _parse_markdown(content)
        assert len(sections) == 2
        assert sections[0].title == "Title"
        assert "Intro text." in sections[0].text
        assert sections[0].level == 1
        assert sections[1].title == "Details"
        assert sections[1].level == 2

    def test_no_headings_produces_single_section_with_empty_title(self):
        sections = _parse_markdown("Just some paragraph text.")
        assert len(sections) == 1
        assert sections[0].title == ""
        assert "paragraph" in sections[0].text

    def test_empty_content_returns_empty(self):
        assert _parse_markdown("") == []

    def test_empty_section_body_dropped(self):
        sections = _parse_markdown("# A\n\n# B\n\nContent.")
        titles = [s.title for s in sections]
        assert "B" in titles
        assert all(s.text.strip() for s in sections)


class _Conn:
    def __init__(self, existing_hash=None):
        self.existing_hash = existing_hash
        self.inserted_sources = []
        self.inserted_chunks = []
        self.executed = []

    async def fetchval(self, query, *args):
        q = query.strip().lower()
        # Match INSERT ... RETURNING id specifically (avoids false positives
        # on strings like "source_identifier" which contain "source_id").
        if "returning id" in q:
            self.inserted_sources.append(args)
            return "fake-source-id"
        if q.startswith("select content_hash"):
            return self.existing_hash
        return None

    async def fetch(self, query, *args):
        return []

    async def execute(self, query, *args):
        self.executed.append(query)
        if "INSERT INTO chunks" in query:
            self.inserted_chunks.append(args)

    def transaction(self):
        return _Tx()


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None


class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return None


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _AcquireCtx(self._conn)


@pytest.mark.asyncio
async def test_ingest_all_with_empty_sources_list(tmp_path, monkeypatch, fake_embedder):
    sources_file = tmp_path / "sources.yml"
    sources_file.write_text("sources: []\n")

    conn = _Conn()

    async def fake_get_pool(url, **kwargs):
        return _FakePool(conn)

    monkeypatch.setattr(ingest_mod, "get_pool", fake_get_pool)

    from docforge.config import Settings

    settings = Settings(sources_file=str(sources_file))

    await ingest_all(settings)
    assert conn.inserted_sources == []


@pytest.mark.asyncio
async def test_ingest_confluence_propagates_stale_prefix_to_chunks(
    tmp_path, monkeypatch, fake_embedder
):
    """Regression: Rule 4's `[STALE YYYY]` prefix lives on the CrawledPage's
    title (set inside crawl_page when version.createdAt crosses the threshold).
    The chunks INSERT must use page.title, not source.title (the unprefixed
    YAML config name), so the prefix lands in chunks.title — the column the
    search API returns.

    See v0.7.7 CHANGELOG: in v0.7.6, sources.title got the prefix but
    chunks.title did not, breaking downstream surfacing of staleness.
    """
    from datetime import datetime, timezone

    from docforge.crawlers.confluence import CrawledPage

    sources_file = tmp_path / "sources.yml"
    # YAML title is unprefixed — only crawl_page adds [STALE …]
    sources_file.write_text(
        "sources:\n"
        "  - type: confluence_page\n"
        '    page_id: "12345"\n'
        '    space_key: "ENG"\n'
        '    title: "Diagnostic Data Adapter"\n'
        "    tags: [platform]\n"
    )

    prefixed_title = "[STALE 2020] Diagnostic Data Adapter"

    async def fake_crawl_page(page_id, **kwargs):
        return CrawledPage(
            page_id=page_id,
            title=prefixed_title,
            space_key="ENG",
            html_content="<h1>X</h1><p>some body text.</p>",
            content_hash="hash-abc",
            version=1,
            url="https://example.atlassian.net/wiki/spaces/ENG/pages/12345",
            last_modified=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )

    monkeypatch.setattr(ingest_mod, "crawl_page", fake_crawl_page)

    conn = _Conn(existing_hash=None)

    async def fake_get_pool(url, **kwargs):
        return _FakePool(conn)

    monkeypatch.setattr(ingest_mod, "get_pool", fake_get_pool)

    from docforge.config import Settings

    settings = Settings(sources_file=str(sources_file))

    await ingest_all(settings)

    assert conn.inserted_chunks, "expected at least one chunks INSERT"
    # Chunk INSERT positional args: (source_id, chunk_index, text, embedding,
    # section_title, title). Title is the LAST positional arg.
    for chunk_args in conn.inserted_chunks:
        assert chunk_args[-1] == prefixed_title, (
            f"chunks.title arg was {chunk_args[-1]!r}; expected the prefixed "
            f"page.title {prefixed_title!r}, not the unprefixed YAML "
            f"source.title."
        )


@pytest.mark.asyncio
async def test_ingest_git_source_inserts_chunks(tmp_path, monkeypatch, fake_embedder):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Title\n\nContent one.\n\n## Sub\n\nContent two.")

    sources_file = tmp_path / "sources.yml"
    sources_file.write_text(
        "sources:\n"
        "  - type: git_repo\n"
        f'    repo_path: "{repo.as_posix()}"\n'
        '    include_patterns: ["README.md"]\n'
        '    title: "RepoX"\n'
        "    tags: [platform]\n"
    )

    conn = _Conn(existing_hash=None)

    async def fake_get_pool(url, **kwargs):
        return _FakePool(conn)

    monkeypatch.setattr(ingest_mod, "get_pool", fake_get_pool)

    from docforge.config import Settings

    settings = Settings(sources_file=str(sources_file))

    await ingest_all(settings)

    assert len(conn.inserted_sources) == 1
    assert len(conn.inserted_chunks) >= 1
    # Tags are the last positional arg to fetchval in the INSERT call
    assert conn.inserted_sources[0][-1] == ["platform"]


@pytest.mark.asyncio
async def test_ingest_skips_when_hash_unchanged(tmp_path, monkeypatch, fake_embedder):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Title\n\nUnchanged content.")

    sources_file = tmp_path / "sources.yml"
    sources_file.write_text(
        "sources:\n"
        "  - type: git_repo\n"
        f'    repo_path: "{repo.as_posix()}"\n'
        '    include_patterns: ["README.md"]\n'
        '    title: "RepoX"\n'
    )

    import hashlib

    content = (repo / "README.md").read_text()
    existing_hash = hashlib.sha256(content.encode()).hexdigest()

    conn = _Conn(existing_hash=existing_hash)

    async def fake_get_pool(url, **kwargs):
        return _FakePool(conn)

    monkeypatch.setattr(ingest_mod, "get_pool", fake_get_pool)

    from docforge.config import Settings

    settings = Settings(sources_file=str(sources_file))

    await ingest_all(settings)

    # No new chunk inserts because hash matches
    assert conn.inserted_chunks == []


@pytest.mark.asyncio
async def test_purge_orphans_empty_identifiers_with_confirm_aborts():
    """Guard: _purge_orphans must return (0, 0) without touching the DB when
    current_identifiers is empty and confirm=True (would otherwise delete every row)."""

    pool = _FakePool(_Conn())
    result = await _purge_orphans(pool, current_identifiers=set(), confirm=True)
    assert result == (0, 0)


@pytest.mark.asyncio
async def test_ingest_continues_on_per_source_failure(tmp_path, monkeypatch, fake_embedder):
    repo_ok = tmp_path / "ok"
    repo_ok.mkdir()
    (repo_ok / "README.md").write_text("# OK\n\nContent.")

    sources_file = tmp_path / "sources.yml"
    sources_file.write_text(
        "sources:\n"
        "  - type: git_repo\n"
        '    repo_path: "E:/definitely/missing/repo"\n'
        '    include_patterns: ["README.md"]\n'
        '    title: "Missing"\n'
        "  - type: git_repo\n"
        f'    repo_path: "{repo_ok.as_posix()}"\n'
        '    include_patterns: ["README.md"]\n'
        '    title: "OK"\n'
    )

    conn = _Conn()

    async def fake_get_pool(url, **kwargs):
        return _FakePool(conn)

    monkeypatch.setattr(ingest_mod, "get_pool", fake_get_pool)

    from docforge.config import Settings

    settings = Settings(sources_file=str(sources_file))

    await ingest_all(settings)
    assert len(conn.inserted_chunks) >= 1


@pytest.mark.asyncio
async def test_ingest_all_skips_purge_when_any_source_failed(tmp_path, monkeypatch, fake_embedder):
    """Guard: if any source fails to ingest, --purge-orphans must not run.
    A failed source's identifiers are unknown and would be misclassified as
    orphans, causing data loss on the next cleanup pass."""
    repo_ok = tmp_path / "ok"
    repo_ok.mkdir()
    (repo_ok / "README.md").write_text("# OK\n\nContent.")

    sources_file = tmp_path / "sources.yml"
    sources_file.write_text(
        "sources:\n"
        "  - type: git_repo\n"
        '    repo_path: "E:/definitely/missing/repo"\n'
        '    include_patterns: ["README.md"]\n'
        '    title: "Missing"\n'
        "  - type: git_repo\n"
        f'    repo_path: "{repo_ok.as_posix()}"\n'
        '    include_patterns: ["README.md"]\n'
        '    title: "OK"\n'
    )

    conn = _Conn()

    async def fake_get_pool(url, **kwargs):
        return _FakePool(conn)

    monkeypatch.setattr(ingest_mod, "get_pool", fake_get_pool)

    purge_calls = {"n": 0}

    async def fake_purge(pool, current_identifiers, confirm):
        purge_calls["n"] += 1
        return (0, 0)

    monkeypatch.setattr(ingest_mod, "_purge_orphans", fake_purge)

    from docforge.config import Settings

    settings = Settings(sources_file=str(sources_file))

    # Request purge with confirm — but one source (the missing repo) will fail.
    # The guard should skip _purge_orphans entirely.
    await ingest_all(settings, purge_orphans=True, confirm=True)
    assert purge_calls["n"] == 0, "purge must be skipped when any source failed"


@pytest.mark.asyncio
async def test_ingest_confluence_tree_ingests_each_enumerated_page(
    tmp_path, monkeypatch, fake_embedder
):
    """A confluence_tree source enumerates descendant page ids, then ingests
    each one with the tree's tags."""
    from datetime import datetime, timezone

    from docforge.crawlers.confluence import CrawledPage

    sources_file = tmp_path / "sources.yml"
    sources_file.write_text(
        "sources:\n"
        "  - type: confluence_tree\n"
        '    root_page_id: "999"\n'
        "    space_key: ProDev\n"
        '    title: "ProDev: Team CCL"\n'
        "    tags: [productdev, ccl]\n"
    )

    async def fake_enumerate(root_page_id, **kwargs):
        assert root_page_id == "999"
        return ["101", "102"]

    crawled = {}

    async def fake_crawl_page(page_id, **kwargs):
        crawled[page_id] = kwargs
        return CrawledPage(
            page_id=page_id,
            title=f"Page {page_id}",
            space_key="9999",
            html_content="<h1>H</h1><p>body text here.</p>",
            content_hash=f"hash-{page_id}",
            version=1,
            url=f"https://x/wiki/spaces/ProDev/pages/{page_id}",
            last_modified=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    monkeypatch.setattr(ingest_mod, "enumerate_tree_page_ids", fake_enumerate)
    monkeypatch.setattr(ingest_mod, "crawl_page", fake_crawl_page)

    conn = _Conn(existing_hash=None)

    async def fake_get_pool(url, **kwargs):
        return _FakePool(conn)

    monkeypatch.setattr(ingest_mod, "get_pool", fake_get_pool)

    from docforge.config import Settings

    settings = Settings(sources_file=str(sources_file))
    await ingest_all(settings)

    # One source row per enumerated page (2), each carrying the tree's tags.
    assert len(conn.inserted_sources) == 2
    for src_args in conn.inserted_sources:
        assert src_args[-1] == ["productdev", "ccl"]
    assert set(crawled.keys()) == {"101", "102"}


@pytest.mark.asyncio
async def test_ingest_confluence_tree_skips_unchanged_page(tmp_path, monkeypatch, fake_embedder):
    """A tree page whose content_hash matches the stored hash is crawled but not
    re-stored; only the changed page produces a source INSERT."""
    from datetime import datetime, timezone

    from docforge.crawlers.confluence import CrawledPage

    sources_file = tmp_path / "sources.yml"
    sources_file.write_text(
        "sources:\n"
        "  - type: confluence_tree\n"
        '    root_page_id: "999"\n'
        "    space_key: ProDev\n"
        '    title: "T"\n'
        "    tags: [productdev]\n"
    )

    async def fake_enumerate(root_page_id, **kwargs):
        return ["101", "102"]

    async def fake_crawl_page(page_id, **kwargs):
        return CrawledPage(
            page_id=page_id,
            title=f"Page {page_id}",
            space_key="9",
            html_content="<p>body text here.</p>",
            content_hash=f"hash-{page_id}",
            version=1,
            url=f"https://x/wiki/spaces/ProDev/pages/{page_id}",
            last_modified=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    monkeypatch.setattr(ingest_mod, "enumerate_tree_page_ids", fake_enumerate)
    monkeypatch.setattr(ingest_mod, "crawl_page", fake_crawl_page)

    class _PageHashConn(_Conn):
        async def fetchval(self, query, *args):
            q = query.strip().lower()
            if q.startswith("select content_hash"):
                # page 101 unchanged (stored hash matches crawl), 102 is new
                return "hash-101" if args and args[0] == "101" else None
            return await super().fetchval(query, *args)

    conn = _PageHashConn()

    async def fake_get_pool(url, **kwargs):
        return _FakePool(conn)

    monkeypatch.setattr(ingest_mod, "get_pool", fake_get_pool)

    from docforge.config import Settings

    settings = Settings(sources_file=str(sources_file))
    await ingest_all(settings)

    # Only the changed page (102) is stored; 101 is skipped on hash match.
    assert len(conn.inserted_sources) == 1
    # sources INSERT positional args: (url, title, page_id, space_key, now, hash, tags)
    assert conn.inserted_sources[0][2] == "102"
