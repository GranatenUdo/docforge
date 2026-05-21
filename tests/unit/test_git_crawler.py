from docforge.crawlers.git import crawl_repo


class TestCrawlRepo:
    def test_finds_readme(self, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("# My Project\n\nThis is a test project.")

        results = crawl_repo(str(tmp_path), include_patterns=["README.md"])

        assert len(results) == 1
        assert results[0].title == "README.md"
        assert "My Project" in results[0].content
        assert results[0].content_hash is not None

    def test_finds_docs_directory(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "arch.md").write_text("# Architecture\n\nSystem design.")
        (docs / "deploy.md").write_text("# Deployment\n\nHow to deploy.")

        results = crawl_repo(str(tmp_path), include_patterns=["docs/**/*.md"])

        assert len(results) == 2
        titles = {r.title for r in results}
        assert "docs\\arch.md" in titles or "docs/arch.md" in titles
        assert "docs\\deploy.md" in titles or "docs/deploy.md" in titles

    def test_skips_missing_files(self, tmp_path):
        results = crawl_repo(str(tmp_path), include_patterns=["README.md"])
        assert results == []

    def test_computes_content_hash(self, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("content")

        results = crawl_repo(str(tmp_path), include_patterns=["README.md"])

        assert len(results[0].content_hash) == 64  # SHA-256 hex

    def test_skips_empty_files(self, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("")

        results = crawl_repo(str(tmp_path), include_patterns=["README.md"])
        assert results == []

    def test_nonexistent_repo_path(self):
        results = crawl_repo("E:/nonexistent/path", include_patterns=["README.md"])
        assert results == []


class TestPathNormalization:
    """Rule 2: file_path and title use forward-slash regardless of OS."""

    def test_nested_path_uses_forward_slash(self, tmp_path):
        nested = tmp_path / "docs" / "sub" / "file.md"
        nested.parent.mkdir(parents=True)
        nested.write_text("content")

        results = crawl_repo(str(tmp_path), include_patterns=["docs/**/*.md"])

        assert len(results) == 1
        # Both file_path and title must use forward slashes
        assert results[0].file_path == "docs/sub/file.md"
        assert results[0].title == "docs/sub/file.md"
        # No backslashes anywhere in the title / file_path
        assert "\\" not in results[0].file_path
        assert "\\" not in results[0].title


class TestLegacyPrefix:
    """Rule 3: title gets '[LEGACY] ' prefix when path contains 'legacy'."""

    def test_legacy_folder_path_gets_prefix(self, tmp_path):
        legacy = tmp_path / "docs" / "_legacy-components-descriptions" / "host" / "foo.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("# Legacy foo")

        # Default legacy_path_substring is "legacy"
        results = crawl_repo(str(tmp_path), include_patterns=["docs/**/*.md"])

        assert len(results) == 1
        assert results[0].title.startswith("[LEGACY] ")
        assert "docs/_legacy-components-descriptions/host/foo.md" in results[0].title
        # file_path is unprefixed (used for hashing/identity)
        assert not results[0].file_path.startswith("[LEGACY]")
        assert results[0].file_path == "docs/_legacy-components-descriptions/host/foo.md"

    def test_non_legacy_path_no_prefix(self, tmp_path):
        non_legacy = tmp_path / "docs" / "architecture-records" / "cache" / "shards.md"
        non_legacy.parent.mkdir(parents=True)
        non_legacy.write_text("# Cache")

        results = crawl_repo(str(tmp_path), include_patterns=["docs/**/*.md"])

        assert len(results) == 1
        assert not results[0].title.startswith("[LEGACY]")

    def test_case_insensitive_match(self, tmp_path):
        upper = tmp_path / "docs" / "LEGACY" / "x.md"
        upper.parent.mkdir(parents=True)
        upper.write_text("uppercase legacy folder")

        results = crawl_repo(str(tmp_path), include_patterns=["docs/**/*.md"])

        assert len(results) == 1
        assert results[0].title.startswith("[LEGACY] ")

    def test_disabled_via_none_kwarg(self, tmp_path):
        """When legacy_path_substring=None, no prefix is applied even for legacy paths."""
        legacy = tmp_path / "docs" / "_legacy" / "foo.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("# foo")

        results = crawl_repo(
            str(tmp_path),
            include_patterns=["docs/**/*.md"],
            legacy_path_substring=None,
        )

        assert len(results) == 1
        assert not results[0].title.startswith("[LEGACY]")

    def test_disabled_via_empty_string_kwarg(self, tmp_path):
        """Empty string is also treated as disabled — matches how pydantic-settings
        env-var loading produces empty strings for unset string-typed settings."""
        legacy = tmp_path / "docs" / "_legacy" / "foo.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("# foo")

        results = crawl_repo(
            str(tmp_path),
            include_patterns=["docs/**/*.md"],
            legacy_path_substring="",
        )

        assert len(results) == 1
        assert not results[0].title.startswith("[LEGACY]")

    def test_custom_substring(self, tmp_path):
        deprecated = tmp_path / "docs" / "_deprecated" / "x.md"
        deprecated.parent.mkdir(parents=True)
        deprecated.write_text("old")

        results = crawl_repo(
            str(tmp_path),
            include_patterns=["docs/**/*.md"],
            legacy_path_substring="deprecated",
        )

        assert len(results) == 1
        assert results[0].title.startswith("[LEGACY] ")
