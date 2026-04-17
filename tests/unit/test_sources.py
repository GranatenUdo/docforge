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

    def test_tags_parsed_from_yaml(self, tmp_path):
        yml = tmp_path / "sources.yml"
        yml.write_text(
            "sources:\n"
            "  - type: confluence_page\n"
            '    page_id: "1"\n'
            "    space_key: HEL\n"
            '    title: "Page"\n'
            "    tags: [ccl, cloud]\n"
            "  - type: git_repo\n"
            '    repo_path: "E:/repo"\n'
            "    include_patterns: [README.md]\n"
            '    title: "R"\n'
            "    tags: [org]\n"
        )
        sources = load_sources(yml)
        assert sources[0].tags == ["ccl", "cloud"]
        assert sources[1].tags == ["org"]
