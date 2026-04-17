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
