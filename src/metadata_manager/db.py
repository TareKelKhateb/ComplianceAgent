"""
db.py
-----
All SQLite operations for the storage layer.
Upper layers (storage_manager.py) call these functions — they never touch SQL directly.
"""

import sqlite3
import os
from typing import Optional
from datetime import datetime, timezone

from .models import StoredDocument, HashCheckResult, BatchStorageResult


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


def _row_to_document(row: sqlite3.Row) -> StoredDocument:
    """Convert a DB row to a StoredDocument dataclass."""
    return StoredDocument(
        id=row["id"],
        file_url=row["file_url"],
        title=row["title"],
        document_type=row["document_type"],
        issuing_entity=row["issuing_entity"],
        document_number=row["document_number"],
        year=row["year"],
        date=row["date"],
        language=row["language"],
        sha256_hash=row["sha256_hash"],
        version=row["version"],
        is_last=bool(row["is_last"]),
        file_path=row["file_path"],
        file_size_bytes=row["file_size_bytes"],
        download_status=row["download_status"],
        created_at=row["created_at"],
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db(db_path: str) -> None:
    """
    Create the database and tables if they don't exist yet.
    Safe to call multiple times (idempotent).
    """
    parent_dir = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(parent_dir, exist_ok=True)

    with _get_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,

                -- Scraped metadata
                file_url         TEXT    NOT NULL,
                title            TEXT,
                document_type    TEXT,
                issuing_entity   TEXT,
                document_number  TEXT,
                year             TEXT,
                date             TEXT,
                language         TEXT,

                -- Storage layer fields
                sha256_hash      TEXT    NOT NULL,
                version          INTEGER NOT NULL DEFAULT 1,
                is_last          INTEGER NOT NULL DEFAULT 1,  -- 1=True, 0=False
                file_path        TEXT,
                file_size_bytes  INTEGER,
                download_status  TEXT    NOT NULL DEFAULT 'pending',
                created_at       TEXT    NOT NULL
            )
        """)

        # Index on (file_url, version) for fast hash lookups
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_url_version
            ON documents (file_url, version)
        """)

        # Index on is_last for quickly finding current versions
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_is_last
            ON documents (is_last)
        """)

        conn.commit()


# ---------------------------------------------------------------------------
# Hash Check  (core deduplication logic)
# ---------------------------------------------------------------------------

def check_hash(db_path: str, file_url: str, sha256_hash: str) -> dict:
    """
    Check if a URL + hash combination already exists in the DB.

    Returns a plain dict with keys:
    - "action"       : "skip" | "insert"
    - "reason"       : human-readable explanation
    - "new_version"  : version number to use if inserting
    """
    with _get_connection(db_path) as conn:
        # Check for exact match (same URL AND same hash)
        row = conn.execute(
            "SELECT * FROM documents WHERE file_url = ? AND sha256_hash = ? LIMIT 1",
            (file_url, sha256_hash),
        ).fetchone()

        if row:
            return {
                "action": "skip",
                "reason": "Exact duplicate — same URL and same hash already stored.",
                "new_version": row["version"],
            }

        # Check if URL exists at all (different hash = content changed)
        latest_row = conn.execute(
            "SELECT * FROM documents WHERE file_url = ? AND is_last = 1 LIMIT 1",
            (file_url,),
        ).fetchone()

        if latest_row:
            return {
                "action": "insert",
                "reason": f"Same URL, content changed — inserting as version {latest_row['version'] + 1}.",
                "new_version": latest_row["version"] + 1,
            }

        # URL never seen before
        return {
            "action": "insert",
            "reason": "New URL — inserting as version 1.",
            "new_version": 1,
        }


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def insert_document(
    db_path: str,
    data: dict,
    version: int,
) -> StoredDocument:
    """
    Insert a new document record.
    Accepts a flat data dict containing file_url, sha256_hash, and any
    optional metadata fields.
    If this is version N+1, the previous is_last is set to False atomically.
    """
    file_url    = data.get("file_url", "").strip()
    sha256_hash = data.get("sha256_hash", "").strip()
    now = datetime.now(timezone.utc).isoformat()

    with _get_connection(db_path) as conn:
        # Atomic transaction: demote old latest → insert new one
        if version > 1:
            conn.execute(
                "UPDATE documents SET is_last = 0 WHERE file_url = ? AND is_last = 1",
                (file_url,),
            )

        cursor = conn.execute(
            """
            INSERT INTO documents (
                file_url, title, document_type, issuing_entity,
                document_number, year, date, language,
                sha256_hash, version, is_last,
                file_path, file_size_bytes, download_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                file_url,
                data.get("title"),
                data.get("document_type"),
                data.get("issuing_entity"),
                data.get("document_number"),
                data.get("year"),
                data.get("date"),
                data.get("language"),
                sha256_hash,
                version,
                data.get("file_path"),
                data.get("file_size_bytes"),
                data.get("download_status", "pending"),
                now,
            ),
        )
        conn.commit()
        new_id = cursor.lastrowid

    return get_document_by_id(db_path, new_id)


