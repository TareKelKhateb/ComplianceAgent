"""
repository_metadata_db.py
--------------------------
Data-access layer backed by the metadata_manager's SQLite database
(data/local_files/legal_valts.db).

KEY SCHEMA DIFFERENCES vs. repository.py (compliance_vault.db)
---------------------------------------------------------------
  - Uses raw sqlite3 — metadata_manager has no SQLModel engine/Session.
  - `id` is TEXT (primary key).  SQLite's implicit `rowid` is exposed as the
    integer `id` that DocumentResponse expects.
  - Timestamp column is `created_at` (mapped to `added_at` on the way out).
  - NO `read_count` or `last_read_at` columns — telemetry functions are stubs.
  - `file_path` (DB)  →  `local_path`  (schema)
  - `date`     (DB)  →  `document_date` (schema)
  - `year`     (DB TEXT) ↔ `year` (schema int)
"""

import hashlib
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional

# Use metadata_manager's canonical schema initialiser (single source of truth).
from src.metadata_manager.db import init_db

from .schemas import (
    BulkImportResult,
    DocumentCreate,
    DocumentUpdate,
    ImportPreviewItem,
    MapAndImportRequest,
    ScrapedDocument,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database path — resolved the same way MetadataStore does so config.yaml
# overrides are respected.  Falls back to data/legal_vault.db by default.
# ---------------------------------------------------------------------------

from src.metadata_manager.metadata_store import MetadataStore as _MetadataStore

DB_PATH: str = _MetadataStore().db_path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_schema() -> None:
    """Create the database and tables if they don't exist yet."""
    init_db(DB_PATH)


def _get_conn() -> sqlite3.Connection:
    """Return an open sqlite3 connection with Row factory."""
    _ensure_schema()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(iso_str: Optional[str]) -> Optional[datetime]:
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str)
    except (ValueError, TypeError):
        return None


def _row_to_ns(row: sqlite3.Row) -> SimpleNamespace:
    """
    Spread the full DB row into a SimpleNamespace using the original column names.

    Only the minimum overrides are applied:
      - int_id     → id        (rowid as int; DocumentResponse.id is int)
      - created_at → added_at  (required datetime field in DocumentResponse)
      - read_count, last_read_at added as 0 / None (columns absent in this DB)

    Non-optional string fields declared in DocumentResponse are coerced from
    NULL → "" so Pydantic's string_type validation does not crash on rows
    that were stored without category/subcategory/title/etc.
    """
    d = dict(row)
    d["id"] = d.pop("int_id")                           # int rowid → replaces TEXT id
    d["added_at"] = _parse_dt(d.get("created_at"))      # required by DocumentResponse
    d.setdefault("read_count", 0)                        # absent in this DB
    d.setdefault("last_read_at", None)                   # absent in this DB

    # Guard non-optional string fields: NULL → "" to satisfy Pydantic
    for field in ("category", "subcategory", "title",
                  "document_type", "issuing_entity", "language"):
        if d.get(field) is None:
            d[field] = ""

    return SimpleNamespace(**d)


def _gen_doc_id(title: str) -> str:
    """Stable TEXT primary key derived from the title."""
    slug = title.lower().replace(" ", "_")[:32]
    suffix = hashlib.md5(title.encode()).hexdigest()[:8]
    return f"{slug}__{suffix}"


