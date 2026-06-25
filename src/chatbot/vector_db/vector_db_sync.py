"""
vector_db_sync.py
-----------------
Standalone bridge module that syncs processed chunks from the SQLite database
(document_chunks / corporate_chunks) into the chatbot's Chroma vector databases
(external_regulations / internal_policies).

Called by the OCR pipeline after chunks are finalized in SQLite.
Uses LangChain's incremental indexing to handle add/update/delete automatically.

Import style: uses absolute `src.chatbot.*` paths to match the Orchestrator's
conventions, avoiding conflicts with the chatbot's internal `chatbot.*` imports.
"""

import os
import sys
import logging
import pathlib
from typing import Literal

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_chroma import Chroma
from langchain_classic.indexes import SQLRecordManager, index

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Storage paths — mirror src/chatbot/config.py without importing it
# ---------------------------------------------------------------------------

_CHATBOT_DIR = pathlib.Path(__file__).resolve().parent.parent  # src/chatbot
_STORAGE_DIR = _CHATBOT_DIR / "storage"
_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

_RECORD_MANAGER_DB_URL = f"sqlite:///{_STORAGE_DIR / 'record_manager_cache.sql'}"

# Embedding config — same as chatbot/config.py
_EMBEDDING_MODEL_NAME = "gemini-embedding-001"


def _get_embeddings() -> Embeddings:
    """Create the Google Generative AI embedding model."""
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    return GoogleGenerativeAIEmbeddings(
        model=_EMBEDDING_MODEL_NAME,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
    )


def _get_collection_name(is_internal: bool) -> str:
    """Map the is_internal flag to the correct Chroma collection name."""
    return "internal_policies" if is_internal else "external_regulations"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sync_chunks_to_vectordb(
    chunks: list[dict],
    doc_id: str,
    is_internal: bool = False,
) -> dict:
    """
    Sync processed chunks into the chatbot's Chroma vector database.

    Converts chunk dicts (from document_chunks or corporate_chunks tables)
    into LangChain Document objects, then uses incremental indexing to
    add new chunks, update modified ones, and remove deleted ones.

    Parameters
    ----------
    chunks : list[dict]
        Finalized chunk dicts as produced by the OCR pipeline.
        Each must have at least: 'content', 'chunk_id', 'chunk_index'.
    doc_id : str
        The document ID these chunks belong to.
    is_internal : bool
        If True, syncs to ``internal_policies`` (from corporate_chunks).
        If False, syncs to ``external_regulations`` (from document_chunks).

    Returns
    -------
    dict
        Indexing summary with keys: num_added, num_updated, num_skipped, num_deleted.
    """
    if not chunks:
        logger.info("VDB sync: no chunks to sync for doc_id=%s", doc_id)
        return {"num_added": 0, "num_updated": 0, "num_skipped": 0, "num_deleted": 0}

    collection_name = _get_collection_name(is_internal)
    logger.info(
        "VDB sync: syncing %d chunk(s) for doc_id='%s' → collection '%s'",
        len(chunks), doc_id, collection_name,
    )

    # 1. Convert chunk dicts to LangChain Documents
    #    - page_content = the chunk text
    #    - metadata.source = doc_id (used by incremental indexing to track/cleanup)
    #    - metadata.chunk_id = deterministic chunk identifier
    documents = []
    for chunk in chunks:
        content = chunk.get("content", "")
        if not content or not content.strip():
            continue

        doc = Document(
            page_content=content,
            metadata={
                "source": doc_id,
                "chunk_id": chunk.get("chunk_id", ""),
                "chunk_index": chunk.get("chunk_index", 0),
                "doc_id": doc_id,
                "page_number": chunk.get("page_number"),
                "version": chunk.get("version"),
                "change_type": chunk.get("change_type", "unchanged"),
            },
        )
        documents.append(doc)

    if not documents:
        logger.warning("VDB sync: all chunks were empty for doc_id=%s. Skipping.", doc_id)
        return {"num_added": 0, "num_updated": 0, "num_skipped": 0, "num_deleted": 0}

    # 2. Initialize Chroma + RecordManager
    embeddings = _get_embeddings()
    persist_dir = str(_STORAGE_DIR / collection_name)

    vector_store = Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=persist_dir,
    )

    namespace = f"chroma/{collection_name}"
    record_manager = SQLRecordManager(
        namespace=namespace,
        db_url=_RECORD_MANAGER_DB_URL,
    )
    record_manager.create_schema()

    # 3. Run incremental indexing
    result = index(
        docs_source=documents,
        record_manager=record_manager,
        vector_store=vector_store,
        cleanup="incremental",
        source_id_key="source",
    )

    logger.info(
        "VDB sync complete for doc_id='%s' → %s: %s",
        doc_id, collection_name, result,
    )
    return result
