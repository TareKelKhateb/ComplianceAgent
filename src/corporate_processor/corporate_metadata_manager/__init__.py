"""
__init__.py
-----------
Public exports for the corporate_metadata_manager package.
Teammates only need: from src.corporate_processor.corporate_metadata_manager import CorporateChunkStore
"""
from .corporate_store import CorporateChunkStore
from .models import (
    CorporateChunkInput,
    StoredCorporateChunk,
    ChunkStorageResult,
    ChunkBatchResult,
)

__all__ = [
    "CorporateChunkStore",
    "CorporateChunkInput",
    "StoredCorporateChunk",
    "ChunkStorageResult",
    "ChunkBatchResult",
]
