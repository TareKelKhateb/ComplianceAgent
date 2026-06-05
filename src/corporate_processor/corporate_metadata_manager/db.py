"""
db.py
-----
All SQLite operations for the corporate_chunks storage layer.
The CorporateChunkStore (corporate_store.py) calls these functions — 
it never touches SQL directly. Mirrors the design of metadata_manager/db.py.
"""

import json
import hashlib
import sqlite3
import os
from typing import Optional, Any, List
from datetime import datetime, timezone

from .models import StoredCorporateChunk, ChunkBatchResult


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_connection(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection with row factory for dict-like access."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # Better concurrent read performance
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _row_to_chunk(row: sqlite3.Row) -> StoredCorporateChunk:
    """Convert a DB row to a StoredCorporateChunk dataclass."""
    return StoredCorporateChunk(
        id=row["id"],
        doc_id=row["doc_id"],
        chunk_index=row["chunk_index"],
        content=row["content"],
        chunk_hash=row["chunk_hash"],
        metadata=row["metadata"],
        embedding=row["embedding"],
        created_at=row["created_at"],
    )


def compute_chunk_hash(content: str) -> str:
    """Compute a SHA-256 hash of the refined text content for deduplication."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Schema Initialization
# ---------------------------------------------------------------------------

def init_db(db_path: str) -> None:
    """
    Initialize the database and ensure the corporate_chunks schema is up to date.
    Uses Schema Evolution (ALTER TABLE) so existing data is never destroyed.

    Args:
        db_path (str): The filesystem path to the SQLite database file.
    """
    parent_dir = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(parent_dir, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        # 1. Create the corporate_chunks table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS corporate_chunks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id      TEXT    NOT NULL,
                chunk_index INTEGER NOT NULL,
                content     TEXT    NOT NULL,
                chunk_hash  TEXT    NOT NULL UNIQUE,   -- Prevents duplicate refined chunks
                metadata    TEXT,                      -- Full document metadata as JSON
                embedding   TEXT,                      -- Nullable: JSON array, populated later
                created_at  TEXT    NOT NULL
            )
        """)

        # 2. Schema evolution: safely add any new columns without touching existing data
        evolution_columns = [
            ("metadata",    "TEXT"),
            ("embedding",   "TEXT"),
        ]
        for col_name, col_type in evolution_columns:
            try:
                conn.execute(f"ALTER TABLE corporate_chunks ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass  # Column already exists — safe to ignore

        # 3. Performance indices
        conn.execute("CREATE INDEX IF NOT EXISTS idx_corp_chunks_doc_id ON corporate_chunks (doc_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_corp_chunks_hash   ON corporate_chunks (chunk_hash)")

        conn.commit()


# ---------------------------------------------------------------------------
# Hash Check — core deduplication logic (mirrors db.check_hash)
# ---------------------------------------------------------------------------

def check_chunk_hash(db_path: str, chunk_hash: str) -> bool:
    """
    Returns True if a chunk with this hash already exists (skip).
    Returns False if the chunk is new (insert).
    """
    with _get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM corporate_chunks WHERE chunk_hash = ? LIMIT 1",
            (chunk_hash,)
        ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Write Operations
# ---------------------------------------------------------------------------

def insert_chunk(db_path: str, chunk: dict) -> Optional[StoredCorporateChunk]:
    """
    Insert a single refined chunk. Skips silently if hash already exists.

    Args:
        db_path: Path to SQLite DB.
        chunk:   Dict with keys: doc_id, chunk_index, content, metadata (dict).

    Returns:
        StoredCorporateChunk if inserted, None if skipped (duplicate).
    """
    content    = chunk.get("content", "")
    chunk_hash = compute_chunk_hash(content)

    # Deduplication check
    if check_chunk_hash(db_path, chunk_hash):
        return None

    now = datetime.now(timezone.utc).isoformat()
    metadata_json = json.dumps(chunk.get("metadata", {}), ensure_ascii=False)

    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO corporate_chunks
                (doc_id, chunk_index, content, chunk_hash, metadata, embedding, created_at)
            VALUES (?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                chunk.get("doc_id"),
                chunk.get("chunk_index"),
                content,
                chunk_hash,
                metadata_json,
                now,
            ),
        )
        conn.commit()
        new_id = cursor.lastrowid

    return get_chunk_by_id(db_path, new_id)


