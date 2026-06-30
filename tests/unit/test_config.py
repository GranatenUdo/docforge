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
        assert s.embedding_model == "Qwen/Qwen3-Embedding-4B"
        assert s.embedding_dimensions == 1024
        assert s.chunk_max_tokens == 500
        assert s.sources_file == "sources.yml"
        assert s.tag_match_weight == pytest.approx(0.1)
        assert not hasattr(s, "org_tag_weight")
        assert s.default_user_name == ""
        assert s.default_team_name == ""
        assert s.default_area_name == ""
        assert s.mcp_instructions == ""
        assert s.mcp_tool_description == ""


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
            "embedding:\n  model: custom/model\n  dimensions: 384\n  chunk_max_tokens: 200\n"
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
        assert s.embedding_model == "Qwen/Qwen3-Embedding-4B"


class TestPrecedence:
    def test_yml_overrides_env_due_to_init_kwarg_pass_through(self, tmp_path, monkeypatch):
        # yml values flow through super().__init__(**merged), which
        # pydantic-settings treats as init-kwargs — higher priority than
        # env vars.
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text("database_url: postgresql://yml:yml@yml:5432/yml\n")
        monkeypatch.setenv("DATABASE_URL", "postgresql://env:env@env:5432/env")

        from docforge.config import Settings

        s = Settings()
        assert s.database_url == "postgresql://yml:yml@yml:5432/yml"

    def test_env_used_when_no_yml_entry(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # yml does NOT set confluence_email; env should win
        (tmp_path / "docforge.yml").write_text("database_url: postgresql://yml\n")
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


class TestAuthSettings:
    def test_default_mode_is_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from docforge.config import Settings

        s = Settings()
        assert s.auth.mode == "none"
        assert s.auth.tenant_id == ""
        assert s.auth.audience == ""

    def test_loads_auth_from_yml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text(
            "auth:\n  mode: entra\n  tenant_id: t-123\n  audience: api://a-456\n",
            encoding="utf-8",
        )
        from docforge.config import Settings

        s = Settings()
        assert s.auth.mode == "entra"
        assert s.auth.tenant_id == "t-123"
        assert s.auth.audience == "api://a-456"

    def test_env_populates_when_yml_absent(self, tmp_path, monkeypatch):
        """Env vars populate auth fields when the yml has no `auth:` block.
        (Matches docforge's established yml>env precedence: yml wins when both
        are set; env is the only source when yml is absent.)"""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AUTH__MODE", "entra")
        monkeypatch.setenv("AUTH__TENANT_ID", "t-from-env")
        monkeypatch.setenv("AUTH__AUDIENCE", "api://env")
        from docforge.config import Settings

        s = Settings()
        assert s.auth.mode == "entra"
        assert s.auth.tenant_id == "t-from-env"
        assert s.auth.audience == "api://env"

    def test_entra_mode_requires_tenant_and_audience(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text(
            "auth:\n  mode: entra\n  tenant_id: ''\n  audience: ''\n",
            encoding="utf-8",
        )
        from docforge.config import Settings

        with pytest.raises(ValueError, match="tenant_id"):
            Settings()

    def test_auth_absent_from_yml_loads_cleanly(self, tmp_path, monkeypatch):
        """Regression: a yml without any auth: block must still load."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text(
            "database_url: postgresql://example/db\n",
            encoding="utf-8",
        )
        from docforge.config import Settings

        s = Settings()
        assert s.auth.mode == "none"


class TestQueryLogRetention:
    def test_default_retention_days(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from docforge.config import Settings

        s = Settings()
        assert s.query_log_retention_days == 180

    def test_retention_overridable_in_yml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text(
            "query_log_retention_days: 90\n",
            encoding="utf-8",
        )
        from docforge.config import Settings

        s = Settings()
        assert s.query_log_retention_days == 90


class TestPoolSettings:
    def test_default_pool_sizes(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from docforge.config import Settings

        s = Settings()
        assert s.pool_min_size == 5
        assert s.pool_max_size == 25

    def test_pool_sizes_overridable_in_yml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text(
            "pool_min_size: 2\npool_max_size: 10\n",
            encoding="utf-8",
        )
        from docforge.config import Settings

        s = Settings()
        assert s.pool_min_size == 2
        assert s.pool_max_size == 10


class TestEmbedderSidecarSettings:
    def test_defaults_when_unset(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for var in ("EMBEDDER_URL", "EMBEDDER_TOKEN"):
            monkeypatch.delenv(var, raising=False)
        from docforge.config import Settings

        s = Settings()
        assert s.embedder_url == ""
        assert s.embedder_token.get_secret_value() == ""

    def test_url_and_token_loadable_from_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("EMBEDDER_URL", "https://embed.internal")
        monkeypatch.setenv("EMBEDDER_TOKEN", "hunter2")
        from docforge.config import Settings

        s = Settings()
        assert s.embedder_url == "https://embed.internal"
        assert s.embedder_token.get_secret_value() == "hunter2"

    def test_url_set_without_token_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text(
            "embedder_url: https://embed.example\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("EMBEDDER_TOKEN", raising=False)
        from docforge.config import Settings

        with pytest.raises(ValueError, match="embedder_token"):
            Settings()

    def test_token_secretstr_not_in_repr(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("EMBEDDER_URL", "https://embed.internal")
        monkeypatch.setenv("EMBEDDER_TOKEN", "very-secret-shhh")
        from docforge.config import Settings

        s = Settings()
        assert "very-secret-shhh" not in repr(s)


class TestRerankerSettings:
    _RERANK_VARS = (
        "RERANK_ENABLED",
        "RERANK_MODEL",
        "RERANK_TOP_N",
        "RERANKER_URL",
        "RERANKER_TOKEN",
    )

    def test_defaults_when_unset(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for var in self._RERANK_VARS:
            monkeypatch.delenv(var, raising=False)
        from docforge.config import Settings

        s = Settings()
        assert s.rerank_enabled is False
        assert s.rerank_model == "BAAI/bge-reranker-v2-m3"
        assert s.rerank_top_n == 50
        assert s.reranker_url == ""
        assert s.reranker_token.get_secret_value() == ""
        assert s.rerank_batch_size == 8
        assert s.rerank_max_length == 512

    def test_overrides_loadable_from_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for var in self._RERANK_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("RERANK_ENABLED", "true")
        monkeypatch.setenv("RERANK_MODEL", "BAAI/bge-reranker-base")
        monkeypatch.setenv("RERANK_TOP_N", "25")
        monkeypatch.setenv("RERANKER_URL", "https://rerank.internal")
        monkeypatch.setenv("RERANKER_TOKEN", "hunter2")
        from docforge.config import Settings

        s = Settings()
        assert s.rerank_enabled is True
        assert s.rerank_model == "BAAI/bge-reranker-base"
        assert s.rerank_top_n == 25
        assert s.reranker_url == "https://rerank.internal"
        assert s.reranker_token.get_secret_value() == "hunter2"

    def test_enabled_without_url_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for var in self._RERANK_VARS:
            monkeypatch.delenv(var, raising=False)
        from docforge.config import Settings

        with pytest.raises(ValueError, match="reranker_url"):
            Settings(rerank_enabled=True)

    def test_url_set_without_token_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for var in self._RERANK_VARS:
            monkeypatch.delenv(var, raising=False)
        (tmp_path / "docforge.yml").write_text(
            "reranker_url: https://rerank.example\n",
            encoding="utf-8",
        )
        from docforge.config import Settings

        with pytest.raises(ValueError, match="reranker_token"):
            Settings()

    def test_top_n_above_max_rerank_batch_raises(self, tmp_path, monkeypatch):
        # rerank_top_n is hard-bounded by MAX_RERANK_BATCH (the sidecar's batch
        # cap), so a too-large value fails at construction rather than 502-ing
        # at query time once reranking is on.
        monkeypatch.chdir(tmp_path)
        for var in self._RERANK_VARS:
            monkeypatch.delenv(var, raising=False)
        from docforge.config import MAX_RERANK_BATCH, Settings

        with pytest.raises(ValueError):
            Settings(rerank_top_n=MAX_RERANK_BATCH + 1)

    def test_top_n_exceeding_pool_size_raises_when_rerank_enabled(self, tmp_path, monkeypatch):
        # The pool-size guard is gated on rerank_enabled, so the raise-case must
        # turn reranking ON (plus url + token to clear the other validators).
        monkeypatch.chdir(tmp_path)
        for var in self._RERANK_VARS:
            monkeypatch.delenv(var, raising=False)
        from docforge.config import Settings

        with pytest.raises(ValueError, match="rerank_top_n"):
            Settings(
                rerank_enabled=True,
                reranker_url="https://rerank.internal",
                reranker_token="hunter2",
                rerank_top_n=999,
            )

    def test_top_n_exceeding_pool_size_ignored_when_rerank_off(self, tmp_path, monkeypatch):
        # Lowering HYBRID_POOL_SIZE below the default rerank_top_n with rerank
        # OFF must NOT break startup — the guard only fires when reranking is on.
        monkeypatch.chdir(tmp_path)
        for var in self._RERANK_VARS:
            monkeypatch.delenv(var, raising=False)
        from docforge.config import Settings

        s = Settings(hybrid_pool_size=10)  # default rerank_top_n=50 > 10, rerank OFF
        assert s.rerank_enabled is False
        assert s.rerank_top_n == 50
        assert s.hybrid_pool_size == 10

    def test_top_n_zero_or_negative_raises(self, tmp_path, monkeypatch):
        # rerank_top_n is bounded ge=1 so 0/negative fail loud at construction.
        monkeypatch.chdir(tmp_path)
        for var in self._RERANK_VARS:
            monkeypatch.delenv(var, raising=False)
        from docforge.config import Settings

        with pytest.raises(ValueError, match="rerank_top_n"):
            Settings(rerank_top_n=0)
        with pytest.raises(ValueError, match="rerank_top_n"):
            Settings(rerank_top_n=-1)

    def test_token_secretstr_not_in_repr(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for var in self._RERANK_VARS:
            monkeypatch.delenv(var, raising=False)
        from docforge.config import Settings

        s = Settings(reranker_token="secret-x")
        assert "secret-x" not in repr(s)


def test_hybrid_retrieval_defaults():
    """Hybrid retrieval Settings defaults match the design spec."""
    from docforge.config import Settings

    s = Settings()
    assert s.rrf_k == 60
    assert s.hybrid_pool_size == 100
    assert s.fts_language == "english"


def test_weighted_rrf_defaults():
    """Weighted RRF defaults at 1.0 == classic RRF behavior (the v0.5.0 default).

    Setting either to a non-1.0 value moves to weighted-RRF without changing
    the formula's structure. The defaults match the v0.5.0 ship state."""
    from docforge.config import Settings

    s = Settings()
    assert s.dense_weight == 1.0
    assert s.sparse_weight == 1.0


def test_embedder_defaults_match_qwen_migration():
    """Engine defaults reflect the v0.7.0 Qwen-4B migration."""
    from docforge.config import Settings

    s = Settings()
    assert s.embedding_model == "Qwen/Qwen3-Embedding-4B"
    assert s.embedding_dimensions == 1024


def test_sources_hygiene_defaults():
    """Defaults match the 2026-05-20 sources-hygiene spec."""
    from docforge.config import Settings

    s = Settings()
    assert s.legacy_path_substring == "legacy"
    assert s.stale_threshold_months == 36


def test_sources_hygiene_overrides_via_env(monkeypatch):
    """Both fields are pydantic-settings-overridable."""
    from docforge.config import Settings

    monkeypatch.setenv("LEGACY_PATH_SUBSTRING", "deprecated")
    monkeypatch.setenv("STALE_THRESHOLD_MONTHS", "12")
    s = Settings()
    assert s.legacy_path_substring == "deprecated"
    assert s.stale_threshold_months == 12


def test_sources_hygiene_disabled_via_none():
    """Setting to None disables the rule. Empty-string env-var behavior is
    handled by the consumer (see test_disabled_via_empty_string_kwarg in
    test_git_crawler.py)."""
    from docforge.config import Settings

    s = Settings(legacy_path_substring=None, stale_threshold_months=None)
    assert s.legacy_path_substring is None
    assert s.stale_threshold_months is None


def test_log_responses_defaults_false(monkeypatch):
    monkeypatch.delenv("LOG_RESPONSES", raising=False)
    from docforge.config import Settings

    assert Settings().log_responses is False


def test_log_responses_env_true(monkeypatch):
    monkeypatch.setenv("LOG_RESPONSES", "true")
    from docforge.config import Settings

    assert Settings().log_responses is True


class TestRerankFailOpenSettings:
    def test_defaults_are_fail_closed_and_60s(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for var in ("RERANK_FAIL_OPEN", "RERANK_TIMEOUT_SECONDS"):
            monkeypatch.delenv(var, raising=False)

        from docforge.config import Settings

        s = Settings()
        # Engine default stays fail-CLOSED for OSS — dw-docforge flips it on
        # via bicepparam. A wrong default would silently degrade recall for
        # every other deployment of the engine.
        assert s.rerank_fail_open is False
        assert s.rerank_timeout_seconds == pytest.approx(60.0)

    def test_env_overrides(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("RERANK_FAIL_OPEN", "true")
        monkeypatch.setenv("RERANK_TIMEOUT_SECONDS", "12")

        from docforge.config import Settings

        s = Settings()
        # Mirrors the prod bicepparam: RERANK_FAIL_OPEN='true', '12'.
        assert s.rerank_fail_open is True
        assert s.rerank_timeout_seconds == pytest.approx(12.0)
