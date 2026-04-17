"""Tests for docforge.ingest — the end-to-end ingest pipeline.

All heavy dependencies are mocked: the Embedder is replaced via the
fake_embedder fixture; asyncpg pool/connection are fakes; crawlers are
monkeypatched to return in-memory objects.
"""

from __future__ import annotations

import pytest

from docforge import ingest as ingest_mod
from docforge.ingest import _parse_markdown, ingest_all


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
async def test_ingest_all_with_empty_sources_list(
    tmp_path, monkeypatch, fake_embedder
):
    sources_file = tmp_path / "sources.yml"
    sources_file.write_text("sources: []\n")

    conn = _Conn()

    async def fake_get_pool(url):
        return _FakePool(conn)

    monkeypatch.setattr(ingest_mod, "get_pool", fake_get_pool)

    from docforge.config import Settings

    settings = Settings(sources_file=str(sources_file))

    await ingest_all(settings)
    assert conn.inserted_sources == []


@pytest.mark.asyncio
async def test_ingest_git_source_inserts_chunks(
    tmp_path, monkeypatch, fake_embedder
):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Title\n\nContent one.\n\n## Sub\n\nContent two.")

    sources_file = tmp_path / "sources.yml"
    sources_file.write_text(
        "sources:\n"
        "  - type: git_repo\n"
        f'    repo_path: "{repo.as_posix()}"\n'
        "    include_patterns: [\"README.md\"]\n"
        "    title: \"RepoX\"\n"
    )

    conn = _Conn(existing_hash=None)

    async def fake_get_pool(url):
        return _FakePool(conn)

    monkeypatch.setattr(ingest_mod, "get_pool", fake_get_pool)

    from docforge.config import Settings

    settings = Settings(sources_file=str(sources_file))

    await ingest_all(settings)

    assert len(conn.inserted_sources) == 1
    assert len(conn.inserted_chunks) >= 1


@pytest.mark.asyncio
async def test_ingest_skips_when_hash_unchanged(
    tmp_path, monkeypatch, fake_embedder
):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Title\n\nUnchanged content.")

    sources_file = tmp_path / "sources.yml"
    sources_file.write_text(
        "sources:\n"
        "  - type: git_repo\n"
        f'    repo_path: "{repo.as_posix()}"\n'
        "    include_patterns: [\"README.md\"]\n"
        "    title: \"RepoX\"\n"
    )

    import hashlib

    content = (repo / "README.md").read_text()
    existing_hash = hashlib.sha256(content.encode()).hexdigest()

    conn = _Conn(existing_hash=existing_hash)

    async def fake_get_pool(url):
        return _FakePool(conn)

    monkeypatch.setattr(ingest_mod, "get_pool", fake_get_pool)

    from docforge.config import Settings

    settings = Settings(sources_file=str(sources_file))

    await ingest_all(settings)

    # No new chunk inserts because hash matches
    assert conn.inserted_chunks == []


@pytest.mark.asyncio
async def test_ingest_continues_on_per_source_failure(
    tmp_path, monkeypatch, fake_embedder
):
    repo_ok = tmp_path / "ok"
    repo_ok.mkdir()
    (repo_ok / "README.md").write_text("# OK\n\nContent.")

    sources_file = tmp_path / "sources.yml"
    sources_file.write_text(
        "sources:\n"
        "  - type: git_repo\n"
        '    repo_path: "E:/definitely/missing/repo"\n'
        "    include_patterns: [\"README.md\"]\n"
        "    title: \"Missing\"\n"
        "  - type: git_repo\n"
        f'    repo_path: "{repo_ok.as_posix()}"\n'
        "    include_patterns: [\"README.md\"]\n"
        "    title: \"OK\"\n"
    )

    conn = _Conn()

    async def fake_get_pool(url):
        return _FakePool(conn)

    monkeypatch.setattr(ingest_mod, "get_pool", fake_get_pool)

    from docforge.config import Settings

    settings = Settings(sources_file=str(sources_file))

    await ingest_all(settings)
    assert len(conn.inserted_chunks) >= 1
