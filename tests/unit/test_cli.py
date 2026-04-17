"""Tests for docforge.cli Typer commands via CliRunner."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from docforge.cli import app

runner = CliRunner()


class TestInit:
    def test_init_creates_project_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init", "myproj"])
        assert result.exit_code == 0
        assert (tmp_path / "myproj").is_dir()

    def test_init_fails_if_directory_exists(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "exists").mkdir()
        result = runner.invoke(app, ["init", "exists"])
        assert result.exit_code == 1
        # Error message goes to stderr via typer.echo(err=True);
        # Typer's CliRunner captures it in result.output (combined).
        assert "already exists" in (result.output + (result.stderr or ""))


class TestInitDb:
    def test_success(self, monkeypatch):
        async def fake(): return None
        monkeypatch.setattr("docforge.cli._init_db", fake)
        result = runner.invoke(app, ["init-db"])
        assert result.exit_code == 0


class TestIngestCommand:
    def test_success(self, monkeypatch):
        called = {"n": 0}

        async def fake():
            called["n"] += 1

        monkeypatch.setattr("docforge.cli._ingest", fake)
        result = runner.invoke(app, ["ingest"])
        assert result.exit_code == 0
        assert called["n"] == 1


class TestSearchCommand:
    def test_success(self, monkeypatch):
        captured = {}

        async def fake(query, limit):
            captured["query"] = query
            captured["limit"] = limit

        monkeypatch.setattr("docforge.cli._search", fake)
        result = runner.invoke(app, ["search", "how do migrations work", "--limit", "3"])
        assert result.exit_code == 0
        assert captured == {"query": "how do migrations work", "limit": 3}


class TestStatusCommand:
    def test_success(self, monkeypatch):
        async def fake(): return None
        monkeypatch.setattr("docforge.cli._status", fake)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0


class TestServeCommand:
    def test_serve_mcp_calls_mcp_run(self, monkeypatch):
        calls = {"mcp": 0}

        class FakeMCP:
            def run(self):
                calls["mcp"] += 1

        monkeypatch.setattr("docforge.mcp_server.mcp", FakeMCP())
        result = runner.invoke(app, ["serve"])
        assert result.exit_code == 0
        assert calls["mcp"] == 1

    def test_serve_api_calls_uvicorn(self, monkeypatch):
        calls = {"n": 0}

        def fake_run(app, **kwargs):
            calls["n"] += 1

        monkeypatch.setattr("uvicorn.run", fake_run)
        result = runner.invoke(app, ["serve", "--api"])
        assert result.exit_code == 0
        assert calls["n"] == 1


class TestHelperCoroutines:
    """Drive the private _init_db / _ingest helpers directly with mocked
    dependencies to exercise their error-handling branches."""

    @pytest.mark.asyncio
    async def test_init_db_os_error_exits_with_1(self, monkeypatch):
        async def fake_init_db(url):
            raise OSError("no db")

        monkeypatch.setattr("docforge.db.init_db", fake_init_db)

        import typer

        from docforge.cli import _init_db

        with pytest.raises(typer.Exit) as ex:
            await _init_db()
        assert ex.value.exit_code == 1

    @pytest.mark.asyncio
    async def test_ingest_os_error_exits_with_1(self, monkeypatch):
        async def fake_ingest_all(settings):
            raise OSError("no db")

        async def fake_close():
            return None

        monkeypatch.setattr("docforge.ingest.ingest_all", fake_ingest_all)
        monkeypatch.setattr("docforge.db.close_pool", fake_close)

        import typer

        from docforge.cli import _ingest

        with pytest.raises(typer.Exit) as ex:
            await _ingest()
        assert ex.value.exit_code == 1
