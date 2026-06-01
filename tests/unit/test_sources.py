from docforge.sources import load_sources


class TestLoadSources:
    def test_loads_confluence_source(self, tmp_path):
        yml = tmp_path / "sources.yml"
        yml.write_text(
            "sources:\n"
            "  - type: confluence_page\n"
            '    page_id: "123"\n'
            "    space_key: HEL\n"
            '    title: "Test Page"\n'
        )
        sources = load_sources(yml)
        assert len(sources) == 1
        assert sources[0].type == "confluence_page"
        assert sources[0].page_id == "123"

    def test_loads_git_repo_source(self, tmp_path):
        yml = tmp_path / "sources.yml"
        yml.write_text(
            "sources:\n"
            "  - type: git_repo\n"
            '    repo_path: "E:/SomeRepo"\n'
            '    include_patterns: ["README.md", "CLAUDE.md"]\n'
            '    title: "SomeRepo"\n'
        )
        sources = load_sources(yml)
        assert len(sources) == 1
        assert sources[0].type == "git_repo"
        assert sources[0].repo_path == "E:/SomeRepo"

    def test_loads_mixed_sources(self, tmp_path):
        yml = tmp_path / "sources.yml"
        yml.write_text(
            "sources:\n"
            "  - type: confluence_page\n"
            '    page_id: "123"\n'
            "    space_key: HEL\n"
            '    title: "Confluence Page"\n'
            "  - type: git_repo\n"
            '    repo_path: "E:/Repo"\n'
            '    include_patterns: ["README.md"]\n'
            '    title: "Git Repo"\n'
        )
        sources = load_sources(yml)
        assert len(sources) == 2
        assert sources[0].type == "confluence_page"
        assert sources[1].type == "git_repo"


class TestTags:
    def test_tags_default_to_empty(self, tmp_path):
        yml = tmp_path / "sources.yml"
        yml.write_text(
            "sources:\n"
            "  - type: confluence_page\n"
            '    page_id: "1"\n'
            "    space_key: HEL\n"
            '    title: "Page"\n'
        )
        sources = load_sources(yml)
        assert sources[0].tags == []

    def test_confluence_tree_tags_default_to_empty(self, tmp_path):
        yml = tmp_path / "sources.yml"
        yml.write_text(
            "sources:\n"
            "  - type: confluence_tree\n"
            '    root_page_id: "1"\n'
            "    space_key: ProDev\n"
            '    title: "T"\n'
        )
        sources = load_sources(yml)
        assert sources[0].tags == []

    def test_tags_parsed_from_yaml(self, tmp_path):
        yml = tmp_path / "sources.yml"
        yml.write_text(
            "sources:\n"
            "  - type: confluence_page\n"
            '    page_id: "1"\n'
            "    space_key: HEL\n"
            '    title: "Page"\n'
            "    tags: [platform, cloud]\n"
            "  - type: git_repo\n"
            '    repo_path: "E:/repo"\n'
            "    include_patterns: [README.md]\n"
            '    title: "R"\n'
            "    tags: [org]\n"
        )
        sources = load_sources(yml)
        assert sources[0].tags == ["platform", "cloud"]
        assert sources[1].tags == ["org"]


def test_load_sources_handles_utf8_titles(tmp_path, monkeypatch):
    """Regression: sources.yml with non-ASCII titles (emoji, em-dash) must
    load on systems whose default locale is not UTF-8 (Windows cp1252)."""
    yml = tmp_path / "sources.yml"
    yml.write_text(
        "sources:\n"
        "  - type: confluence_page\n"
        '    page_id: "1"\n'
        "    space_key: HEL\n"
        '    title: "\U0001f3af Light-Year Strategy — em-dash"\n'
        "    tags: [org]\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("locale.getpreferredencoding", lambda do_setlocale=True: "ascii")

    sources = load_sources(yml)
    assert len(sources) == 1
    assert sources[0].title == "\U0001f3af Light-Year Strategy — em-dash"


class TestConfluenceTreeSource:
    def test_loads_confluence_tree_source(self, tmp_path):
        yml = tmp_path / "sources.yml"
        yml.write_text(
            "sources:\n"
            "  - type: confluence_tree\n"
            '    root_page_id: "6540493502"\n'
            "    space_key: ProDev\n"
            '    title: "ProDev: Product Documentation"\n'
            "    tags: [productdev]\n"
        )
        sources = load_sources(yml)
        assert len(sources) == 1
        s = sources[0]
        assert s.type == "confluence_tree"
        assert s.root_page_id == "6540493502"
        assert s.space_key == "ProDev"
        assert s.title == "ProDev: Product Documentation"
        assert s.tags == ["productdev"]
        assert s.stale_months == 24  # default

    def test_confluence_tree_stale_months_override_and_none(self, tmp_path):
        yml = tmp_path / "sources.yml"
        yml.write_text(
            "sources:\n"
            "  - type: confluence_tree\n"
            '    root_page_id: "1"\n'
            "    space_key: ProDev\n"
            '    title: "All"\n'
            "    stale_months: null\n"
            "  - type: confluence_tree\n"
            '    root_page_id: "2"\n'
            "    space_key: ProDev\n"
            '    title: "Recent"\n'
            "    stale_months: 12\n"
        )
        sources = load_sources(yml)
        assert sources[0].stale_months is None
        assert sources[1].stale_months == 12

    def test_stale_months_rejects_zero_and_negative(self, tmp_path):
        import pytest
        from pydantic import ValidationError

        for bad in (0, -1):
            yml = tmp_path / "sources.yml"
            yml.write_text(
                "sources:\n"
                "  - type: confluence_tree\n"
                '    root_page_id: "1"\n'
                "    space_key: ProDev\n"
                '    title: "T"\n'
                f"    stale_months: {bad}\n"
            )
            with pytest.raises(ValidationError):
                load_sources(yml)
