"""
cache_db.py
-----------
SQLite-backed mapping cache for user adjustments.

When a user reviews a document and assigns metadata (category, subcategory, id, etc.),
the mapping is persisted here keyed by ``file_url``.  On subsequent scrapes that produce
the same URL, the cached fields are auto-populated so the user doesn't repeat work.
"""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS document_mappings (
    file_url         TEXT PRIMARY KEY,
    title            TEXT,
    document_type    TEXT,
    issuing_entity   TEXT,
    document_number  TEXT,
    year             TEXT,
    date             TEXT,
    language         TEXT,
    category         TEXT,
    subcategory      TEXT,
    doc_id           TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
"""

# Fields that can be cached (excludes file_url which is the PK, and timestamps)
_CACHEABLE_FIELDS = {
    "title", "document_type", "issuing_entity", "document_number",
    "year", "date", "language", "category", "subcategory", "doc_id",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_connection(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection with row-factory for dict-like access."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_cache_db(db_path: str) -> None:
    """
    Create the mapping cache database and table if they don't exist.

    Parameters
    ----------
    db_path : str
        Filesystem path to the SQLite database file.
    """
    parent = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(parent, exist_ok=True)

    with _get_connection(db_path) as conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.commit()


def get_cached_mapping(db_path: str, file_url: str) -> Optional[dict]:
    """
    Retrieve a cached mapping by file_url.

    Returns
    -------
    dict | None
        A dict of cached fields if found, ``None`` otherwise.
    """
    with _get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM document_mappings WHERE file_url = ? LIMIT 1",
            (file_url,),
        ).fetchone()

    if row is None:
        return None

    return {
        "title": row["title"],
        "document_type": row["document_type"],
        "issuing_entity": row["issuing_entity"],
        "document_number": row["document_number"],
        "year": row["year"],
        "date": row["date"],
        "language": row["language"],
        "category": row["category"],
        "subcategory": row["subcategory"],
        "doc_id": row["doc_id"],
    }


def upsert_mapping(db_path: str, file_url: str, fields: dict) -> None:
    """
    Insert or update a single mapping.

    Parameters
    ----------
    db_path : str
        Path to the cache database.
    file_url : str
        The URL that uniquely identifies this document.
    fields : dict
        Key-value pairs to cache.  Only keys in ``_CACHEABLE_FIELDS`` are stored.
    """
    now = _now_iso()
    safe = {k: v for k, v in fields.items() if k in _CACHEABLE_FIELDS}

    with _get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT 1 FROM document_mappings WHERE file_url = ?",
            (file_url,),
        ).fetchone()

        if existing:
            # UPDATE — only set provided fields
            if not safe:
                return
            set_clause = ", ".join(f"{col} = ?" for col in safe)
            values = list(safe.values()) + [now, file_url]
            conn.execute(
                f"UPDATE document_mappings SET {set_clause}, updated_at = ? WHERE file_url = ?",
                values,
            )
        else:
            # INSERT
            cols = ["file_url", "created_at", "updated_at"] + list(safe.keys())
            placeholders = ", ".join("?" for _ in cols)
            values = [file_url, now, now] + list(safe.values())
            conn.execute(
                f"INSERT INTO document_mappings ({', '.join(cols)}) VALUES ({placeholders})",
                values,
            )

        conn.commit()


def upsert_mappings_batch(db_path: str, mappings: list[dict]) -> int:
    """
    Batch upsert mappings.  Each dict must contain ``file_url`` plus any
    cacheable fields.

    Returns
    -------
    int
        Number of mappings processed.
    """
    count = 0
    for m in mappings:
        url = m.get("file_url")
        if not url:
            continue
        upsert_mapping(db_path, url, m)
        count += 1
    return count


def get_all_mappings(db_path: str) -> list[dict]:
    """
    Return every cached mapping as a list of dicts.
    """
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM document_mappings ORDER BY updated_at DESC"
        ).fetchall()

    return [
        {
            "file_url": row["file_url"],
            "title": row["title"],
            "document_type": row["document_type"],
            "issuing_entity": row["issuing_entity"],
            "document_number": row["document_number"],
            "year": row["year"],
            "date": row["date"],
            "language": row["language"],
            "category": row["category"],
            "subcategory": row["subcategory"],
            "doc_id": row["doc_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def delete_mapping(db_path: str, file_url: str) -> bool:
    """
    Delete a single cached mapping by file_url.

    Returns
    -------
    bool
        True if a row was deleted, False if not found.
    """
    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM document_mappings WHERE file_url = ?",
            (file_url,),
        )
        conn.commit()
        return cursor.rowcount > 0


def clear_all_mappings(db_path: str) -> int:
    """
    Delete all cached document mappings.

    Returns
    -------
    int
        The number of mappings deleted.
    """
    with _get_connection(db_path) as conn:
        cursor = conn.execute("DELETE FROM document_mappings")
        conn.commit()
        return cursor.rowcount
