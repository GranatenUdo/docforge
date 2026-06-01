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
        async def fake():
            return None

        monkeypatch.setattr("docforge.cli._init_db", fake)
        result = runner.invoke(app, ["init-db"])
        assert result.exit_code == 0


class TestIngestCommand:
    def test_success(self, monkeypatch):
        called = {"n": 0}

        async def fake(purge_orphans=False, confirm=False):
            called["n"] += 1

        monkeypatch.setattr("docforge.cli._ingest", fake)
        result = runner.invoke(app, ["ingest"])
        assert result.exit_code == 0
        assert called["n"] == 1


class TestSearchCommand:
    def test_success_with_required_flags(self, monkeypatch):
        captured = {}

        async def fake(query, user_name, team_name, area_name, limit):
            captured["query"] = query
            captured["user"] = user_name
            captured["team"] = team_name
            captured["area"] = area_name
            captured["limit"] = limit

        monkeypatch.setattr("docforge.cli._search", fake)
        result = runner.invoke(
            app,
            [
                "search",
                "q",
                "--user",
                "tobias",
                "--team",
                "platform",
                "--area",
                "cloud",
                "--limit",
                "3",
            ],
        )
        assert result.exit_code == 0
        assert captured == {
            "query": "q",
            "user": "tobias",
            "team": "platform",
            "area": "cloud",
            "limit": 3,
        }

    def test_area_optional(self, monkeypatch):
        captured = {}

        async def fake(query, user_name, team_name, area_name, limit):
            captured["area"] = area_name

        monkeypatch.setattr("docforge.cli._search", fake)
        result = runner.invoke(
            app,
            ["search", "q", "--user", "u", "--team", "t"],
        )
        assert result.exit_code == 0
        assert captured["area"] is None

    def test_fails_when_user_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["search", "q", "--team", "t"])
        assert result.exit_code == 1
        assert "--user is required" in (result.output + (result.stderr or ""))

    def test_fails_when_team_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["search", "q", "--user", "u"])
        assert result.exit_code == 1
        assert "--team is required" in (result.output + (result.stderr or ""))

    def test_uses_settings_default_user(self, monkeypatch, tmp_path):
        captured = {}

        async def fake(query, user_name, team_name, area_name, limit):
            captured["user"] = user_name
            captured["team"] = team_name

        monkeypatch.setattr("docforge.cli._search", fake)
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text(
            "default_user_name: tobias.default\ndefault_team_name: platform.default\n"
        )
        result = runner.invoke(app, ["search", "q"])
        assert result.exit_code == 0
        assert captured == {"user": "tobias.default", "team": "platform.default"}


class TestStatusCommand:
    def test_success(self, monkeypatch):
        async def fake():
            return None

        monkeypatch.setattr("docforge.cli._status", fake)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0


class TestLintDocsCommand:
    def test_clean_repo_exits_zero(self, tmp_path, monkeypatch):
        (tmp_path / "README.md").write_text("# Clean repo\n", encoding="utf-8")
        result = runner.invoke(app, ["lint-docs", str(tmp_path)])
        assert result.exit_code == 0
        assert "PASS" in result.output

    def test_failing_repo_exits_one(self, tmp_path, monkeypatch):
        (tmp_path / "README.md").write_text("# Repo\n\nTODO: Explain\n", encoding="utf-8")
        result = runner.invoke(app, ["lint-docs", str(tmp_path)])
        assert result.exit_code == 1
        assert "FAIL" in result.output
        assert "todo-placeholder" in result.output

    def test_missing_directory_exits_one(self, tmp_path):
        missing = tmp_path / "does-not-exist"
        result = runner.invoke(app, ["lint-docs", str(missing)])
        assert result.exit_code == 1
        assert "not a directory" in (result.output + (result.stderr or ""))


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
        async def fake_ingest_all(settings, *, purge_orphans=False, confirm=False):
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


def test_serve_remote_api_dispatches_to_run_remote_mcp(monkeypatch):
    """`serve --remote-api $URL --auth bearer` calls run_remote_mcp with AuthName.bearer."""
    from docforge.remote_client import AuthName

    captured = {}

    def fake_run_remote_mcp(
        *, url: str, auth_name, instructions=None, tool_description=None
    ) -> None:
        captured["url"] = url
        captured["auth_name"] = auth_name

    monkeypatch.setattr("docforge.remote_client.run_remote_mcp", fake_run_remote_mcp)

    result = runner.invoke(
        app, ["serve", "--remote-api", "https://api.example.com", "--auth", "bearer"]
    )
    assert result.exit_code == 0, result.output
    assert captured["url"] == "https://api.example.com"
    assert captured["auth_name"] is AuthName.bearer


def test_serve_remote_api_and_api_mutually_exclusive(monkeypatch):
    """Passing both --api and --remote-api errors with exit code 1."""
    result = runner.invoke(app, ["serve", "--api", "--remote-api", "https://api.example.com"])
    assert result.exit_code == 1
    assert "mutually exclusive" in (result.output + (result.stderr or ""))


def test_serve_remote_api_falls_back_to_env_var(monkeypatch):
    """When --remote-api flag is omitted but DOCFORGE_API_URL is set, it's used."""
    monkeypatch.setenv("DOCFORGE_API_URL", "https://from-env.example.com")
    captured = {}

    def fake_run_remote_mcp(
        *, url: str, auth_name, instructions=None, tool_description=None
    ) -> None:
        captured["url"] = url

    monkeypatch.setattr("docforge.remote_client.run_remote_mcp", fake_run_remote_mcp)

    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0, result.output
    assert captured["url"] == "https://from-env.example.com"
