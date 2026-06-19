"""
chunkers package
----------------
Public API for the corporate chunker module.

    from src.corporate_processor.chunkers import get_chunker, BaseChunker, Config

Strategy selection is driven by ``Config.CHUNK_REFINEMENT_STRATEGY``.
"""

from src.corporate_processor.chunkers.base_chunker import BaseChunker
from src.corporate_processor.chunkers.config import Config
from src.corporate_processor.chunkers.corporate_chunker import (
    LLMRefiner,
    SemanticRefiner,
    PassthroughRefiner,
    CorporateChunker,   # backward-compatible alias
    get_chunker,
)

__all__ = [
    "BaseChunker",
    "Config",
    "LLMRefiner",
    "SemanticRefiner",
    "PassthroughRefiner",
    "CorporateChunker",
    "get_chunker",
]