def _placeholder_hash(title: str, file_url: Optional[str]) -> str:
    """
    Deterministic sha256 hex string used as sha256_hash (NOT NULL in schema).
    DocumentCreate doesn't carry a real hash so we derive one from metadata.
    """
    return hashlib.sha256(f"{title}|{file_url or ''}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# Collision helpers
# ---------------------------------------------------------------------------

def _title_exists(
    conn: sqlite3.Connection, title: str, exclude_rowid: Optional[int] = None
) -> bool:
    if exclude_rowid is not None:
        row = conn.execute(
            "SELECT rowid AS int_id FROM documents WHERE title = ? AND rowid != ? LIMIT 1",
            (title, exclude_rowid),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT rowid AS int_id FROM documents WHERE title = ? LIMIT 1",
            (title,),
        ).fetchone()
    return row is not None


def _combo_exists(
    conn: sqlite3.Connection,
    category: str,
    subcategory: str,
    exclude_rowid: Optional[int] = None,
) -> bool:
    if exclude_rowid is not None:
        row = conn.execute(
            "SELECT rowid AS int_id FROM documents "
            "WHERE category = ? AND subcategory = ? AND rowid != ? LIMIT 1",
            (category, subcategory, exclude_rowid),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT rowid AS int_id FROM documents "
            "WHERE category = ? AND subcategory = ? LIMIT 1",
            (category, subcategory),
        ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Low-level insert (reused by add_document and map_and_import_document)
# ---------------------------------------------------------------------------

def _do_insert(conn: sqlite3.Connection, doc_in: DocumentCreate) -> SimpleNamespace:
    # Generate the text hash strictly for fallback URLs, do not insert into 'id'
    fallback_hash = _gen_doc_id(doc_in.title)
    sha256 = _placeholder_hash(doc_in.title, doc_in.file_url)
    now = _now_iso()
    file_url = doc_in.file_url or f"local://{fallback_hash}"
    date_str = doc_in.document_date.isoformat() if doc_in.document_date else None
    
    # Pass the year as an integer to avoid Strict mode mismatches
    year_val = doc_in.year

    cursor = conn.cursor()
    
    # 1. Removed 'id' from columns and removed the first '?' from VALUES
    cursor.execute(
        """
        INSERT INTO documents (
            file_url, sha256_hash, created_at,
            title, document_type, issuing_entity, document_number,
            year, date, language, category, subcategory,
            file_path, download_status, version, is_last
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 1, 1)
        """,
        (
            file_url, sha256, now,
            doc_in.title, doc_in.document_type, doc_in.issuing_entity,
            doc_in.document_number, year_val, date_str, doc_in.language,
            doc_in.category, doc_in.subcategory, doc_in.local_path,
        ),
    )
    conn.commit()

    # 2. Capture the newly generated auto-increment integer ID
    inserted_id = cursor.lastrowid

    # 3. Fetch using rowid (which maps perfectly to the integer id)
    row = conn.execute(
        "SELECT rowid AS int_id, * FROM documents WHERE rowid = ? LIMIT 1", 
        (inserted_id,)
    ).fetchone()
    
    return _row_to_ns(row)


# ===========================================================================
# CRUD — Add
# ===========================================================================

def add_document(doc_in: DocumentCreate):
    """Saves a new document. Raises ValueError on title or category+subcategory collision."""
    with _get_conn() as conn:
        if _title_exists(conn, doc_in.title):
            raise ValueError(
                f"Title conflict: '{doc_in.title}' already exists in the metadata database."
            )
        if _combo_exists(conn, doc_in.category, doc_in.subcategory):
            raise ValueError(
                f"Category conflict: '{doc_in.category}/{doc_in.subcategory}' "
                "is already used by another document."
            )
        return _do_insert(conn, doc_in)


# ===========================================================================
# CRUD — Bulk import
# ===========================================================================

def bulk_import_documents(selected_docs: List[DocumentCreate]) -> BulkImportResult:
    """Inserts valid documents, skips collisions, returns a summary."""
    successful, failed = 0, 0
    errors: List[str] = []

    for doc_in in selected_docs:
        try:
            add_document(doc_in)
            successful += 1
        except ValueError as exc:
            failed += 1
            errors.append(f"[{doc_in.title}] {exc}")
        except Exception as exc:
            failed += 1
            errors.append(f"[{doc_in.title}] Unexpected error: {exc}")
            logger.exception("bulk_import_documents: unexpected error for '%s'", doc_in.title)

    return BulkImportResult(successful=successful, failed=failed, errors=errors)


# ===========================================================================
# CRUD — Delete
# ===========================================================================

def delete_document_by_title(title: str) -> bool:
    """Delete by exact title. Returns True if found and deleted, False otherwise."""
    with _get_conn() as conn:
        cur = conn.execute("DELETE FROM documents WHERE title = ?", (title,))
        conn.commit()
        return cur.rowcount > 0


def delete_document_by_category(category: str, subcategory: str) -> bool:
    """Delete by category+subcategory. Returns True if found and deleted."""
    with _get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM documents WHERE category = ? AND subcategory = ?",
            (category, subcategory),
        )
        conn.commit()
        return cur.rowcount > 0


# ===========================================================================
# CRUD — Update
# ===========================================================================

def update_document(doc_id: int, doc_in: DocumentUpdate):
    """
    Partially update a document (identified by its integer rowid).
    Raises ValueError on collision with another document.
    Returns None if the document is not found.
    """
    with _get_conn() as conn:
        # Confirm the row exists
        row = conn.execute(
            "SELECT rowid AS int_id, * FROM documents WHERE rowid = ? LIMIT 1", (doc_id,)
        ).fetchone()
        if row is None:
            return None

        current = _row_to_ns(row)

        new_title      = doc_in.title      if doc_in.title      is not None else current.title
        new_category   = doc_in.category   if doc_in.category   is not None else current.category
        new_subcategory = doc_in.subcategory if doc_in.subcategory is not None else current.subcategory

        # Collision checks (exclude this row from the search)
        if new_title != current.title and _title_exists(conn, new_title, exclude_rowid=doc_id):
            raise ValueError(
                f"Title conflict: '{new_title}' is already used by another document."
            )
        if (new_category != current.category or new_subcategory != current.subcategory) and \
                _combo_exists(conn, new_category, new_subcategory, exclude_rowid=doc_id):
            raise ValueError(
                f"Category conflict: '{new_category}/{new_subcategory}' is already "
                "used by another document."
            )

        # Build SET clause from only the fields that were provided
        update_data = doc_in.model_dump(exclude_unset=True)
        # Map schema field names → DB column names
        field_map = {
            "title": "title",
            "category": "category",
            "subcategory": "subcategory",
            "document_type": "document_type",
            "issuing_entity": "issuing_entity",
            "document_number": "document_number",
            "year": "year",
            "document_date": "date",
            "language": "language",
            "file_url": "file_url",
            "local_path": "file_path",
        }
        db_updates: dict = {}
        for schema_field, db_col in field_map.items():
            if schema_field in update_data:
                val = update_data[schema_field]
                # Convert types where schema ≠ DB
                if schema_field == "year" and val is not None:
                    val = str(val)
                if schema_field == "document_date" and val is not None:
                    val = val.isoformat()
                db_updates[db_col] = val

        if db_updates:
            set_clause = ", ".join(f"{col} = ?" for col in db_updates)
            values = list(db_updates.values()) + [doc_id]
            conn.execute(
                f"UPDATE documents SET {set_clause} WHERE rowid = ?", values
            )
            conn.commit()

        updated_row = conn.execute(
            "SELECT rowid AS int_id, * FROM documents WHERE rowid = ? LIMIT 1", (doc_id,)
        ).fetchone()
        return _row_to_ns(updated_row)


# ===========================================================================
# Ingestion & Pipeline
# ===========================================================================

def preview_local_scraped_file(filepath: Path) -> List[ImportPreviewItem]:
    """
    Parse a local JSON file and check every title against legal_valts.db.
    Returns ImportPreviewItem list with READY_TO_MAP or TITLE_CONFLICT status.
    """
    raw = Path(filepath).read_text(encoding="utf-8")
    data = json.loads(raw)

    # Support both flat [dict, …] and nested [[dict, …], …]
    if data and isinstance(data[0], list):
        flat = [item for group in data for item in group]
    else:
        flat = data

    items: List[ImportPreviewItem] = []

    with _get_conn() as conn:
        for idx, raw_doc in enumerate(flat):
            scraped = ScrapedDocument(**raw_doc)
            conflict = _title_exists(conn, scraped.title)

            if conflict:
                status  = "TITLE_CONFLICT"
                message = (
                    f"'{scraped.title}' already exists in the metadata database. "
                    "Import will be skipped unless the title is overridden."
                )
            else:
                status  = "READY_TO_MAP"
                message = f"'{scraped.title}' is new and ready to be mapped and imported."

            items.append(
                ImportPreviewItem(index=idx, document=scraped, status=status, message=message)
            )

    return items


def map_and_import_document(req: MapAndImportRequest):
    """
    Merge a ScrapedDocument with user-supplied category/subcategory (and optional
    title override) and persist it. Raises ValueError on any collision.
    """
    effective_title = req.override_title or req.scraped_data.title

    doc_in = DocumentCreate(
        category=req.category,
        subcategory=req.subcategory,
        title=effective_title,
        document_type=req.scraped_data.document_type,
        issuing_entity=req.scraped_data.issuing_entity,
        document_number=req.scraped_data.document_number,
        year=req.scraped_data.year,
        document_date=req.scraped_data.document_date,
        language=req.scraped_data.language,
        file_url=req.scraped_data.file_url,
        local_path=req.scraped_data.local_path,
        pdf_name=req.scraped_data.pdf_name,
    )

    with _get_conn() as conn:
        if _title_exists(conn, effective_title):
            raise ValueError(
                f"Title conflict: '{effective_title}' already exists in the metadata database."
            )
        if _combo_exists(conn, req.category, req.subcategory):
            raise ValueError(
                f"Category conflict: '{req.category}/{req.subcategory}' "
                "is already used by another document."
            )
        return _do_insert(conn, doc_in)


# ===========================================================================
# Telemetry & Inbox
# ===========================================================================

def export_for_pipeline():
    """
    Fetch ALL documents from legal_valts.db.
    Side-effects (read_count / last_read_at) are SKIPPED — columns don't exist.
    """
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT rowid AS int_id, * FROM documents ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_ns(r) for r in rows]