def insert_chunks_batch(db_path: str, chunks: list[dict]) -> ChunkBatchResult:
    """
    Bulk insert a list of refined chunks. Duplicate hashes are silently skipped.

    Args:
        db_path: Path to SQLite DB.
        chunks:  List of dicts, each with: doc_id, chunk_index, content, metadata.

    Returns:
        ChunkBatchResult with counts and any error messages.
    """
    now = datetime.now(timezone.utc).isoformat()
    inserted_count = 0
    skipped_count  = 0
    errors: list   = []

    for chunk in chunks:
        content    = chunk.get("content", "")
        chunk_hash = compute_chunk_hash(content)

        if check_chunk_hash(db_path, chunk_hash):
            skipped_count += 1
            continue

        metadata_json = json.dumps(chunk.get("metadata", {}), ensure_ascii=False)
        try:
            with _get_connection(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO corporate_chunks
                        (doc_id, chunk_index, content, chunk_hash, metadata, embedding, created_at)
                    VALUES (?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (
                        chunk.get("doc_id"),
                        chunk.get("chunk_index"),
                        content,
                        chunk_hash,
                        metadata_json,
                        now,
                    ),
                )
                conn.commit()
                inserted_count += 1
        except sqlite3.Error as e:
            errors.append(f"Chunk {chunk.get('chunk_index')} for {chunk.get('doc_id')}: {e}")

    return ChunkBatchResult(
        total_count=len(chunks),
        inserted_count=inserted_count,
        skipped_count=skipped_count,
        failed_count=len(errors),
        errors=errors,
    )


def update_chunk_embedding(db_path: str, chunk_id: int, embedding: List[float]) -> bool:
    """
    Populate the embedding column for a stored chunk (separate process step).

    Args:
        db_path:   Path to SQLite DB.
        chunk_id:  The integer primary key of the chunk.
        embedding: List of floats from your embedding model.

    Returns:
        True if updated, False if chunk_id not found.
    """
    embedding_json = json.dumps(embedding)
    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            "UPDATE corporate_chunks SET embedding = ? WHERE id = ?",
            (embedding_json, chunk_id),
        )
        conn.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Read Operations
# ---------------------------------------------------------------------------

def get_chunk_by_id(db_path: str, chunk_id: int) -> Optional[StoredCorporateChunk]:
    """Fetch a single chunk by its integer primary key."""
    with _get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM corporate_chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
    return _row_to_chunk(row) if row else None


def get_chunks_by_doc_id(db_path: str, doc_id: str) -> list[StoredCorporateChunk]:
    """Fetch all stored chunks for a given document, ordered by chunk_index."""
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM corporate_chunks WHERE doc_id = ? ORDER BY chunk_index ASC",
            (doc_id,)
        ).fetchall()
    return [_row_to_chunk(r) for r in rows]


def get_chunks_without_embeddings(db_path: str) -> list[StoredCorporateChunk]:
    """Fetch all chunks that have not yet been embedded — useful for batch embedding jobs."""
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM corporate_chunks WHERE embedding IS NULL ORDER BY created_at ASC"
        ).fetchall()
    return [_row_to_chunk(r) for r in rows]


def delete_chunks_by_doc_id(db_path: str, doc_id: str) -> int:
    """
    Delete all chunks for a given doc_id. 
    Returns the number of rows deleted.
    """
    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM corporate_chunks WHERE doc_id = ?", (doc_id,)
        )
        conn.commit()
    return cursor.rowcount
