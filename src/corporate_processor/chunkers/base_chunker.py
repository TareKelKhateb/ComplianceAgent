"""
base_chunker.py
---------------
Abstract Base Class for all chunking / refinement strategies.

Every concrete strategy must:
  1. Inherit from BaseChunker.
  2. Implement the `refine_chunk` abstract method.

The shared `split_text_by_headers` logic lives here so it is inherited
by every strategy without duplication.
"""

import re
import logging
from abc import ABC, abstractmethod
from typing import List

logger = logging.getLogger(__name__)


class BaseChunker(ABC):
    """
    Abstract base class that defines the chunker contract.

    Subclasses implement the `refine_chunk` method to apply their own
    refinement logic (LLM-based, embedding-based, or pass-through).
    """

    # ── Shared splitting logic ────────────────────────────────────────────────

    def split_text_by_headers(self, text: str) -> List[str]:
        """
        Splits text by Markdown headers (##, ###, ####) and applies
        semantic merging to prevent over-chunking and data fragmentation.

        Args:
            text: Raw document text, optionally containing Markdown headers.

        Returns:
            A list of meaningful, non-trivial text chunks.
        """
        if not isinstance(text, str):
            logger.error("Validation Error: Provided text is not a string.")
            return []

        # ── Step 1: Initial split on Markdown headers ─────────────────────
        raw_chunks = re.split(r'\n(?=#{2,4}\s)', text)
        raw_chunks = [chunk.strip() for chunk in raw_chunks if chunk.strip()]

        merged_chunks: List[str] = []

        for chunk in raw_chunks:
            # Strip Markdown markers for content-only analysis
            plain_text = re.sub(r'#+\s*', '', chunk).strip()

            # ── Step 2: Discard metadata-only chunks ──────────────────────
            # e.g. "## صفحة 3" or extremely short strings (<10 chars)
            if (
                re.match(r'^(صفحة|page)\s*\d+$', plain_text, re.IGNORECASE)
                or len(plain_text) < 10
            ):
                logger.debug("Discarding metadata-only chunk: %s", chunk)
                continue

            # ── Step 3: Minimum content threshold ─────────────────────────
            # Chunks under 100 chars lack full semantic context; merge backward.
            if len(chunk) < 100 and merged_chunks:
                logger.debug("Merging short chunk (<100 chars) with previous: %s", chunk)
                merged_chunks[-1] += "\n\n" + chunk
            else:
                merged_chunks.append(chunk)

        # ── Step 4: Forward-merge isolated headings ───────────────────────
        # A heading with no body text is merged with the next chunk.
        final_chunks: List[str] = []
        i = 0
        while i < len(merged_chunks):
            current = merged_chunks[i]
            if current.startswith('#') and len(current) < 150 and i < len(merged_chunks) - 1:
                logger.debug("Forward merging isolated heading: %s", current)
                final_chunks.append(current + "\n\n" + merged_chunks[i + 1])
                i += 2
            else:
                final_chunks.append(current)
                i += 1

        return final_chunks

    # ── Abstract refinement contract ──────────────────────────────────────────

    @abstractmethod
    def refine_chunk(self, content: str) -> str:
        """
        Refine a single text chunk using the strategy's specific logic.

        Args:
            content: The raw chunk text to refine.

        Returns:
            The refined (or unchanged) chunk text.
        """
        ...
