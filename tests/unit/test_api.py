"""Tests for docforge.api FastAPI endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from docforge.api import app, get_azure_scheme, get_embedder, get_pool_dep, get_settings
from tests.conftest import CapturingPool, FakePool, fake_settings


@pytest.fixture(autouse=True)
def _no_lifespan_defaults():
    """Default lifespan-populated dependencies to safe stubs for all tests in
    this module.

    Tests bypass the FastAPI lifespan (ASGITransport doesn't run it), so
    request.state is empty. These overrides prevent AttributeError when
    dependency getters try to read request.state keys that lifespan would
    normally populate.

    Individual tests replace these defaults with their own overrides as needed.
    The overrides dict is cleared fully by each test's own try/finally block;
    this fixture only ensures the module-wide defaults are in place.
    """
    from tests.conftest import FakeEmbedder

    app.dependency_overrides[get_azure_scheme] = lambda: None
    app.dependency_overrides[get_settings] = fake_settings
    app.dependency_overrides[get_pool_dep] = lambda: CapturingPool(rows=[])
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    yield
    app.dependency_overrides.clear()


def _client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self):
        async with _client() as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestSearchEndpoint:
    @pytest.mark.asyncio
    async def test_returns_results_on_success(self):
        rows = [
            {
                "text": "Platform owns orgs.",
                "section_title": "Platform",
                "source_title": "Doc A",
                "source_url": "https://wiki/a",
                "source_tags": ["platform", "cloud"],
                "similarity": 0.95,
            }
        ]

        from tests.conftest import FakeEmbedder

        pool = CapturingPool(rows)

        app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
        app.dependency_overrides[get_pool_dep] = lambda: pool
        app.dependency_overrides[get_settings] = fake_settings
        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={
                        "query": "q",
                        "user_name": "tobias.ens",
                        "team_name": "platform",
                        "area_name": "cloud",
                        "limit": 5,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["results"][0]["text"] == "Platform owns orgs."
        assert body["results"][0]["source_tags"] == ["platform", "cloud"]
        assert any("INSERT INTO query_log" in q for q, _ in pool.executes)

    @pytest.mark.asyncio
    async def test_returns_503_on_db_error(self):
        from tests.conftest import FakeEmbedder

        class _BrokenPool:
            def acquire(self):
                raise OSError("db down")

        app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
        app.dependency_overrides[get_pool_dep] = lambda: _BrokenPool()
        app.dependency_overrides[get_settings] = fake_settings
        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={
                        "query": "q",
                        "user_name": "u",
                        "team_name": "t",
                        "limit": 1,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 503
        assert "Database unavailable" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_returns_500_on_embed_error(self):
        from unittest.mock import AsyncMock

        fake_embedder = MagicMock()
        fake_embedder.aembed_query = AsyncMock(side_effect=RuntimeError("embed broken"))

        app.dependency_overrides[get_embedder] = lambda: fake_embedder
        app.dependency_overrides[get_pool_dep] = lambda: CapturingPool(rows=[])
        app.dependency_overrides[get_settings] = fake_settings
        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={
                        "query": "q",
                        "user_name": "u",
                        "team_name": "t",
                        "limit": 1,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_reranker_outage_returns_502_not_503(self):
        """A reranker sidecar outage maps to 502 (upstream dependency down),
        NOT the generic 503 reserved for DB failures."""
        import httpx

        from docforge.api import get_reranker
        from tests.conftest import FakeEmbedder

        # One canned row so the rerank seam (which runs only when rows) fires.
        rows = [
            {
                "text": "body",
                "section_title": "sec",
                "source_title": "Doc",
                "source_url": "https://wiki/0",
                "source_tags": ["ccl"],
                "similarity": 0.9,
                "dense_rank": 1,
                "sparse_rank": 1,
            }
        ]

        def _rerank_on_settings():
            s = fake_settings()
            s.rerank_enabled = True
            s.rerank_top_n = 50
            s.reranker_url = "https://rerank.invalid"
            return s

        class _DownReranker:
            async def arerank(self, query, passages):
                raise httpx.ConnectError("sidecar down")

        app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
        app.dependency_overrides[get_pool_dep] = lambda: CapturingPool(rows=rows)
        app.dependency_overrides[get_settings] = _rerank_on_settings
        app.dependency_overrides[get_reranker] = lambda: _DownReranker()
        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={"query": "q", "team_name": "ccl", "limit": 5},
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 502
        assert "reranker unavailable" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_search_rejects_limit_over_max(self):
        """limit > 50 returns 422 with the limit field in the error detail."""
        async with _client() as client:
            resp = await client.post(
                "/search",
                json={
                    "query": "q",
                    "user_name": "u",
                    "team_name": "t",
                    "limit": 51,
                },
            )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert any(err["loc"][-1] == "limit" for err in detail)

    @pytest.mark.asyncio
    async def test_search_rejects_limit_under_min(self):
        """limit < 1 returns 422 with the limit field in the error detail."""
        async with _client() as client:
            resp = await client.post(
                "/search",
                json={
                    "query": "q",
                    "user_name": "u",
                    "team_name": "t",
                    "limit": 0,
                },
            )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert any(err["loc"][-1] == "limit" for err in detail)

    @pytest.mark.asyncio
    async def test_search_rejects_query_over_max_length(self):
        """query > 8000 chars returns 422 with the query field in the error detail."""
        async with _client() as client:
            resp = await client.post(
                "/search",
                json={
                    "query": "x" * 8001,
                    "user_name": "u",
                    "team_name": "t",
                    "limit": 1,
                },
            )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert any(err["loc"][-1] == "query" for err in detail)

    @pytest.mark.asyncio
    async def test_search_runs_embed_via_to_thread(self, monkeypatch):
        """The search handler calls aembed_query on the embedder, which
        (for in-process Embedder) wraps the sync call in asyncio.to_thread.
        This test verifies aembed_query is called with the correct query."""
        from unittest.mock import AsyncMock

        fake_embedder = MagicMock()
        fake_embedder.aembed_query = AsyncMock(return_value=[0.0] * 768)

        app.dependency_overrides[get_embedder] = lambda: fake_embedder
        app.dependency_overrides[get_pool_dep] = lambda: CapturingPool(rows=[])
        app.dependency_overrides[get_settings] = fake_settings
        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={
                        "query": "hello",
                        "user_name": "u",
                        "team_name": "t",
                        "limit": 1,
                    },
                )
            assert resp.status_code == 200
            fake_embedder.aembed_query.assert_called_once_with("hello")
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_search_uses_anonymous_when_no_auth_no_user_name(self, monkeypatch):
        """POST /search without user_name and no auth → log_search receives 'anonymous'."""
        captured: dict = {}

        async def fake_log_search(pool, user_name, team_name, area_name, query, count, **kwargs):
            captured["user_name"] = user_name
            captured["team_name"] = team_name

        monkeypatch.setattr("docforge.api.log_search", fake_log_search)

        async with _client() as client:
            resp = await client.post("/search", json={"query": "hello", "limit": 5})

        assert resp.status_code == 200
        assert captured["user_name"] == "anonymous"
        assert captured["team_name"] is None

    @pytest.mark.asyncio
    async def test_search_uses_auth_subject_when_present(self, monkeypatch):
        """POST /search with auth subject → log_search receives preferred_username."""
        from types import SimpleNamespace

        from docforge.api import _auth_dependency

        captured: dict = {}

        async def fake_log_search(pool, user_name, team_name, area_name, query, count, **kwargs):
            captured["user_name"] = user_name

        monkeypatch.setattr("docforge.api.log_search", fake_log_search)

        fake_user = SimpleNamespace(preferred_username="tobias.ens", oid="abc-123")
        app.dependency_overrides[_auth_dependency] = lambda: fake_user
        try:
            async with _client() as client:
                resp = await client.post("/search", json={"query": "hello", "limit": 5})
        finally:
            del app.dependency_overrides[_auth_dependency]

        assert resp.status_code == 200
        assert captured["user_name"] == "tobias.ens"


class TestSourcesEndpoint:
    @pytest.mark.asyncio
    async def test_lists_sources(self):
        rows = [
            {
                "title": "Doc A",
                "url": "https://wiki/a",
                "status": "active",
                "last_crawled_at": datetime(2026, 4, 17, 9, 0, tzinfo=timezone.utc),
                "chunk_count": 4,
            }
        ]
        fake_pool = FakePool(rows)

        app.dependency_overrides[get_pool_dep] = lambda: fake_pool
        app.dependency_overrides[get_settings] = fake_settings
        try:
            async with _client() as client:
                resp = await client.get("/sources")
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["sources"][0]["title"] == "Doc A"

    @pytest.mark.asyncio
    async def test_returns_503_on_db_error(self):
        class _BrokenPool:
            def acquire(self):
                raise OSError("boom")

        app.dependency_overrides[get_pool_dep] = lambda: _BrokenPool()
        app.dependency_overrides[get_settings] = fake_settings
        try:
            async with _client() as client:
                resp = await client.get("/sources")
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 503


class TestRequestTimingInstrumentation:
    """C4.3 — the /search handler measures its own wall-clock time and
    passes request_ms into log_search."""

    @pytest.mark.asyncio
    async def test_search_writes_request_ms_to_query_log(self, monkeypatch):
        captured: dict = {}

        async def fake_log_search(*args, **kwargs):
            captured.update(kwargs)

        monkeypatch.setattr("docforge.api.log_search", fake_log_search)

        from tests.conftest import FakeEmbedder

        app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
        app.dependency_overrides[get_pool_dep] = lambda: CapturingPool(rows=[])
        app.dependency_overrides[get_settings] = fake_settings
        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={
                        "query": "test",
                        "user_name": "tobias",
                        "team_name": "platform",
                        "area_name": None,
                        "limit": 3,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert "request_ms" in captured
        assert isinstance(captured["request_ms"], int)
        assert captured["request_ms"] >= 0
        # Sanity: should be much less than a second for a stubbed handler.
        assert captured["request_ms"] < 1000


def test_search_request_default_limit_is_10():
    from docforge.api import SearchRequest

    assert SearchRequest(query="x").limit == 10


def test_search_request_user_name_and_team_name_optional():
    """SearchRequest validates without user_name or team_name (relaxed schema)."""
    from docforge.api import SearchRequest

    req = SearchRequest(query="hello", limit=5)
    assert req.user_name is None
    assert req.team_name is None
    assert req.area_name is None
    assert req.query == "hello"


def test_search_request_accepts_full_body_for_backwards_compat():
    """Existing clients still work when sending all identity fields."""
    from docforge.api import SearchRequest

    req = SearchRequest(
        query="hello",
        user_name="tobias.ens",
        team_name="ccl",
        area_name="cloud",
        limit=10,
    )
    assert req.user_name == "tobias.ens"
    assert req.team_name == "ccl"
    assert req.area_name == "cloud"


class TestSearchPhaseLogging:
    @pytest.mark.asyncio
    async def test_search_logs_phase_latencies(self, caplog):
        """Each /search call emits exactly one 'search_phases' log line with
        embed and db timings; t_total_ms is persisted to query_log.request_ms
        (NOT logged as a separate line — it's a DB metric, not an ops metric)."""
        import logging

        caplog.set_level(logging.INFO, logger="docforge.api")

        from tests.conftest import CapturingPool, FakeEmbedder, fake_settings

        pool = CapturingPool(
            [
                {
                    "text": "row",
                    "section_title": None,
                    "source_title": "Doc",
                    "source_url": "https://x",
                    "source_tags": [],
                    "similarity": 0.01,
                }
            ]
        )
        app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
        app.dependency_overrides[get_pool_dep] = lambda: pool
        app.dependency_overrides[get_settings] = fake_settings
        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={"query": "x", "team_name": "ccl", "limit": 1},
                )
            assert resp.status_code == 200, resp.text

            messages = [r.getMessage() for r in caplog.records]
            phase_lines = [m for m in messages if "search_phases" in m]
            assert len(phase_lines) == 1, (
                f"expected exactly 1 'search_phases' line, got {len(phase_lines)}: {phase_lines}"
            )
            line = phase_lines[0]
            assert "t_embed_ms=" in line, f"missing t_embed_ms in phase line: {line}"
            assert "t_db_ms=" in line, f"missing t_db_ms in phase line: {line}"
            assert "t_total_ms=" not in line, (
                "t_total_ms should be persisted to query_log.request_ms, "
                f"not logged as a separate field: {line}"
            )

            # t_total_ms is persisted to query_log via log_query's request_ms.
            # query_log.INSERT positional args (from query_log.py):
            #   $1=user_name, $2=team_name, $3=area_name, $4=query,
            #   $5=result_count, $6=user_oid, $7=request_ms
            # So request_ms is the LAST positional arg (args[6]).
            query_log_inserts = [
                (q, args) for q, args in pool.executes if "INSERT INTO query_log" in q
            ]
            assert len(query_log_inserts) == 1, (
                f"expected exactly 1 query_log INSERT, got {len(query_log_inserts)}"
            )
            args = query_log_inserts[0][1]
            # Pin the INSERT parameter count so a future query_log refactor that
            # appends a new positional arg fails loudly here instead of silently
            # picking up the wrong column from args[-1].
            assert len(args) == 7, (
                f"query_log INSERT param count changed (expected 7, got {len(args)}); "
                f"re-verify request_ms position before updating this test"
            )
            request_ms_value = args[-1]
            assert isinstance(request_ms_value, int) and request_ms_value >= 0, (
                f"expected request_ms to be a non-negative int, got {request_ms_value!r}"
            )
        finally:
            app.dependency_overrides.clear()


class TestLifespanLoggingConfig:
    @pytest.mark.asyncio
    async def test_lifespan_configures_root_logger_at_info(self, monkeypatch):
        """The lifespan installs a root logger handler at INFO so that
        docforge.api logger.info() calls reach stdout in production.

        Regression guard for the silent /search latency logs we discovered
        in production: uvicorn leaves the root logger at WARNING by default,
        so logger.info() from docforge.* was filtered before any handler.

        We force the root logger to WARNING first, then enter the lifespan
        (mocking out pool/embedder construction so we exercise only the
        logging-config slice), and assert the root logger is now INFO."""
        import logging

        from docforge import api as api_module

        # Stand the root logger up at WARNING (uvicorn's default state in prod).
        root = logging.getLogger()
        saved_level = root.level
        saved_handlers = root.handlers[:]
        logging.basicConfig(level=logging.WARNING, force=True)
        assert root.level == logging.WARNING

        # Make lifespan abort cheaply right after the logging.basicConfig call
        # so we don't need a real Postgres pool / embedder. The lifespan calls
        # asyncpg.create_pool immediately after basicConfig.
        async def _boom(*args, **kwargs):
            raise RuntimeError("stop after logging setup")

        monkeypatch.setattr(api_module.asyncpg, "create_pool", _boom)

        try:
            async with api_module.lifespan(api_module.app):
                pass  # pragma: no cover - lifespan should raise before yield
        except RuntimeError as e:
            assert "stop after logging setup" in str(e)
        finally:
            # Capture result before restoring so the assertion message is clean.
            final_level = root.level
            # Restore root logger state so we don't pollute other tests.
            for h in root.handlers[:]:
                root.removeHandler(h)
            for h in saved_handlers:
                root.addHandler(h)
            root.setLevel(saved_level)

        assert final_level == logging.INFO, (
            f"lifespan must reconfigure root logger to INFO; got {final_level}"
        )


@pytest.mark.asyncio
async def test_search_captures_results_when_flag_on():
    from tests.conftest import FakeEmbedder, fake_settings

    def _settings_capture():
        s = fake_settings()
        s.log_responses = True
        return s

    rows = [
        {
            "text": "Platform owns orgs.",
            "section_title": "Platform",
            "source_title": "Doc A",
            "source_url": "https://wiki/a",
            "source_tags": ["org"],
            "similarity": 0.03,
        }
    ]
    pool = CapturingPool(rows)
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    app.dependency_overrides[get_pool_dep] = lambda: pool
    app.dependency_overrides[get_settings] = _settings_capture
    try:
        async with _client() as client:
            resp = await client.post(
                "/search", json={"query": "q", "user_name": "u", "team_name": "ccl", "limit": 5}
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert any("INSERT INTO query_result" in q for q, _ in pool.executes)


@pytest.mark.asyncio
async def test_search_skips_capture_when_flag_off():
    from tests.conftest import FakeEmbedder

    rows = [
        {
            "text": "x",
            "section_title": None,
            "source_title": "T",
            "source_url": "u",
            "source_tags": [],
            "similarity": 0.01,
        }
    ]
    pool = CapturingPool(rows)
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    app.dependency_overrides[get_pool_dep] = lambda: pool
    app.dependency_overrides[get_settings] = fake_settings  # log_responses=False
    try:
        async with _client() as client:
            resp = await client.post(
                "/search", json={"query": "q", "user_name": "u", "team_name": "t", "limit": 5}
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert not any("INSERT INTO query_result" in q for q, _ in pool.executes)


class TestSearchDebugMode:
    @pytest.mark.asyncio
    async def test_debug_false_default_omits_debug_fields(self):
        """When debug is not requested, response has no debug block on the
        envelope and no debug field on each result. Backward compatible."""
        from tests.conftest import FakeEmbedder

        rows = [
            {
                "text": "Platform owns orgs.",
                "section_title": "Platform",
                "source_title": "Doc A",
                "source_url": "https://wiki/a",
                "source_tags": ["platform"],
                "similarity": 0.95,
                "dense_rank": 1,
                "sparse_rank": 2,
            }
        ]
        pool = CapturingPool(rows)

        app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
        app.dependency_overrides[get_pool_dep] = lambda: pool
        app.dependency_overrides[get_settings] = fake_settings
        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={"query": "q", "user_name": "u", "team_name": "t", "limit": 5},
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        # Pydantic v2 includes None fields in serialization by default;
        # assert the values are None (not that keys are absent) so the
        # public API surface remains backward-compatible for clients that
        # ignore unknown null fields.
        assert body.get("debug") is None
        assert body["results"][0].get("debug") is None

    @pytest.mark.asyncio
    async def test_debug_true_includes_per_result_and_envelope_debug(self):
        """With debug=true, each result has dense_rank/sparse_rank/rrf_score
        and the envelope has weights + k."""
        from tests.conftest import FakeEmbedder

        rows = [
            {
                "text": "Platform owns orgs.",
                "section_title": "Platform",
                "source_title": "Doc A",
                "source_url": "https://wiki/a",
                "source_tags": ["platform"],
                "similarity": 0.038,
                "dense_rank": 4,
                "sparse_rank": 1,
            }
        ]
        pool = CapturingPool(rows)

        app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
        app.dependency_overrides[get_pool_dep] = lambda: pool
        app.dependency_overrides[get_settings] = fake_settings
        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={
                        "query": "q",
                        "user_name": "u",
                        "team_name": "t",
                        "limit": 5,
                        "debug": True,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        # Per-result debug — assert non-null and check nested fields
        r0 = body["results"][0]
        assert r0["debug"] is not None
        assert r0["debug"]["dense_rank"] == 4
        assert r0["debug"]["sparse_rank"] == 1
        assert r0["debug"]["rrf_score"] == pytest.approx(0.038)
        # Envelope debug — assert non-null and check nested fields
        assert body["debug"] is not None
        assert body["debug"]["weights"]["dense"] == fake_settings().dense_weight
        assert body["debug"]["weights"]["sparse"] == fake_settings().sparse_weight
        assert body["debug"]["k"] == 5


def test_docs_routes_absent_when_expose_docs_false(monkeypatch):
    """EXPOSE_DOCS=false must strip /docs + /openapi.json from the app."""
    monkeypatch.setenv("EXPOSE_DOCS", "false")
    import importlib

    import docforge.api as api_mod
    importlib.reload(api_mod)
    try:
        assert api_mod.app.docs_url is None
        assert api_mod.app.openapi_url is None
        paths = {getattr(r, "path", None) for r in api_mod.app.routes}
        assert "/docs" not in paths and "/openapi.json" not in paths
    finally:
        monkeypatch.delenv("EXPOSE_DOCS", raising=False)
        importlib.reload(api_mod)  # restore default (docs on) for other tests