def get_unread_documents():
    """
    NOT SUPPORTED — legal_valts.db has no read_count column.
    Returns an empty list.
    """
    logger.warning(
        "Notice: get_unread_documents is not supported when using the "
        "metadata_manager database because it lacks telemetry columns."
    )
    return []


def get_documents_added_since(since: datetime):
    """
    Fetch documents where created_at >= *since*.
    Side-effects (read_count / last_read_at) are SKIPPED — columns don't exist.
    """
    since_iso = since.isoformat()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT rowid AS int_id, * FROM documents WHERE created_at >= ? ORDER BY created_at DESC",
            (since_iso,),
        ).fetchall()
    return [_row_to_ns(r) for r in rows]


def read_document_by_title(title: str):
    """
    Fetch a single document by exact title.
    Side-effects (read_count / last_read_at) are SKIPPED — columns don't exist.
    Returns None if not found.
    """
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT rowid AS int_id, * FROM documents WHERE title = ? LIMIT 1", (title,)
        ).fetchone()
    return _row_to_ns(row) if row else None


def reset_all_telemetry() -> int:
    """
    NOT SUPPORTED — legal_valts.db has no telemetry columns.
    Returns 0.
    """
    logger.warning(
        "Notice: reset_all_telemetry is not supported in the metadata_manager database."
    )
    return 0