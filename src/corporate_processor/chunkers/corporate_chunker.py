"""
corporate_chunker.py
--------------------
Concrete chunker strategies and the get_chunker() factory function.

Strategies
----------
- LLMRefiner     : Refines each chunk via a local Ollama LLM call.
- SemanticRefiner: Placeholder for embedding-based semantic refinement.
- PassthroughRefiner: Returns the chunk unchanged (strategy='none').

Usage
-----
    from src.corporate_processor.chunkers.corporate_chunker import get_chunker

    chunker = get_chunker(Config.CHUNK_REFINEMENT_STRATEGY)
    refined  = chunker.refine_chunk(raw_text)
"""

import logging
import tempfile
import os
from typing import List

import requests

from src.corporate_processor.chunkers.base_chunker import BaseChunker
from src.corporate_processor.chunkers.config import Config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ── Concrete Strategies ────────────────────────────────────────────────────────

class LLMRefiner(BaseChunker):
    """
    Refines text chunks by sending them to a locally-hosted Ollama LLM.

    Falls back gracefully to the original content if the LLM is
    unreachable or returns an empty response.
    """

    def __init__(self) -> None:
        self.config = Config()

    def refine_chunk(self, content: str) -> str:
        """
        Sends the chunk to Ollama for professional Arabic-language refinement.

        Args:
            content: Raw chunk text.

        Returns:
            LLM-refined text, or the original content on any error.
        """
        if not isinstance(content, str):
            logger.error("Validation Error: Content provided for refinement is not a string.")
            return content

        logger.info("Sending chunk to Ollama for refinement (length: %d chars)", len(content))

        try:
            prompt = (
                "You are a professional corporate compliance assistant. "
                "If the text is already perfectly formatted and clear, return it as is without changes. "
                "Otherwise, refine it for clarity and tone while maintaining Markdown structure, "
                "and ALWAYS respond in Arabic.\n"
                "Output ONLY the refined text.\n"
                f"Text to refine: {content}"
            )

            payload = {
                "model": self.config.LLM_MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": self.config.LLM_TEMPERATURE,
                },
            }

            response = requests.post(self.config.LLM_BASE_URL, json=payload, timeout=120)
            response.raise_for_status()

            response_data = response.json()
            refined_content: str = response_data.get("response", "")

            if not refined_content:
                logger.warning("Ollama returned an empty response. Returning original content.")
                return content

            return refined_content.strip()

        except requests.exceptions.RequestException as e:
            logger.warning(
                "Ollama instance unreachable or API error: %s. Returning original content.", e
            )
            return content
        except Exception as e:
            logger.error(
                "Unexpected error during LLM refinement: %s. Returning original content.", e
            )
            return content


class SemanticRefiner(BaseChunker):
    """
    Embedding-based semantic refinement strategy.

    This is a structured placeholder.  The embedding / clustering logic
    should be added inside `refine_chunk` once the embedding model is chosen.

    Suggested implementation steps
    --------------------------------
    1. Load a sentence-transformer model (e.g. ``sentence-transformers``).
    2. Encode `content` into a dense vector.
    3. Compare against neighbouring chunk vectors and merge/split accordingly.
    4. Return the semantically-adjusted chunk text.
    """

    def __init__(self) -> None:
        # TODO: initialise your embedding model here, e.g.
        # from sentence_transformers import SentenceTransformer
        # self.model = SentenceTransformer("BAAI/bge-m3")
        logger.info("SemanticRefiner initialised (placeholder — no embedding model loaded).")

    def refine_chunk(self, content: str) -> str:
        """
        Placeholder: returns the original content unchanged.

        Replace the body of this method with real semantic refinement logic.

        Args:
            content: Raw chunk text.

        Returns:
            Semantically-refined text (currently a pass-through).
        """
        if not isinstance(content, str):
            logger.error("Validation Error: Content provided for refinement is not a string.")
            return content

        logger.debug("SemanticRefiner.refine_chunk called — returning original content (stub).")
        # ──────────────────────────────────────────────────
        # TODO: implement embedding-based refinement here.
        # ──────────────────────────────────────────────────
        return content


class PassthroughRefiner(BaseChunker):
    """
    No-op refinement strategy (strategy='none').

    Returns every chunk exactly as received — useful for debugging
    or when downstream consumers handle their own refinement.
    """

    def refine_chunk(self, content: str) -> str:
        """
        Returns the chunk unchanged.

        Args:
            content: Raw chunk text.

        Returns:
            The same text with no modifications.
        """
        if not isinstance(content, str):
            logger.error("Validation Error: Content provided for refinement is not a string.")
            return content

        logger.debug("PassthroughRefiner.refine_chunk called — returning original content.")
        return content


# ── Factory Function ───────────────────────────────────────────────────────────

def get_chunker(strategy: str) -> BaseChunker:
    """
    Factory function that returns the appropriate BaseChunker instance.

    Args:
        strategy: One of ``'llm'``, ``'semantic'``, or ``'none'``.

    Returns:
        A concrete :class:`BaseChunker` implementation.

    Raises:
        ValueError: If *strategy* is not a recognised value.
    """
    strategy = strategy.strip().lower()

    _registry: dict[str, type[BaseChunker]] = {
        "llm": LLMRefiner,
        "semantic": SemanticRefiner,
        "none": PassthroughRefiner,
    }

    if strategy not in _registry:
        raise ValueError(
            f"Unknown chunking strategy: '{strategy}'. "
            f"Allowed values are: {sorted(_registry.keys())}"
        )

    logger.info("get_chunker: initialising strategy='%s'", strategy)
    return _registry[strategy]()


# ── Backward-compatible alias ──────────────────────────────────────────────────

class CorporateChunker(LLMRefiner):
    """
    Backward-compatible alias for code that still imports CorporateChunker directly.

    New code should prefer :func:`get_chunker` with an explicit strategy.
    """


# ── Demo / smoke-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile

    demo_text = """## Financial Performance 2023
The company achieved a total revenue of $14.5M, representing an 8% year-over-year growth.
Net margins remained stable at 12.4%.

### Legal Disclaimer
Under Section 4.A (Liability), the corporation assumes no responsibility for third-party damages.
Please refer to the compliance mandate 2023-A."""

    logger.info("Starting Corporate Chunker Demo...")

    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, encoding="utf-8", suffix=".txt"
    ) as tmp:
        tmp.write(demo_text)
        tmp_path = tmp.name

    try:
        logger.info("Reading content from file: %s", tmp_path)
        with open(tmp_path, "r", encoding="utf-8") as f:
            file_content = f.read()

        # Validate config before use
        Config.validate()

        chunker = get_chunker(Config.CHUNK_REFINEMENT_STRATEGY)
        logger.info("Active strategy: %s", type(chunker).__name__)

        logger.info("Splitting text by headers...")
        chunks: List[str] = chunker.split_text_by_headers(file_content)
        logger.info("Generated %d chunks.", len(chunks))

        for i, chunk in enumerate(chunks, start=1):
            logger.info("--- Processing Chunk %d ---", i)
            refined_result = chunker.refine_chunk(chunk)
            logger.info("Refined Output for Chunk %d:\n%s\n", i, refined_result)

    finally:
        os.remove(tmp_path)
        logger.info("Demo complete. Temporary files cleaned up.")
