from docforge.processors.parser import parse_confluence_html


class TestParseConfluenceHtml:
    def test_simple_headings_and_paragraphs(self):
        html = (
            "<h2>Overview</h2><p>This is the overview.</p><h2>Details</h2><p>These are details.</p>"
        )
        sections = parse_confluence_html(html)

        assert len(sections) == 2
        assert sections[0].title == "Overview"
        assert "This is the overview." in sections[0].text
        assert sections[1].title == "Details"
        assert "These are details." in sections[1].text

    def test_empty_html(self):
        sections = parse_confluence_html("")
        assert sections == []

    def test_no_headings(self):
        html = "<p>Just a paragraph.</p><p>And another.</p>"
        sections = parse_confluence_html(html)

        assert len(sections) == 1
        assert "Just a paragraph." in sections[0].text
        assert sections[0].title == ""

    def test_table_conversion(self):
        html = """
        <table>
            <tr><th>Team</th><th>Responsibility</th></tr>
            <tr><td>Platform</td><td>Organization Lifecycle</td></tr>
            <tr><td>Imaging</td><td>Document Rendering</td></tr>
        </table>
        """
        sections = parse_confluence_html(html)

        assert len(sections) == 1
        text = sections[0].text
        assert "Platform" in text
        assert "Organization Lifecycle" in text

    def test_smartlink_macro(self):
        html = (
            '<p>See <custom data-type="smartlink" data-id="id-1">'
            "https://example.com/page</custom> for details.</p>"
        )
        sections = parse_confluence_html(html)

        assert len(sections) == 1
        assert "https://example.com/page" in sections[0].text

    def test_status_macro(self):
        html = (
            '<p><custom data-type="status" data-id="id-0">Work in progress</custom>'
            " This is draft content.</p>"
        )
        sections = parse_confluence_html(html)

        assert len(sections) == 1
        assert "[Work in progress]" in sections[0].text

    def test_emoji_macro_stripped(self):
        html = (
            '<p><custom data-type="emoji" data-id="id-0">:arrow_down:</custom> Team info below.</p>'
        )
        sections = parse_confluence_html(html)

        assert len(sections) == 1
        assert ":arrow_down:" not in sections[0].text
        assert "Team info below." in sections[0].text

    def test_empty_sections_dropped(self):
        html = "<h2>Empty Section</h2><h2>Non-empty</h2><p>Content here.</p>"
        sections = parse_confluence_html(html)

        assert len(sections) == 1
        assert sections[0].title == "Non-empty"

    def test_heading_levels(self):
        html = "<h1>Top</h1><p>Top content.</p><h3>Sub</h3><p>Sub content.</p>"
        sections = parse_confluence_html(html)

        assert len(sections) == 2
        assert sections[0].level == 1
        assert sections[1].level == 3
