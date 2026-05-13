"""
Unit tests for SemanticChunker.

Run with:
    pytest tests/document_processor/test_semantic_chunker.py -v
"""

import pytest

from src.document_processor.chunkers.semantic_chunker import (
    Chunk,
    ChunkMetadata,
    SemanticChunker,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

DOC_ID = 1


def make_chunker() -> SemanticChunker:
    return SemanticChunker()


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestNormalDocumentWithPreamble:
    """A typical document: preamble followed by numbered articles."""

    SAMPLE = """
This is the preamble of the regulation.
It may span several lines.

### Article 1

First article body.

### Article 2

Second article body with more text here.
""".strip()

    def test_chunk_count(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        # 1 preamble + 2 articles
        assert len(chunks) == 3

    def test_preamble_chunk(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        preamble = chunks[0]
        assert preamble.metadata.type == "preamble"
        assert preamble.metadata.header is None
        assert preamble.metadata.article_number is None
        assert preamble.metadata.word_count > 0

    def test_article_chunks(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        art1, art2 = chunks[1], chunks[2]
        assert art1.metadata.type == "article"
        assert art1.metadata.article_number == 1
        assert art2.metadata.article_number == 2

    def test_chunk_indices_sequential(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))

    def test_doc_id_propagated(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        assert all(c.doc_id == DOC_ID for c in chunks)

    def test_returns_list_of_chunk_models(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        assert all(isinstance(c, Chunk) for c in chunks)
        assert all(isinstance(c.metadata, ChunkMetadata) for c in chunks)


class TestDocumentNoPreamble:
    """Document that starts directly with an article (no leading text)."""

    SAMPLE = """### Article 1

Body of the first article.

### Article 2

Body of the second article.
""".strip()

    def test_no_preamble_chunk(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        types = [c.metadata.type for c in chunks]
        assert "preamble" not in types

    def test_correct_article_count(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        assert len(chunks) == 2

    def test_chunk_index_starts_at_zero(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        assert chunks[0].chunk_index == 0


class TestArabicHeaders:
    """Document with Arabic article headers."""

    SAMPLE = """ديباجة الوثيقة

### المادة 1

نص المادة الأولى.

### المادة 2

نص المادة الثانية.
بماده 3 نص المادة

""".strip()

    def test_arabic_language_detected(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        article_chunks = [c for c in chunks if c.metadata.type == "article"]
        assert all(c.metadata.language == "ar" for c in article_chunks)

    def test_arabic_article_numbers_extracted(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        article_chunks = [c for c in chunks if c.metadata.type == "article"]
        assert article_chunks[0].metadata.article_number == 1
        assert article_chunks[1].metadata.article_number == 2

    @pytest.mark.xfail(reason="preamble language hardcoded to 'en', bug not yet fixed")
    def test_preamble_language_detected_as_arabic(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        preamble = next(c for c in chunks if c.metadata.type == "preamble")
        assert preamble.metadata.language == "ar"

    def test_correct_article_count(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        assert len(chunks) == 3

    def test_doc_id_propagated(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        assert all(c.doc_id == DOC_ID for c in chunks)
    


class TestEmptyArticleBody:
    """
    When Article 1 has no body text and Article 2 follows immediately,
    the chunker should still produce two separate article chunks:
    Article 1 with an empty body and Article 2 with its body.
    A logger.warning containing "empty body" must be emitted for Article 1.
    """

    SAMPLE = """### Article 1

### Article 2

Has a body.
""".strip()

    def test_two_article_chunks_produced(self):
        """Empty-body article and the following article are two distinct chunks."""
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        assert len(chunks) == 2
        assert all(c.metadata.type == "article" for c in chunks)

    def test_article1_has_empty_body(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        art1 = next(c for c in chunks if c.metadata.article_number == 1)
        # Content should be just the header with no trailing body text
        assert "Has a body." not in art1.content

    def test_article1_word_count_reflects_header_only(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        art1 = next(c for c in chunks if c.metadata.article_number == 1)
        expected = len(art1.content.split())
        assert art1.metadata.word_count == expected

    def test_empty_body_logs_warning(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        assert "empty body" in caplog.text


class TestPageSeparatorCleanup:
    """Page-separator blocks should be stripped before chunking."""

    SAMPLE = (
        "Preamble text.\n\n"
        "---\n\n"
        "## Page 1\n\n"
        "1\n\n"
        "### Article 1\n\n"
        "Body after page separator."
    )

    def test_page_separator_stripped(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        for c in chunks:
            assert "## Page" not in c.content
            assert "---" not in c.content

    def test_article_body_intact(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        art = next(c for c in chunks if c.metadata.type == "article")
        assert "Body after page separator." in art.content


class TestWordCountMetadata:
    """word_count must reflect actual words in content."""

    SAMPLE = "### Article 3\n\nOne two three four five."

    def test_word_count_accuracy(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        art = chunks[0]
        expected = len("### Article 3\n\nOne two three four five.".split())
        assert art.metadata.word_count == expected

    def test_preamble_word_count_accuracy(self):
        sample = "This is a preamble.\n\n### Article 1\n\nBody."
        chunks = make_chunker().create_chunks(sample, DOC_ID)
        preamble = next(c for c in chunks if c.metadata.type == "preamble")
        expected = len("This is a preamble.".split())
        assert preamble.metadata.word_count == expected


# ---------------------------------------------------------------------------
# Mixed-language document tests
# ---------------------------------------------------------------------------


class TestMixedLanguageDocument:
    """Document with both Arabic and English article headers."""

    SAMPLE = """Preamble text.

### Article 1

English article body.

### المادة 2

Arabic article body.
""".strip()

    def test_english_article_language(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        art1 = next(c for c in chunks if c.metadata.article_number == 1)
        assert art1.metadata.language == "en"

    def test_arabic_article_language(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        art2 = next(c for c in chunks if c.metadata.article_number == 2)
        assert art2.metadata.language == "ar"

    def test_total_chunk_count(self):
        chunks = make_chunker().create_chunks(self.SAMPLE, DOC_ID)
        assert len(chunks) == 3  # 1 preamble + 2 articles


# ---------------------------------------------------------------------------
# Input-validation tests
# ---------------------------------------------------------------------------


class TestInputValidation:
    """create_chunks() must raise ValueError for bad inputs."""

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="non-empty string"):
            make_chunker().create_chunks("", DOC_ID)

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="non-empty string"):
            make_chunker().create_chunks("   \n\t  ", DOC_ID)

    def test_none_raises(self):
        with pytest.raises(ValueError, match="non-empty string"):
            make_chunker().create_chunks(None, DOC_ID)  # type: ignore[arg-type]

    def test_non_string_raises(self):
        with pytest.raises(ValueError, match="non-empty string"):
            make_chunker().create_chunks(42, DOC_ID)  # type: ignore[arg-type]

    def test_zero_doc_id_raises(self):
        with pytest.raises(ValueError, match="positive integer"):
            make_chunker().create_chunks("### Article 1\n\nBody.", 0)

    def test_negative_doc_id_raises(self):
        with pytest.raises(ValueError, match="positive integer"):
            make_chunker().create_chunks("### Article 1\n\nBody.", -5)

    def test_float_doc_id_raises(self):
        with pytest.raises(ValueError, match="positive integer"):
            make_chunker().create_chunks("### Article 1\n\nBody.", 1.0)  # type: ignore[arg-type]