def update_document_file_info(
    db_path: str,
    document_id: int,
    fields: dict,
) -> Optional[StoredDocument]:
    """
    Update any combination of document fields by ID.
    Accepts a dict of column → value pairs to update.
    Supported fields: file_path, file_size_bytes, download_status, title,
    document_type, issuing_entity, document_number, year, date, language,
    is_last.
    """
    ALLOWED = {
        "file_path", "file_size_bytes", "download_status",
        "title", "document_type", "issuing_entity", "document_number",
        "year", "date", "language", "is_last",
    }
    updates = {k: v for k, v in fields.items() if k in ALLOWED}
    if not updates:
        return get_document_by_id(db_path, document_id)

    set_clause = ", ".join(f"{col} = ?" for col in updates)
    values = list(updates.values()) + [document_id]

    with _get_connection(db_path) as conn:
        conn.execute(
            f"UPDATE documents SET {set_clause} WHERE id = ?",
            values,
        )
        conn.commit()

    return get_document_by_id(db_path, document_id)


def mark_download_failed(db_path: str, document_id: int) -> None:
    """Mark a document record as failed to download."""
    with _get_connection(db_path) as conn:
        conn.execute(
            "UPDATE documents SET download_status = 'failed' WHERE id = ?",
            (document_id,),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def get_document_by_id(db_path: str, document_id: int) -> Optional[StoredDocument]:
    """Fetch a single document by its primary key."""
    with _get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
    return _row_to_document(row) if row else None


def get_latest_by_url(db_path: str, file_url: str) -> Optional[StoredDocument]:
    """Fetch the latest (is_last=True) version of a document by URL."""
    with _get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE file_url = ? AND is_last = 1 LIMIT 1",
            (file_url,),
        ).fetchone()
    return _row_to_document(row) if row else None


def get_all_versions_by_url(db_path: str, file_url: str) -> list[StoredDocument]:
    """Fetch all versions of a document by URL, ordered oldest → newest."""
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM documents WHERE file_url = ? ORDER BY version ASC",
            (file_url,),
        ).fetchall()
    return [_row_to_document(r) for r in rows]


def get_all_latest_documents(db_path: str) -> list[StoredDocument]:
    """Fetch all current (is_last=True) documents — useful for Tier 2 handoff."""
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM documents WHERE is_last = 1 ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_document(r) for r in rows]


def search_by_metadata(
    db_path: str,
    title: Optional[str] = None,
    issuing_entity: Optional[str] = None,
    document_type: Optional[str] = None,
    document_number: Optional[str] = None,
    year: Optional[str] = None,
    language: Optional[str] = None,
    download_status: Optional[str] = None,
    latest_only: bool = True,
) -> list[StoredDocument]:
    """
    Query documents by any combination of metadata fields.
    title and issuing_entity use LIKE (partial match).
    By default only returns the latest version of each document.
    """
    conditions = []
    params = []

    if latest_only:
        conditions.append("is_last = 1")
    if title:
        conditions.append("title LIKE ?")
        params.append(f"%{title}%")
    if issuing_entity:
        conditions.append("issuing_entity LIKE ?")
        params.append(f"%{issuing_entity}%")
    if document_type:
        conditions.append("document_type = ?")
        params.append(document_type)
    if document_number:
        conditions.append("document_number = ?")
        params.append(document_number)
    if year:
        conditions.append("year = ?")
        params.append(year)
    if language:
        conditions.append("language = ?")
        params.append(language)
    if download_status:
        conditions.append("download_status = ?")
        params.append(download_status)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with _get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM documents {where_clause} ORDER BY created_at DESC",
            params,
        ).fetchall()
    return [_row_to_document(r) for r in rows]


def get_documents_by_download_status(
    db_path: str, status: str
) -> list[StoredDocument]:
    """
    Get all documents with a given download_status.
    Useful for retrying failed downloads: get_documents_by_download_status(db, "failed")
    """
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM documents WHERE download_status = ? ORDER BY created_at DESC",
            (status,),
        ).fetchall()
    return [_row_to_document(r) for r in rows]

def insert_documents_batch(db_path: str, docs: list[StoredDocument]) -> BatchStorageResult:
    """
    Abstracted method for the 'Middle-man' to perform bulk inserts.
    It returns the BatchStorageResult dataclass you just created.
    """
    now = datetime.now(timezone.utc).isoformat()
    inserted_count = 0
    errors = []

    # Prepare the data for high-speed insertion
    payload = [
        (
            d.file_url, d.title, d.document_type, d.issuing_entity,
            d.document_number, d.year, d.date, d.language,
            d.sha256_hash, d.version, 1, # Mark as latest version
            d.file_path, d.file_size_bytes, d.download_status, now
        ) for d in docs
    ]

    try:
        with _get_connection(db_path) as conn:
            cursor = conn.executemany("""
                INSERT INTO documents (
                    file_url, title, document_type, issuing_entity,
                    document_number, year, date, language,
                    sha256_hash, version, is_last,
                    file_path, file_size_bytes, download_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, payload)
            conn.commit()
            inserted_count = cursor.rowcount
    except Exception as e:
        errors.append(str(e))

    # Return the result object your friend is expecting
    return BatchStorageResult(
        total_count=len(docs),
        inserted_count=inserted_count,
        failed_count=len(docs) - inserted_count,
        errors=errors
    )