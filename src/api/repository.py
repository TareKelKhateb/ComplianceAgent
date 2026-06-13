"""
repository.py
-------------
Data-access layer for the Compliance Agent API.

All functions open their own SQLModel Session via the shared engine defined in
database.py, operate on the `Document` SQLModel table (compliance_vault.db),
and return plain SQLModel objects that FastAPI serialises through the router
response_model.

Rules obeyed:
  - Only this file is modified.
  - No dependency on metadata_manager.metadata_store (different DB / different
    schema — that store manages legal_vault.db for the ingestion pipeline).
  - Every session is opened and closed inside each function (no global state).
  - ValueError is raised for constraint violations so the router can convert
    them to HTTP 400 responses.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from sqlmodel import Session, select

from .database import engine
from .models import Document
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
# Internal helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


def _mark_read(session: Session, doc: Document) -> None:
    """Increment read_count by 1 and update last_read_at to now UTC in-place."""
    doc.read_count = (doc.read_count or 0) + 1
    doc.last_read_at = _now_utc()
    session.add(doc)


def _check_title_collision(
    session: Session,
    title: str,
    exclude_id: Optional[int] = None,
) -> bool:
    """
    Return True if *title* is already taken by a document other than *exclude_id*.
    When *exclude_id* is None (add path), any existing row is a collision.
    """
    stmt = select(Document).where(Document.title == title)
    existing = session.exec(stmt).first()
    if existing is None:
        return False
    # On the update path, a match against the document itself is fine.
    return existing.id != exclude_id


def _check_combo_collision(
    session: Session,
    category: str,
    subcategory: str,
    exclude_id: Optional[int] = None,
) -> bool:
    """
    Return True if the category+subcategory combination is already taken by a
    document other than *exclude_id*.
    """
    stmt = select(Document).where(
        Document.category == category,
        Document.subcategory == subcategory,
    )
    existing = session.exec(stmt).first()
    if existing is None:
        return False
    return existing.id != exclude_id


# ---------------------------------------------------------------------------
# CRUD — Add
# ---------------------------------------------------------------------------

def add_document(doc_in: DocumentCreate) -> Document:
    """
    Persist a new document.

    Raises ValueError if:
      - the title already exists, OR
      - the category+subcategory combination is already in use.
    """
    with Session(engine) as session:
        # --- Collision checks ---
        if _check_title_collision(session, doc_in.title):
            raise ValueError(
                f"Title conflict: a document with title '{doc_in.title}' already exists."
            )
        if _check_combo_collision(session, doc_in.category, doc_in.subcategory):
            raise ValueError(
                f"Category conflict: the combination '{doc_in.category}/"
                f"{doc_in.subcategory}' is already used by another document."
            )

        # --- Map schema → ORM model ---
        doc = Document(
            category=doc_in.category,
            subcategory=doc_in.subcategory,
            title=doc_in.title,
            document_type=doc_in.document_type,
            issuing_entity=doc_in.issuing_entity,
            document_number=doc_in.document_number,
            year=doc_in.year,
            document_date=doc_in.document_date,
            language=doc_in.language,
            file_url=doc_in.file_url,
            local_path=doc_in.local_path,
            pdf_name=doc_in.pdf_name,
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)
        return doc


# ---------------------------------------------------------------------------
# CRUD — Bulk import
# ---------------------------------------------------------------------------

def bulk_import_documents(selected_docs: List[DocumentCreate]) -> BulkImportResult:
    """
    Insert every document in *selected_docs*.

    Skips (instead of crashing) any document that has a title or
    category/subcategory collision. Tallies successes, failures, and the
    per-failure error messages.
    """
    successful = 0
    failed = 0
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


# ---------------------------------------------------------------------------
# CRUD — Delete
# ---------------------------------------------------------------------------

def delete_document_by_title(title: str) -> bool:
    """
    Delete the document whose title exactly matches *title*.

    Returns True on success, False if no such document exists.
    """
    with Session(engine) as session:
        doc = session.exec(select(Document).where(Document.title == title)).first()
        if doc is None:
            return False
        session.delete(doc)
        session.commit()
        return True


def delete_document_by_category(category: str, subcategory: str) -> bool:
    """
    Delete the document whose category+subcategory combination matches exactly.

    Returns True on success, False if no such document exists.
    """
    with Session(engine) as session:
        doc = session.exec(
            select(Document).where(
                Document.category == category,
                Document.subcategory == subcategory,
            )
        ).first()
        if doc is None:
            return False
        session.delete(doc)
        session.commit()
        return True


# ---------------------------------------------------------------------------
# CRUD — Update
# ---------------------------------------------------------------------------

def update_document(doc_id: int, doc_in: DocumentUpdate) -> Optional[Document]:
    """
    Apply partial updates to an existing document.

    Returns the updated Document, or None if not found.
    Raises ValueError if the proposed new title or category/subcategory would
    clash with *another* document (self-collision is allowed).
    """
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if doc is None:
            return None

        # Determine the effective new values (fall back to current if not supplied).
        new_title = doc_in.title if doc_in.title is not None else doc.title
        new_category = doc_in.category if doc_in.category is not None else doc.category
        new_subcategory = doc_in.subcategory if doc_in.subcategory is not None else doc.subcategory

        # --- Collision checks against other documents ---
        if new_title != doc.title and _check_title_collision(session, new_title, exclude_id=doc_id):
            raise ValueError(
                f"Title conflict: '{new_title}' is already used by another document."
            )
        if (new_category != doc.category or new_subcategory != doc.subcategory) and \
                _check_combo_collision(session, new_category, new_subcategory, exclude_id=doc_id):
            raise ValueError(
                f"Category conflict: '{new_category}/{new_subcategory}' is already "
                "used by another document."
            )

        # --- Apply only the fields that were actually provided ---
        update_data = doc_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(doc, field, value)

        session.add(doc)
        session.commit()
        session.refresh(doc)
        return doc


# ---------------------------------------------------------------------------
# Ingestion & Pipeline
# ---------------------------------------------------------------------------

def preview_local_scraped_file(filepath: Path) -> List[ImportPreviewItem]:
    """
    Parse the local JSON file at *filepath* and check every entry's title
    against the database.

    Returns a list of ImportPreviewItem objects with status:
      "READY_TO_MAP"   — title is new; safe to import.
      "TITLE_CONFLICT" — a document with this title already exists in the DB.
    """
    filepath = Path(filepath)
    raw = filepath.read_text(encoding="utf-8")
    data = json.loads(raw)

    # Tolerate both flat [dict, …] and nested [[dict, …], …] layouts.
    if data and isinstance(data[0], list):
        flat_items = [item for group in data for item in group]
    else:
        flat_items = data

    preview_items: List[ImportPreviewItem] = []

    with Session(engine) as session:
        for idx, raw_doc in enumerate(flat_items):
            # Parse through the ScrapedDocument schema for validation / defaults.
            scraped = ScrapedDocument(**raw_doc)

            title_taken = session.exec(
                select(Document).where(Document.title == scraped.title)
            ).first() is not None

            if title_taken:
                status = "TITLE_CONFLICT"
                message = (
                    f"A document with the title '{scraped.title}' already exists "
                    "in the database. Import will be skipped unless title is overridden."
                )
            else:
                status = "READY_TO_MAP"
                message = f"'{scraped.title}' is new and ready to be mapped and imported."

            preview_items.append(
                ImportPreviewItem(
                    index=idx,
                    document=scraped,
                    status=status,
                    message=message,
                )
            )

    return preview_items


def map_and_import_document(req: MapAndImportRequest) -> Document:
    """
    Merge a raw ScrapedDocument with user-supplied category/subcategory and an
    optional title override, then persist it.

    Raises ValueError on any title or category/subcategory collision.
    """
    # Build the effective title.
    effective_title = req.override_title if req.override_title else req.scraped_data.title

    with Session(engine) as session:
        # --- Collision checks ---
        if _check_title_collision(session, effective_title):
            raise ValueError(
                f"Title conflict: '{effective_title}' is already used by another document."
            )
        if _check_combo_collision(session, req.category, req.subcategory):
            raise ValueError(
                f"Category conflict: '{req.category}/{req.subcategory}' is already "
                "used by another document."
            )

        doc = Document(
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
        session.add(doc)
        session.commit()
        session.refresh(doc)
        return doc


# ---------------------------------------------------------------------------
# Telemetry & Inbox
# ---------------------------------------------------------------------------

def read_document_by_title(title: str) -> Optional[Document]:
    """
    Fetch a single document by exact title.

    Side-effect: increments read_count by 1 and sets last_read_at to now UTC.
    Returns None if no document with that title exists.
    """
    with Session(engine) as session:
        doc = session.exec(select(Document).where(Document.title == title)).first()
        if doc is None:
            return None
        _mark_read(session, doc)
        session.commit()
        session.refresh(doc)
        return doc


def get_unread_documents() -> List[Document]:
    """
    Return all documents where read_count == 0 (never read).

    Side-effect: marks every returned document as read (read_count += 1,
    last_read_at = now UTC) so they do not appear in the inbox again.
    """
    with Session(engine) as session:
        docs = session.exec(
            select(Document).where(Document.read_count == 0)
        ).all()

        for doc in docs:
            _mark_read(session, doc)

        session.commit()

        # Refresh each object so callers see the updated telemetry.
        for doc in docs:
            session.refresh(doc)

        return list(docs)


def get_documents_added_since(since: datetime) -> List[Document]:
    """
    Return all documents whose added_at timestamp is >= *since*.

    Side-effect: marks every returned document as read (read_count += 1,
    last_read_at = now UTC).
    """
    with Session(engine) as session:
        docs = session.exec(
            select(Document).where(Document.added_at >= since)
        ).all()

        for doc in docs:
            _mark_read(session, doc)

        session.commit()

        for doc in docs:
            session.refresh(doc)

        return list(docs)


def export_for_pipeline() -> List[Document]:
    """
    Fetch every document in the database.

    Side-effect: marks *all* documents as read (read_count += 1,
    last_read_at = now UTC), regardless of their previous read state.
    Returns the flat list.
    """
    with Session(engine) as session:
        docs = session.exec(select(Document)).all()

        for doc in docs:
            _mark_read(session, doc)

        session.commit()

        for doc in docs:
            session.refresh(doc)

        return list(docs)


def reset_all_telemetry() -> int:
    """
    Admin function: reset read_count to 0 and last_read_at to None for every
    document.  The added_at timestamp is left untouched.

    Returns the number of rows that were reset.
    """
    with Session(engine) as session:
        docs = session.exec(select(Document)).all()

        for doc in docs:
            doc.read_count = 0
            doc.last_read_at = None
            session.add(doc)

        session.commit()
        return len(docs)