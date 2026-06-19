"""
Embedding-based Semantic Chunker for Internal Documents
========================================================

Splits text into semantically coherent chunks using sentence-embedding
similarity rather than article-header regex patterns.

How it works:
  1. Split the full text into sentences (or small paragraph blocks).
  2. Compute an embedding vector for each sentence.
  3. Walk through consecutive sentence pairs and measure cosine similarity.
  4. When similarity drops below a configurable threshold, start a new chunk.
  5. Merge tiny residual fragments into their predecessor.

This chunker is designed for **internal company documents** (policies,
procedures, memos) that lack the structured "Article N" headers found in
published laws. External/general-law documents should still use the
header-aware ``SemanticChunker``.

NOTE: The embedding model is lazily loaded on first call so that importing
this module does not trigger a heavy download at startup.
"""

import logging
import re
from typing import Any, Dict, List, Optional

import numpy as np

from .base_chunker import BaseChunker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentence splitter — covers Arabic period (۔), western period, !, ?, and
# common Markdown line breaks.  Preserves the delimiter at the end of each
# sentence so that rejoined text is lossless.
# ---------------------------------------------------------------------------
_SENTENCE_SPLIT_RE = re.compile(
    r"(?<=[.!?؟۔\n])\s+"
)


def _split_sentences(text: str, min_length: int = 20) -> List[str]:
    """Split *text* into sentences, merging fragments shorter than *min_length*."""
    raw = _SENTENCE_SPLIT_RE.split(text.strip())
    sentences: List[str] = []
    for s in raw:
        s = s.strip()
        if not s:
            continue
        # Merge tiny fragments into the previous sentence
        if sentences and len(s) < min_length:
            sentences[-1] += " " + s
        else:
            sentences.append(s)
    return sentences


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1-D vectors."""
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 0.0
    return float(dot / norm)


class EmbeddingSemanticChunker(BaseChunker):
    """
    Embedding-similarity semantic chunker for internal documents.

    Parameters
    ----------
    model_name : str
        Sentence-transformer model identifier.  Defaults to a small
        multilingual model suitable for Arabic + English.
    similarity_threshold : float
        Cosine-similarity breakpoint.  Consecutive sentences whose
        similarity falls **below** this value trigger a chunk boundary.
    max_chunk_words : int
        Hard upper limit on words per chunk.  If a semantically coherent
        block exceeds this, it is force-split at the limit.
    min_chunk_words : int
        Chunks shorter than this are merged into the previous one.
    """

    # Lazy singleton — shared across instances so the model is loaded once.
    _model = None
    _model_name_loaded: Optional[str] = None

    def __init__(
        self,
        model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        similarity_threshold: float = 0.45,
        max_chunk_words: int = 500,
        min_chunk_words: int = 30,
    ) -> None:
        self.model_name = model_name
        self.similarity_threshold = similarity_threshold
        self.max_chunk_words = max_chunk_words
        self.min_chunk_words = min_chunk_words

    # ------------------------------------------------------------------
    # Lazy model loader
    # ------------------------------------------------------------------
    def _ensure_model(self) -> None:
        """Load the sentence-transformer model on first use."""
        if (
            EmbeddingSemanticChunker._model is not None
            and EmbeddingSemanticChunker._model_name_loaded == self.model_name
        ):
            return  # already loaded

        logger.info(
            "EmbeddingSemanticChunker: Loading model '%s' …", self.model_name
        )
        try:
            from sentence_transformers import SentenceTransformer

            EmbeddingSemanticChunker._model = SentenceTransformer(self.model_name)
            EmbeddingSemanticChunker._model_name_loaded = self.model_name
            logger.info("EmbeddingSemanticChunker: Model loaded successfully.")
        except ImportError:
            logger.error(
                "sentence-transformers is not installed. "
                "Run: pip install sentence-transformers"
            )
            raise
        except Exception as exc:
            logger.error(
                "Failed to load sentence-transformer model '%s': %s",
                self.model_name,
                exc,
            )
            raise

    # ------------------------------------------------------------------
    # Embedding helper
    # ------------------------------------------------------------------
    def _embed(self, texts: List[str]) -> np.ndarray:
        """Return (N, D) embedding matrix for *texts*."""
        self._ensure_model()
        return EmbeddingSemanticChunker._model.encode(
            texts, show_progress_bar=False, convert_to_numpy=True
        )

    # ------------------------------------------------------------------
    # BaseChunker contract
    # ------------------------------------------------------------------
    def create_chunks(self, full_text: str, doc_id: str) -> List[Dict[str, Any]]:
        """
        Split *full_text* into semantically coherent chunks.

        Args:
            full_text: Complete extracted text (Markdown or plain).
            doc_id:    Parent document identifier.

        Returns:
            List of chunk dicts matching the BaseChunker schema.
        """
        if not isinstance(full_text, str) or not full_text.strip():
            raise ValueError(
                f"full_text must be a non-empty string, got: {full_text!r}"
            )

        logger.info(
            "EmbeddingSemanticChunker: Processing doc_id=%s (%d chars)…",
            doc_id,
            len(full_text),
        )

        # 1. Split into sentences
        sentences = _split_sentences(full_text)
        if not sentences:
            logger.warning(
                "EmbeddingSemanticChunker: No sentences found for doc_id=%s",
                doc_id,
            )
            return []

        logger.debug(
            "EmbeddingSemanticChunker: %d sentence(s) extracted.", len(sentences)
        )

        # 2. Compute embeddings
        embeddings = self._embed(sentences)

        # 3. Walk pairs and find breakpoints
        groups: List[List[str]] = [[sentences[0]]]
        for i in range(1, len(sentences)):
            sim = _cosine_similarity(embeddings[i - 1], embeddings[i])

            # Check word count of current group
            current_words = sum(len(s.split()) for s in groups[-1])

            if sim < self.similarity_threshold or current_words >= self.max_chunk_words:
                # Start a new group
                groups.append([sentences[i]])
            else:
                groups[-1].append(sentences[i])

        # 4. Merge tiny trailing groups
        merged: List[str] = []
        for group in groups:
            content = " ".join(group).strip()
            word_count = len(content.split())

            if merged and word_count < self.min_chunk_words:
                merged[-1] += " " + content
            else:
                merged.append(content)

        # 5. Build output dicts
        chunks: List[Dict[str, Any]] = []
        for idx, content in enumerate(merged):
            chunks.append(
                {
                    "doc_id": doc_id,
                    "chunk_index": idx,
                    "content": content,
                    "metadata": {
                        "type": "embedding_semantic_block",
                        "word_count": len(content.split()),
                    },
                }
            )

        logger.info(
            "EmbeddingSemanticChunker: doc_id=%s — %d chunks created "
            "from %d sentences (threshold=%.2f).",
            doc_id,
            len(chunks),
            len(sentences),
            self.similarity_threshold,
        )

        return chunks
