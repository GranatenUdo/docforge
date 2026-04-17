"""Tests for docforge.config.Settings — YAML loading, env overrides, precedence."""

from __future__ import annotations

import pytest


class TestSettingsDefaults:
    def test_defaults_when_no_yml_or_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for var in ("DATABASE_URL", "CONFLUENCE_BASE_URL", "HF_TOKEN", "EMBEDDING_MODEL"):
            monkeypatch.delenv(var, raising=False)

        from docforge.config import Settings

        s = Settings()
        assert s.database_url == "postgresql://docforge:localdev@localhost:5432/docforge"
        assert s.confluence_base_url == ""
        assert s.embedding_model == "google/embeddinggemma-300m"
        assert s.embedding_dimensions == 768
        assert s.chunk_max_tokens == 500
        assert s.sources_file == "sources.yml"
        assert s.tag_match_weight == pytest.approx(0.1)
        assert s.org_tag_weight == pytest.approx(0.05)
        assert s.default_user_name == ""
        assert s.default_team_name == ""
        assert s.default_area_name == ""


class TestYamlLoading:
    def test_loads_flat_keys_from_docforge_yml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for var in ("DATABASE_URL", "CONFLUENCE_BASE_URL"):
            monkeypatch.delenv(var, raising=False)
        (tmp_path / "docforge.yml").write_text(
            "database_url: postgresql://u:p@h:5432/db\n"
            "confluence_base_url: https://example.atlassian.net\n"
            "confluence_email: user@example.com\n"
        )

        from docforge.config import Settings

        s = Settings()
        assert s.database_url == "postgresql://u:p@h:5432/db"
        assert s.confluence_base_url == "https://example.atlassian.net"
        assert s.confluence_email == "user@example.com"

    def test_embedding_section_is_flattened(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text(
            "embedding:\n"
            "  model: custom/model\n"
            "  dimensions: 384\n"
            "  chunk_max_tokens: 200\n"
        )

        from docforge.config import Settings

        s = Settings()
        assert s.embedding_model == "custom/model"
        assert s.embedding_dimensions == 384
        assert s.chunk_max_tokens == 200

    def test_empty_yml_file_does_not_crash(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text("")

        from docforge.config import Settings

        s = Settings()
        assert s.embedding_model == "google/embeddinggemma-300m"


class TestPrecedence:
    def test_yml_overrides_env_due_to_init_kwarg_pass_through(
        self, tmp_path, monkeypatch
    ):
        # yml values flow through super().__init__(**merged), which
        # pydantic-settings treats as init-kwargs — higher priority than
        # env vars.
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text(
            "database_url: postgresql://yml:yml@yml:5432/yml\n"
        )
        monkeypatch.setenv("DATABASE_URL", "postgresql://env:env@env:5432/env")

        from docforge.config import Settings

        s = Settings()
        assert s.database_url == "postgresql://yml:yml@yml:5432/yml"

    def test_env_used_when_no_yml_entry(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # yml does NOT set confluence_email; env should win
        (tmp_path / "docforge.yml").write_text(
            "database_url: postgresql://yml\n"
        )
        monkeypatch.setenv("CONFLUENCE_EMAIL", "env@user.com")

        from docforge.config import Settings

        s = Settings()
        assert s.confluence_email == "env@user.com"

    def test_kwargs_override_env_and_yml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text("database_url: postgresql://yml\n")
        monkeypatch.setenv("DATABASE_URL", "postgresql://env")

        from docforge.config import Settings

        s = Settings(database_url="postgresql://kwarg")
        assert s.database_url == "postgresql://kwarg"


class TestSecrets:
    def test_secretstr_fields_not_leaked_in_repr(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HF_TOKEN", "secret_token_shhh")

        from docforge.config import Settings

        s = Settings()
        assert s.hf_token.get_secret_value() == "secret_token_shhh"
        assert "secret_token_shhh" not in repr(s)
