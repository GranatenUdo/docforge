from docforge.processors.chunker import _approximate_token_count, chunk_sections
from docforge.processors.parser import Section


def _word_tokenizer(text: str) -> int:
    """Simple word-count tokenizer for deterministic testing."""
    return len(text.split())


class TestChunkSections:
    def test_single_small_section(self):
        sections = [Section(title="Intro", text="A short paragraph.", level=2)]
        chunks = chunk_sections(sections, max_tokens=100, tokenizer_fn=_word_tokenizer)

        assert len(chunks) == 1
        assert "Intro" in chunks[0].text
        assert "A short paragraph." in chunks[0].text
        assert chunks[0].chunk_index == 0

    def test_multiple_small_sections(self):
        sections = [
            Section(title="A", text="First section.", level=2),
            Section(title="B", text="Second section.", level=2),
        ]
        chunks = chunk_sections(sections, max_tokens=100, tokenizer_fn=_word_tokenizer)

        assert len(chunks) == 2
        assert chunks[0].section_title == "A"
        assert chunks[1].section_title == "B"

    def test_large_section_splits(self):
        long_text = " ".join(["word"] * 200)
        sections = [Section(title="Big", text=long_text, level=2)]
        chunks = chunk_sections(sections, max_tokens=50, tokenizer_fn=_word_tokenizer)

        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.section_title == "Big"

    def test_empty_sections_skipped(self):
        sections = [
            Section(title="Empty", text="", level=2),
            Section(title="Content", text="Has content.", level=2),
        ]
        chunks = chunk_sections(sections, max_tokens=100, tokenizer_fn=_word_tokenizer)

        assert len(chunks) == 1
        assert chunks[0].section_title == "Content"

    def test_chunk_indices_sequential(self):
        sections = [
            Section(title="A", text="First.", level=2),
            Section(title="B", text="Second.", level=2),
            Section(title="C", text="Third.", level=2),
        ]
        chunks = chunk_sections(sections, max_tokens=100, tokenizer_fn=_word_tokenizer)

        indices = [c.chunk_index for c in chunks]
        assert indices == [0, 1, 2]


class TestApproximateTokenCount:
    def test_empty_string(self):
        assert _approximate_token_count("") == 0

    def test_single_word(self):
        count = _approximate_token_count("hello")
        assert count >= 1

    def test_sentence(self):
        count = _approximate_token_count("This is a simple test sentence with eight words")
        # 8 words / 0.75 ≈ 10.67 → 10
        assert 8 <= count <= 14
