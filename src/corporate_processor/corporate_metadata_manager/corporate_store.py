"""
corporate_store.py
------------------
THE ONLY FILE YOUR TEAMMATES NEED TO IMPORT.

This is the public interface for the corporate_chunks storage layer.
It mirrors the MetadataStore class from metadata_manager/metadata_store.py
but is adapted for CorporateChunker output.

QUICKSTART:
    from src.corporate_processor.corporate_metadata_manager.corporate_store import CorporateChunkStore

    store = CorporateChunkStore()

    # Insert a batch of refined chunks from ChunkOrchestrator
    result = store.insert_chunks_batch(
        doc_id="2016_580ab4",
        chunks=[{"chunk_index": 0, "content": "...refined..."}],
        metadata={"title": "...", "category": "Financial"}
    )
    print(result.success)          # True
    print(result.data.inserted_count)  # 2
"""

import os
from typing import List, Optional

from .db import (
    init_db,
    check_chunk_hash,
    insert_chunk,
    insert_chunks_batch,
    update_chunk_embedding,
    get_chunk_by_id,
    get_chunks_by_doc_id,
    get_chunks_without_embeddings,
    delete_chunks_by_doc_id,
)
from .models import ChunkStorageResult, StoredCorporateChunk, ChunkBatchResult


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROOT_DIR        = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DEFAULT_DB_PATH = os.path.join(ROOT_DIR, "data", "corporate_chunks.db")


class CorporateChunkStore:
    """
    Full CRUD storage layer for LLM-refined corporate chunks.
    Instantiate once and reuse across your pipeline.

        store = CorporateChunkStore()                       # default path
        store = CorporateChunkStore(db_path="custom.db")   # custom path
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        init_db(self.db_path)   # Ensures schema exists / evolves safely

    # =======================================================================
    # INSERT
    # =======================================================================

    def insert_chunk(self, doc_id: str, chunk_index: int, content: str, metadata: dict = None) -> ChunkStorageResult:
        """
        Insert a single LLM-refined chunk.

        Args:
            doc_id:      Source document identifier.
            chunk_index: Position of this chunk in the document.
            content:     LLM-refined text from CorporateChunker.
            metadata:    Full document metadata dict (stored as JSON context).

        Deduplication:
            If a chunk with identical content already exists (same SHA-256 hash),
            it is silently skipped and success=True is returned.

        Returns:
            ChunkStorageResult where .data is the StoredCorporateChunk or None if skipped.
        """
        if not content or not content.strip():
            return ChunkStorageResult(success=False, message="Insert failed: 'content' is required but empty.")

        result = insert_chunk(
            self.db_path,
            {
                "doc_id":      doc_id,
                "chunk_index": chunk_index,
                "content":     content,
                "metadata":    metadata or {},
            }
        )

        if result is None:
            return ChunkStorageResult(
                success=True,
                message=f"Chunk {chunk_index} for '{doc_id}' already exists — skipped (duplicate hash).",
                data=None,
            )

        return ChunkStorageResult(
            success=True,
            message=f"Chunk {chunk_index} for '{doc_id}' inserted successfully.",
            data=result,
        )

    def insert_chunks_batch(
        self,
        doc_id:   str,
        chunks:   List[dict],
        metadata: dict = None,
    ) -> ChunkStorageResult:
        """
        Insert a batch of refined chunks from ChunkOrchestrator output.

        Args:
            doc_id:   Source document identifier (applied to all chunks).
            chunks:   List of chunk dicts. Each must have 'chunk_index' and 'content'.
                      Example: [{"chunk_index": 0, "content": "..."}]
            metadata: Full document metadata dict, stored as JSON on each chunk for context.

        Returns:
            ChunkStorageResult where .data is a ChunkBatchResult with counts.
        """
        if not chunks:
            return ChunkStorageResult(success=False, message="Insert failed: chunks list is empty.")

        # Enrich each chunk dict with doc_id and shared metadata before passing to db layer
        enriched = [
            {
                "doc_id":      doc_id,
                "chunk_index": c.get("chunk_index", i),
                "content":     c.get("content", ""),
                "metadata":    metadata or {},
            }
            for i, c in enumerate(chunks)
        ]

        batch_result: ChunkBatchResult = insert_chunks_batch(self.db_path, enriched)

        return ChunkStorageResult(
            success=batch_result.failed_count == 0,
            message=(
                f"Batch complete for '{doc_id}': "
                f"{batch_result.inserted_count} inserted, "
                f"{batch_result.skipped_count} skipped (duplicates), "
                f"{batch_result.failed_count} failed."
            ),
            data=batch_result,
        )

    # =======================================================================
    # UPDATE
    # =======================================================================

    def update_embedding(self, chunk_id: int, embedding: List[float]) -> ChunkStorageResult:
        """
        Populate the embedding vector for a stored chunk.
        This is intentionally separate — embeddings are generated in a later batch process.

        Args:
            chunk_id:  The integer primary key of the stored chunk.
            embedding: List of floats from your embedding model.

        Returns:
            ChunkStorageResult indicating success or failure.
        """
        updated = update_chunk_embedding(self.db_path, chunk_id, embedding)
        if updated:
            return ChunkStorageResult(success=True, message=f"Embedding updated for chunk ID {chunk_id}.")
        return ChunkStorageResult(success=False, message=f"Chunk ID {chunk_id} not found.")

    # =======================================================================
    # READ
    # =======================================================================

    def get_chunk_by_id(self, chunk_id: int) -> ChunkStorageResult:
        """Fetch a single chunk by its primary key."""
        chunk = get_chunk_by_id(self.db_path, chunk_id)
        if chunk:
            return ChunkStorageResult(success=True, message="Found.", data=chunk)
        return ChunkStorageResult(success=False, message=f"No chunk found with ID {chunk_id}.")

    def get_chunks_by_doc_id(self, doc_id: str) -> ChunkStorageResult:
        """Fetch all stored chunks for a document, ordered by chunk_index."""
        chunks = get_chunks_by_doc_id(self.db_path, doc_id)
        return ChunkStorageResult(
            success=True,
            message=f"Found {len(chunks)} chunk(s) for '{doc_id}'.",
            data=chunks,
        )

    def get_chunks_without_embeddings(self) -> ChunkStorageResult:
        """
        Fetch all chunks that have not yet been embedded.
        Use this to drive a background embedding batch job.
        """
        chunks = get_chunks_without_embeddings(self.db_path)
        return ChunkStorageResult(
            success=True,
            message=f"Found {len(chunks)} chunk(s) pending embedding.",
            data=chunks,
        )

    # =======================================================================
    # DELETE
    # =======================================================================

    def delete_chunks_by_doc_id(self, doc_id: str) -> ChunkStorageResult:
        """Delete all stored chunks for a given document."""
        deleted_count = delete_chunks_by_doc_id(self.db_path, doc_id)
        return ChunkStorageResult(
            success=True,
            message=f"Deleted {deleted_count} chunk(s) for '{doc_id}'.",
            data=deleted_count,
        )
