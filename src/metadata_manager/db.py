"""
db.py
-----
All SQLite operations for the storage layer.
Upper layers (storage_manager.py) call these functions — they never touch SQL directly.
"""

import sqlite3
import os
from typing import Optional, Any
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
        category=row["category"],
        subcategory=row["subcategory"],
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

import os
import sqlite3
def init_db(db_path: str) -> None:
    """
    Initialize the database and ensure the schema is up to date.
    This function creates missing tables and adds missing columns to existing tables
    without affecting current data (Schema Evolution).
    
    Args:
        db_path (str): The filesystem path to the SQLite database file.
    """
    # Ensure the directory for the database file exists
    parent_dir = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(parent_dir, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        # Check if the table exists
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='documents'")
        table_exists = cursor.fetchone() is not None

        if table_exists:
            # Table exists. Let's inspect primary keys to see if we need a migration
            table_info = conn.execute("PRAGMA table_info(documents)").fetchall()
            pk_cols = [row[1] for row in table_info if row[5] > 0]
            if pk_cols and "version" not in pk_cols:
                # We need to migrate to composite primary key (id, version)!
                # Rename the table
                conn.execute("ALTER TABLE documents RENAME TO documents_old")
                
                # Create the new table with composite primary key
                conn.execute("""
                    CREATE TABLE documents (
                        id TEXT NOT NULL,
                        file_url TEXT NOT NULL,
                        sha256_hash TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1,
                        PRIMARY KEY (id, version)
                    )
                """)
                
                # Evolve columns first on the new table so all schema columns exist
                new_columns = [
                    ("title", "TEXT"),
                    ("document_type", "TEXT"),
                    ("issuing_entity", "TEXT"),
                    ("document_number", "TEXT"),
                    ("year", "TEXT"),
                    ("date", "TEXT"),
                    ("language", "TEXT"),
                    ("category", "TEXT"),
                    ("subcategory", "TEXT"),
                    ("version", "INTEGER NOT NULL DEFAULT 1"),
                    ("is_last", "INTEGER NOT NULL DEFAULT 1"),
                    ("file_path", "TEXT"),
                    ("file_size_bytes", "INTEGER"),
                    ("download_status", "TEXT NOT NULL DEFAULT 'pending'"),
                    ("ocr_status", "TEXT NOT NULL DEFAULT 'pending'"),
                    ("ocr_processed_at", "TEXT"),
                    ("retry_count", "INTEGER NOT NULL DEFAULT 0")
                ]
                for col_name, col_type in new_columns:
                    try:
                        conn.execute(f"ALTER TABLE documents ADD COLUMN {col_name} {col_type}")
                    except sqlite3.OperationalError:
                        pass
                
                # Copy data from documents_old (matching whatever columns exist in documents_old)
                old_cols = [row[1] for row in table_info]
                new_cols_set = {"id", "file_url", "sha256_hash", "created_at"} | {c[0] for c in new_columns}
                cols_to_copy = [c for c in old_cols if c in new_cols_set]
                
                cols_str = ", ".join(cols_to_copy)
                conn.execute(f"""
                    INSERT INTO documents ({cols_str})
                    SELECT {cols_str} FROM documents_old
                """)
                
                # Drop old table
                conn.execute("DROP TABLE documents_old")
        else:
            # Table does not exist, create it with composite key
            conn.execute("""
                CREATE TABLE documents (
                    id TEXT NOT NULL,
                    file_url TEXT NOT NULL,
                    sha256_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (id, version)
                )
            """)

        # 2. List of columns that might be added to the 'documents' table over time.
        new_columns = [
            ("title", "TEXT"),
            ("document_type", "TEXT"),
            ("issuing_entity", "TEXT"),
            ("document_number", "TEXT"),
            ("year", "TEXT"),
            ("date", "TEXT"),
            ("language", "TEXT"),
            ("category", "TEXT"),
            ("subcategory", "TEXT"),
            ("version", "INTEGER NOT NULL DEFAULT 1"),
            ("is_last", "INTEGER NOT NULL DEFAULT 1"),
            ("file_path", "TEXT"),
            ("file_size_bytes", "INTEGER"),
            ("download_status", "TEXT NOT NULL DEFAULT 'pending'"),
            ("ocr_status", "TEXT NOT NULL DEFAULT 'pending'"),
            ("ocr_processed_at", "TEXT"),
            ("retry_count", "INTEGER NOT NULL DEFAULT 0")
        ]
        
        for col_name, col_type in new_columns:
            try:
                # Attempt to add the column to the table
                conn.execute(f"ALTER TABLE documents ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                # Column already exists, safe to ignore
                pass

        # Create internal_documents table with the same schema as documents
        conn.execute("""
            CREATE TABLE IF NOT EXISTS internal_documents (
                id TEXT NOT NULL,
                file_url TEXT NOT NULL,
                sha256_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (id, version)
            )
        """)
        
        for col_name, col_type in new_columns:
            try:
                conn.execute(f"ALTER TABLE internal_documents ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass

        # 3. Create the 'document_chunks' table to store OCR output and text segments
        conn.execute("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id           TEXT NOT NULL,
                chunk_id         TEXT,     -- New deterministic ID field
                chunk_index      INTEGER NOT NULL,
                content          TEXT    NOT NULL,
                bbox             TEXT,
                page_number      INTEGER,
                chunk_hash       TEXT    NOT NULL,
                is_active        INTEGER NOT NULL DEFAULT 1, 
                version          INTEGER NOT NULL DEFAULT 1, 
                created_at       TEXT,     
                change_type      TEXT    DEFAULT 'unchanged',
                old_content      TEXT,             
                FOREIGN KEY (doc_id, version) REFERENCES documents (id, version) ON DELETE CASCADE
            )
        """)

        # Add chunk_id column to existing tables (Schema Evolution)
        try:
            conn.execute("ALTER TABLE document_chunks ADD COLUMN chunk_id TEXT")
        except sqlite3.OperationalError:
            pass

        # Create corporate_chunks table to store OCR output and segments of internal documents
        conn.execute("""
            CREATE TABLE IF NOT EXISTS corporate_chunks (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id           TEXT NOT NULL,
                chunk_id         TEXT,     -- New deterministic ID field
                chunk_index      INTEGER NOT NULL,
                content          TEXT    NOT NULL,
                bbox             TEXT,
                page_number      INTEGER,
                chunk_hash       TEXT    NOT NULL,
                is_active        INTEGER NOT NULL DEFAULT 1, 
                version          INTEGER NOT NULL DEFAULT 1, 
                created_at       TEXT,     
                change_type      TEXT    DEFAULT 'unchanged',
                old_content      TEXT,             
                FOREIGN KEY (doc_id, version) REFERENCES internal_documents (id, version) ON DELETE CASCADE
            )
        """)

        try:
            conn.execute("ALTER TABLE corporate_chunks ADD COLUMN chunk_id TEXT")
        except sqlite3.OperationalError:
            pass

        # 4. Create performance indices for faster queries
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ocr_status ON documents (ocr_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON document_chunks (doc_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_internal_docs_ocr ON internal_documents (ocr_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_corp_chunks_doc_id ON corporate_chunks (doc_id)")

        # Schema evolution for approved column (MVP review flow)
        try:
            conn.execute("ALTER TABLE document_chunks ADD COLUMN approved INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        conn.commit()


# ---------------------------------------------------------------------------
# Hash Check  (core deduplication logic)
# ---------------------------------------------------------------------------

def check_hash(db_path: str, document_id: str, sha256_hash: str, is_internal: bool = False) -> dict:
    """
    Check if a document ID + hash combination already exists in the DB as the latest version.

    Returns a plain dict with keys:
    - "action"       : "skip" | "insert"
    - "reason"       : human-readable explanation
    - "new_version"  : version number to use if inserting
    """
    table = "internal_documents" if is_internal else "documents"
    with _get_connection(db_path) as conn:
        # Check for exact match on the latest version (same ID AND same hash as the current latest)
        row = conn.execute(
            f"SELECT * FROM {table} WHERE id = ? AND sha256_hash = ? AND is_last = 1 LIMIT 1",
            (document_id, sha256_hash),
        ).fetchone()

        if row:
            return {
                "action": "skip",
                "reason": "Exact duplicate — same ID and same hash already stored as latest version.",
                "new_version": row["version"],
            }

        # Check if ID exists at all (different hash = content changed compared to current latest)
        latest_row = conn.execute(
            f"SELECT * FROM {table} WHERE id = ? AND is_last = 1 LIMIT 1",
            (document_id,),
        ).fetchone()

        if latest_row:
            return {
                "action": "insert",
                "reason": f"Same ID, content changed — inserting as version {latest_row['version'] + 1}.",
                "new_version": latest_row["version"] + 1,
            }

        # ID never seen before
        return {
            "action": "insert",
            "reason": "New ID — inserting as version 1.",
            "new_version": 1,
        }


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def insert_document(
    db_path: str,
    data: dict,
    version: int,
    is_internal: bool = False,
) -> StoredDocument:
    """
    Insert a new document record.
    Accepts a flat data dict containing id, file_url, sha256_hash, and any
    optional metadata fields.
    If this is version N+1, the previous is_last is set to False atomically.
    """
    document_id = data.get("id", "").strip()
    file_url    = data.get("file_url", "").strip()
    sha256_hash = data.get("sha256_hash", "").strip()
    now = datetime.now(timezone.utc).isoformat()
    table = "internal_documents" if is_internal else "documents"

    with _get_connection(db_path) as conn:
        # Atomic transaction: demote old latest → insert new one by ID
        if version > 1:
            conn.execute(
                f"UPDATE {table} SET is_last = 0 WHERE id = ? AND is_last = 1",
                (document_id,),
            )

        cursor = conn.execute(
            f"""
            INSERT INTO {table} (
                id, file_url, title, document_type, issuing_entity,
                document_number, year, date, language, category, subcategory,
                sha256_hash, version, is_last,
                file_path, file_size_bytes, download_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                document_id,
                file_url,
                data.get("title"),
                data.get("document_type"),
                data.get("issuing_entity"),
                data.get("document_number"),
                data.get("year"),
                data.get("date"),
                data.get("language"),
                data.get("category"),
                data.get("subcategory"),
                sha256_hash,
                version,
                data.get("file_path"),
                data.get("file_size_bytes"),
                data.get("download_status", "pending"),
                now,
            ),
        )
        conn.commit()

    return get_document_by_id(db_path, document_id, is_internal=is_internal)


def update_document_file_info(
    db_path: str,
    document_id: str,
    fields: dict,
    is_internal: bool = False,
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
    table = "internal_documents" if is_internal else "documents"
    if not updates:
        return get_document_by_id(db_path, document_id, is_internal=is_internal)

    set_clause = ", ".join(f"{col} = ?" for col in updates)
    values = list(updates.values()) + [document_id]

    with _get_connection(db_path) as conn:
        conn.execute(
            f"UPDATE {table} SET {set_clause} WHERE id = ? AND is_last = 1",
            values,
        )
        conn.commit()

    return get_document_by_id(db_path, document_id, is_internal=is_internal)


def mark_download_failed(db_path: str, document_id: str, is_internal: bool = False) -> None:
    """Mark a document record as failed to download."""
    table = "internal_documents" if is_internal else "documents"
    with _get_connection(db_path) as conn:
        conn.execute(
            f"UPDATE {table} SET download_status = 'failed' WHERE id = ? AND is_last = 1",
            (document_id,),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def get_document_by_id(db_path: str, document_id: str, is_internal: bool = False) -> Optional[StoredDocument]:
    """Fetch the latest version of a document by its ID."""
    table = "internal_documents" if is_internal else "documents"
    with _get_connection(db_path) as conn:
        row = conn.execute(
            f"SELECT * FROM {table} WHERE id = ? AND is_last = 1 LIMIT 1", (document_id,)
        ).fetchone()
    return _row_to_document(row) if row else None


def get_latest_by_id(db_path: str, document_id: str, is_internal: bool = False) -> Optional[StoredDocument]:
    """Fetch the latest (is_last=True) version of a document by ID."""
    table = "internal_documents" if is_internal else "documents"
    with _get_connection(db_path) as conn:
        row = conn.execute(
            f"SELECT * FROM {table} WHERE id = ? AND is_last = 1 LIMIT 1",
            (document_id,),
        ).fetchone()
    return _row_to_document(row) if row else None


def get_all_versions_by_id(db_path: str, document_id: str, is_internal: bool = False) -> list[StoredDocument]:
    """Fetch all versions of a document by ID, ordered oldest → newest."""
    table = "internal_documents" if is_internal else "documents"
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE id = ? ORDER BY version ASC",
            (document_id,),
        ).fetchall()
    return [_row_to_document(r) for r in rows]


def get_latest_by_url(db_path: str, file_url: str, is_internal: bool = False) -> Optional[StoredDocument]:
    """Fetch the latest (is_last=True) version of a document by URL."""
    table = "internal_documents" if is_internal else "documents"
    with _get_connection(db_path) as conn:
        row = conn.execute(
            f"SELECT * FROM {table} WHERE file_url = ? AND is_last = 1 LIMIT 1",
            (file_url,),
        ).fetchone()
    return _row_to_document(row) if row else None


def get_all_versions_by_url(db_path: str, file_url: str, is_internal: bool = False) -> list[StoredDocument]:
    """Fetch all versions of a document by URL, ordered oldest → newest."""
    table = "internal_documents" if is_internal else "documents"
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE file_url = ? ORDER BY version ASC",
            (file_url,),
        ).fetchall()
    return [_row_to_document(r) for r in rows]


def get_all_latest_documents(db_path: str, is_internal: bool = False) -> list[StoredDocument]:
    """Fetch all current (is_last=True) documents — useful for Tier 2 handoff."""
    table = "internal_documents" if is_internal else "documents"
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE is_last = 1 ORDER BY created_at DESC"
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
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    download_status: Optional[str] = None,
    latest_only: bool = True,
    is_internal: bool = False,
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
    if category:
        conditions.append("category = ?")
        params.append(category)
    if subcategory:
        conditions.append("subcategory = ?")
        params.append(subcategory)
    if download_status:
        conditions.append("download_status = ?")
        params.append(download_status)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    table = "internal_documents" if is_internal else "documents"

    with _get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM {table} {where_clause} ORDER BY created_at DESC",
            params,
        ).fetchall()
    return [_row_to_document(r) for r in rows]


def get_documents_by_download_status(
    db_path: str, status: str, is_internal: bool = False
) -> list[StoredDocument]:
    """
    Get all documents with a given download_status.
    Useful for retrying failed downloads: get_documents_by_download_status(db, "failed")
    """
    table = "internal_documents" if is_internal else "documents"
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE download_status = ? ORDER BY created_at DESC",
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
            d.id, d.file_url, d.title, d.document_type, d.issuing_entity,
            d.document_number, d.year, d.date, d.language,
            d.category, d.subcategory,
            d.sha256_hash, d.version, 1, # Mark as latest version
            d.file_path, d.file_size_bytes, d.download_status, now
        ) for d in docs
    ]

    try:
        with _get_connection(db_path) as conn:
            cursor = conn.executemany("""
                INSERT INTO documents (
                    id, file_url, title, document_type, issuing_entity,
                    document_number, year, date, language,
                    category, subcategory,
                    sha256_hash, version, is_last,
                    file_path, file_size_bytes, download_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


# ---------------------------------------------------------------------------
# OCR Operations (Layer 3 & Pipeline Helpers)
# ---------------------------------------------------------------------------

def get_pending_ocr_documents(db_path: str) -> list[StoredDocument]:
    """
    Fetch documents that are downloaded successfully but not yet processed by OCR.
    
    Returns:
        list[StoredDocument]: List of documents ready for processing.
    """
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM documents WHERE download_status = 'completed' AND ocr_status = 'pending'"
        ).fetchall()
    return [_row_to_document(r) for r in rows]


def update_ocr_status(db_path: str, document_id: str, status: str) -> None:
    """
    Update the OCR status of a document (e.g., to 'processing', 'completed', or 'failed').
    """
    with _get_connection(db_path) as conn:
        conn.execute(
            "UPDATE documents SET ocr_status = ? WHERE id = ? AND is_last = 1",
            (status, document_id)
        )
        conn.commit()


def insert_document_chunks_batch(db_path: str, chunks: list[dict[str, Any]]) -> bool:
    """
    Layer 3: Bulk insert OCR chunks and finalize the document's OCR lifecycle.
    
    Args:
        db_path (str): Path to the SQLite database.
        chunks (list[dict]): List of processed chunks from Layer 2.
    
    Returns:
        bool: True if transaction succeeded, False otherwise.
    """
    if not chunks:
        return False

    doc_id: str = chunks[0]['doc_id']
    now: str = datetime.now(timezone.utc).isoformat()
    
    # Map dictionary keys to database columns
    payload = [
        (
            c['doc_id'], 
            c.get('chunk_id'), # New deterministic ID
            c['chunk_index'], 
            c['content'], 
            str(c.get('bbox', '')), # Ensure bbox is a string
            c.get('page_number'), 
            c['chunk_hash']
        ) for c in chunks
    ]

    try:
        with _get_connection(db_path) as conn:
            # 1. Insert all chunks in one batch
            conn.executemany("""
                INSERT INTO document_chunks (
                    doc_id, chunk_id, chunk_index, content, bbox, page_number, chunk_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, payload)

            # 2. Update parent record to 'completed' and set the timestamp
            conn.execute("""
                UPDATE documents 
                SET ocr_status = 'completed', ocr_processed_at = ? 
                WHERE id = ? AND is_last = 1
            """, (now, doc_id))
            
            conn.commit()
            return True
    except sqlite3.Error as e:
        print(f"[-] Database error during chunk storage: {e}")
        return False    


def get_documents_by_custom_filter(
    db_path: str,
    category: str,
    subcategory: Optional[str] = None,
    title: Optional[str] = None,
    is_last: Optional[bool] = None,
) -> list[StoredDocument]:
    """
    Query documents by category with optional subcategory, title, and is_last filters.
    """
    is_internal = (category or "").strip().lower() == "internal"
    table = "internal_documents" if is_internal else "documents"
    conditions = ["category = ?"]
    params = [category]

    if subcategory:
        conditions.append("subcategory = ?")
        params.append(subcategory)
    if title:
        conditions.append("title LIKE ?")
        params.append(f"%{title}%")
    if is_last is not None:
        conditions.append("is_last = ?")
        params.append(1 if is_last else 0)

    where_clause = "WHERE " + " AND ".join(conditions)
    query = f"SELECT * FROM {table} {where_clause} ORDER BY created_at DESC"

    with _get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    
    return [_row_to_document(row) for row in rows]


def get_unapproved_chunks(db_path: str) -> list[dict]:
    """
    Fetch all document chunks that have been modified or added, 
    but not yet approved by the user, and have version > 1.
    """
    query = """
        SELECT c.id, c.doc_id, c.chunk_id, c.chunk_index, c.content, c.page_number, c.version, c.change_type, c.old_content, d.title
        FROM document_chunks c
        LEFT JOIN documents d ON c.doc_id = d.id AND c.version = d.version
        WHERE c.approved = 0 AND c.version > 1
        ORDER BY d.title ASC, c.chunk_index ASC
    """
    with _get_connection(db_path) as conn:
        rows = conn.execute(query).fetchall()
    return [dict(row) for row in rows]


def approve_chunk_by_id(db_path: str, chunk_id: int) -> bool:
    """
    Mark a document chunk as approved.
    """
    query = "UPDATE document_chunks SET approved = 1 WHERE id = ?"
    try:
        with _get_connection(db_path) as conn:
            conn.execute(query, (chunk_id,))
            conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"[!] Error approving chunk: {e}")
        return False


