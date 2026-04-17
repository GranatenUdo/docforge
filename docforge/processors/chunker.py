"""Token-aware chunker — splits sections into chunks under a token limit."""

from __future__ import annotations

from dataclasses import dataclass

from docforge.processors.parser import Section


@dataclass
class Chunk:
    text: str
    section_title: str
    chunk_index: int


def chunk_sections(
    sections: list[Section],
    max_tokens: int = 500,
    tokenizer_fn: callable | None = None,
) -> list[Chunk]:
    """Split sections into chunks of roughly max_tokens size.

    Splits on section boundaries first, then on paragraph boundaries
    if a section exceeds max_tokens.

    Args:
        sections: Parsed sections from the document.
        max_tokens: Maximum tokens per chunk.
        tokenizer_fn: Function that counts tokens in a string.
                      If None, uses a simple word-count approximation
                      (1 token ~ 0.75 words).
    """
    if tokenizer_fn is None:
        tokenizer_fn = _approximate_token_count

    chunks: list[Chunk] = []
    chunk_index = 0

    for section in sections:
        text = section.text.strip()
        if not text:
            continue

        # Add section title as context prefix
        if section.title:
            text = f"{section.title}\n\n{text}"

        if tokenizer_fn(text) <= max_tokens:
            chunks.append(Chunk(text=text, section_title=section.title, chunk_index=chunk_index))
            chunk_index += 1
        else:
            # Split on paragraph boundaries
            sub_chunks = _split_by_paragraphs(text, max_tokens, tokenizer_fn)
            for sub_text in sub_chunks:
                chunks.append(
                    Chunk(text=sub_text, section_title=section.title, chunk_index=chunk_index)
                )
                chunk_index += 1

    return chunks


def _split_by_paragraphs(
    text: str, max_tokens: int, tokenizer_fn: callable
) -> list[str]:
    """Split text into chunks by paragraph boundaries."""
    paragraphs = text.split("\n")
    result: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        para_tokens = tokenizer_fn(paragraph)

        if para_tokens > max_tokens:
            # Flush current buffer
            if current_parts:
                result.append("\n".join(current_parts))
                current_parts = []
                current_tokens = 0

            # Split long paragraph by sentences
            for sentence_chunk in _split_long_text(paragraph, max_tokens, tokenizer_fn):
                result.append(sentence_chunk)
            continue

        if current_tokens + para_tokens > max_tokens and current_parts:
            result.append("\n".join(current_parts))
            current_parts = []
            current_tokens = 0

        current_parts.append(paragraph)
        current_tokens += para_tokens

    if current_parts:
        result.append("\n".join(current_parts))

    return result


def _split_long_text(text: str, max_tokens: int, tokenizer_fn: callable) -> list[str]:
    """Split text that exceeds max_tokens by sentence boundaries, falling back to words."""
    # Try splitting by sentences (period followed by space)
    sentences = text.replace(". ", ".\n").split("\n")

    result: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        sent_tokens = tokenizer_fn(sentence)

        if current_tokens + sent_tokens > max_tokens and current_parts:
            result.append(" ".join(current_parts))
            current_parts = []
            current_tokens = 0

        current_parts.append(sentence)
        current_tokens += sent_tokens

    if current_parts:
        result.append(" ".join(current_parts))

    return result


def _approximate_token_count(text: str) -> int:
    """Approximate token count using word count.

    Roughly 1 token ~ 0.75 words for English text.
    This is used as fallback when no model tokenizer is available.
    """
    words = len(text.split())
    return int(words / 0.75)
