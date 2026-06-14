"""
app.py
------
FastAPI application for the User Adjustments stage.

Provides REST endpoints to:
  1. Create review sessions from scraper output
  2. View and edit document metadata
  3. Approve sessions — which caches mappings and triggers the orchestrator
  4. Manage the mapping cache

Sessions are stored in-memory (short-lived review contexts).
Mappings are persisted in SQLite via ``cache_db``.
"""

import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .cache_db import (
    clear_all_mappings,
    delete_mapping,
    get_all_mappings,
    get_cached_mapping,
    init_cache_db,
    upsert_mappings_batch,
)
from .models import (
    ApproveResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    DocumentUpdate,
    ReviewDocument,
    ReviewSessionInfo,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("user_adjustments_api")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
CACHE_DB_PATH = os.path.join(ROOT_DIR, "data", "mapping_cache.db")

# Ensure project root is on sys.path for orchestrator imports
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------

class _SessionData:
    """Internal representation of a review session."""

    __slots__ = ("session_id", "status", "created_at", "approved_at", "documents")

    def __init__(
        self,
        session_id: str,
        documents: list[list[ReviewDocument]],
    ) -> None:
        self.session_id = session_id
        self.status: str = "pending"
        self.created_at: str = datetime.now(timezone.utc).isoformat()
        self.approved_at: Optional[str] = None
        self.documents = documents

    @property
    def document_count(self) -> int:
        return sum(len(group) for group in self.documents)

    def to_info(self) -> ReviewSessionInfo:
        return ReviewSessionInfo(
            session_id=self.session_id,
            status=self.status,
            created_at=self.created_at,
            document_count=self.document_count,
            approved_at=self.approved_at,
        )


# Global session store  (dict: session_id → _SessionData)
_sessions: dict[str, _SessionData] = {}


# ---------------------------------------------------------------------------
# Lifespan — initialise cache DB on startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initialising mapping cache DB at: %s", CACHE_DB_PATH)
    init_cache_db(CACHE_DB_PATH)
    yield


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="User Adjustments API",
    description=(
        "Human-in-the-loop metadata review for the Compliance Agent pipeline. "
        "Receives scraper output, presents it for review, caches user mappings, "
        "and triggers the orchestrator on approval."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — wide-open for local dev; tighten in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Serve UI
# ---------------------------------------------------------------------------

@app.get("/review", include_in_schema=False)
@app.get("/review/{session_id}", include_in_schema=False)
async def review_session_page(session_id: Optional[str] = None):
    """Serve the index.html page for a specific session review."""
    ui_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui"
    )
    index_path = os.path.join(ui_dir, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="UI index.html not found")
    return FileResponse(index_path)

# Mount the static files for the UI (JS, CSS, assets)
ui_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui"
)
app.mount("/ui", StaticFiles(directory=ui_dir), name="ui")


# ===================================================================
# Helper: apply cached mappings to scraped documents
# ===================================================================

def _apply_cache(doc: ReviewDocument) -> ReviewDocument:
    """
    Look up ``doc.file_url`` in the mapping cache and pre-fill any
    cached classification fields.  Sets ``doc.cached = True`` if a
    mapping was found.
    """
    cached = get_cached_mapping(CACHE_DB_PATH, doc.file_url)
    if cached is None:
        return doc

    # Only fill in fields that are currently empty on the document
    if cached.get("category") and not doc.category:
        doc.category = cached["category"]
    if cached.get("subcategory") and not doc.subcategory:
        doc.subcategory = cached["subcategory"]
    if cached.get("doc_id") and not doc.id:
        doc.id = cached["doc_id"]
    # Also fill other metadata if the scraper left them blank
    if cached.get("title") and not doc.title:
        doc.title = cached["title"]
    if cached.get("document_type") and not doc.document_type:
        doc.document_type = cached["document_type"]
    if cached.get("issuing_entity") and not doc.issuing_entity:
        doc.issuing_entity = cached["issuing_entity"]
    if cached.get("document_number") and not doc.document_number:
        doc.document_number = cached["document_number"]
    if cached.get("year") and not doc.year:
        doc.year = cached["year"]
    if cached.get("date") and not doc.date:
        doc.date = cached["date"]
    if cached.get("language") and not doc.language:
        doc.language = cached["language"]

    doc.cached = True
    return doc


# ===================================================================
# Helper: resolve flat doc index → (group_index, inner_index)
# ===================================================================

def _resolve_doc_index(
    session: _SessionData, doc_index: int
) -> tuple[int, int]:
    """
    Convert a flat 0-based doc_index across all groups into
    (group_idx, inner_idx).  Raises HTTPException 404 if out of range.
    """
    offset = 0
    for gi, group in enumerate(session.documents):
        if doc_index < offset + len(group):
            return gi, doc_index - offset
        offset += len(group)
    raise HTTPException(
        status_code=404,
        detail=f"Document index {doc_index} out of range (total={session.document_count}).",
    )


# ===================================================================
# Helper: background orchestrator trigger
# ===================================================================

def _run_orchestrator_background(records: list[dict]) -> None:
    """
    Spawn the Orchestrator with pre-approved records.
    Runs in a background thread so the API response returns immediately.
    """
    try:
        from src.Orchetrator.Orchestrator import Orchestrator

        logger.info("Background: starting orchestrator with %d record(s).", len(records))
        orchestrator = Orchestrator(push_to_dagshub=False)
        orchestrator.run_with_data(records)
        logger.info("Background: orchestrator completed successfully.")
    except Exception:
        logger.exception("Background: orchestrator failed.")


# ===================================================================
# 1. POST /api/sessions — Create a new review session
# ===================================================================

@app.post(
    "/api/sessions",
    response_model=CreateSessionResponse,
    status_code=201,
    summary="Create a review session from scraper output",
)
async def create_session(body: CreateSessionRequest):
    """
    Accept scraper output and create a review session.

    Each document is checked against the mapping cache.  If a cached mapping
    exists for its ``file_url``, the classification fields are auto-populated
    and ``cached`` is set to ``True``.

    Returns the ``session_id`` and a review URL.
    """
    session_id = uuid.uuid4().hex[:12]

    # Convert ScrapedDocument → ReviewDocument, applying cache
    review_groups: list[list[ReviewDocument]] = []
    for group in body.documents:
        review_group = []
        for scraped in group:
            review_doc = ReviewDocument(**scraped.model_dump())
            review_doc = _apply_cache(review_doc)
            review_group.append(review_doc)
        review_groups.append(review_group)

    session = _SessionData(session_id=session_id, documents=review_groups)
    _sessions[session_id] = session

    review_url = f"/review/{session_id}"

    logger.info(
        "Created session %s with %d document(s) (%d cached).",
        session_id,
        session.document_count,
        sum(
            1
            for g in review_groups
            for d in g
            if d.cached
        ),
    )

    return CreateSessionResponse(
        session_id=session_id,
        review_url=review_url,
        session=session.to_info(),
    )


# ===================================================================
# 2. GET /api/sessions — List all sessions
# ===================================================================

@app.get(
    "/api/sessions",
    response_model=list[ReviewSessionInfo],
    summary="List all review sessions",
)
async def list_sessions(
    status: Optional[str] = Query(None, description="Filter by status: pending|approved|rejected"),
):
    sessions = list(_sessions.values())
    if status:
        sessions = [s for s in sessions if s.status == status]
    return [s.to_info() for s in sessions]


# ===================================================================
# 3. GET /api/sessions/{session_id} — Get session details
# ===================================================================

@app.get(
    "/api/sessions/{session_id}",
    summary="Get session details with all documents",
)
async def get_session(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    return {
        "session": session.to_info(),
        "documents": [
            [doc.model_dump() for doc in group]
            for group in session.documents
        ],
    }


# ===================================================================
# 4. GET /api/sessions/{session_id}/documents — All documents (flat)
# ===================================================================

@app.get(
    "/api/sessions/{session_id}/documents",
    response_model=list[ReviewDocument],
    summary="Get all documents in a session (flat list)",
)
async def get_session_documents(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    return [doc for group in session.documents for doc in group]


# ===================================================================
# 5. GET /api/sessions/{session_id}/documents/{doc_index}
# ===================================================================

@app.get(
    "/api/sessions/{session_id}/documents/{doc_index}",
    response_model=ReviewDocument,
    summary="Get a single document by flat index",
)
async def get_document(session_id: str, doc_index: int):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    gi, ii = _resolve_doc_index(session, doc_index)
    return session.documents[gi][ii]


# ===================================================================
# 6. PUT /api/sessions/{session_id}/documents/{doc_index}
# ===================================================================

@app.put(
    "/api/sessions/{session_id}/documents/{doc_index}",
    response_model=ReviewDocument,
    summary="Update a single document's metadata",
)
async def update_document(session_id: str, doc_index: int, update: DocumentUpdate):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    if session.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Session is '{session.status}' — only pending sessions can be edited.",
        )

    gi, ii = _resolve_doc_index(session, doc_index)
    doc = session.documents[gi][ii]

    # Apply only non-None fields from the update
    update_data = update.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(doc, key, value)

    return doc


# ===================================================================
# 7. PUT /api/sessions/{session_id}/documents — Bulk update
# ===================================================================

@app.put(
    "/api/sessions/{session_id}/documents",
    response_model=list[ReviewDocument],
    summary="Bulk update all documents in one request",
)
async def bulk_update_documents(
    session_id: str, updates: list[DocumentUpdate]
):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    if session.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Session is '{session.status}' — only pending sessions can be edited.",
        )

    # Flatten documents for indexing
    flat_docs = [doc for group in session.documents for doc in group]
    if len(updates) != len(flat_docs):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Expected {len(flat_docs)} updates but received {len(updates)}. "
                "Provide one update per document (use null fields to skip)."
            ),
        )

    for doc, upd in zip(flat_docs, updates):
        update_data = upd.model_dump(exclude_none=True)
        for key, value in update_data.items():
            setattr(doc, key, value)

    return flat_docs


# ===================================================================
# 8. POST /api/sessions/{session_id}/approve — Approve & trigger
# ===================================================================

@app.post(
    "/api/sessions/{session_id}/approve",
    response_model=ApproveResponse,
    summary="Approve the session and trigger the orchestrator",
)
async def approve_session(session_id: str, background_tasks: BackgroundTasks):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    if session.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Session is already '{session.status}'.",
        )

    # ------------------------------------------------------------------
    # Validate: every document must have id, category, subcategory
    # ------------------------------------------------------------------
    errors: list[str] = []
    flat_index = 0
    for gi, group in enumerate(session.documents):
        for ii, doc in enumerate(group):
            missing = []
            if not doc.id:
                missing.append("id")
            if not doc.category:
                missing.append("category")
            if not doc.subcategory:
                missing.append("subcategory")
            if missing:
                errors.append(
                    f"Document [{flat_index}] ('{doc.title or doc.file_url}'): "
                    f"missing required field(s): {', '.join(missing)}"
                )
            flat_index += 1

    if errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Cannot approve: some documents are incomplete.",
                "errors": errors,
            },
        )

    # ------------------------------------------------------------------
    # 1. Build the adjusted output in list[list[dict]] format
    # ------------------------------------------------------------------
    adjusted_data: list[list[dict]] = []
    cache_entries: list[dict] = []

    for group in session.documents:
        adjusted_group: list[dict] = []
        for doc in group:
            doc_dict = doc.model_dump(exclude={"cached"})
            adjusted_group.append(doc_dict)

            # Prepare cache entry
            cache_entries.append({
                "file_url": doc.file_url,
                "title": doc.title,
                "document_type": doc.document_type,
                "issuing_entity": doc.issuing_entity,
                "document_number": doc.document_number,
                "year": doc.year,
                "date": doc.date,
                "language": doc.language,
                "category": doc.category,
                "subcategory": doc.subcategory,
                "doc_id": doc.id,
            })
        adjusted_data.append(adjusted_group)

    # ------------------------------------------------------------------
    # 2. Persist all mappings to cache
    # ------------------------------------------------------------------
    cached_count = upsert_mappings_batch(CACHE_DB_PATH, cache_entries)
    logger.info("Cached %d mapping(s) for session %s.", cached_count, session_id)

    # ------------------------------------------------------------------
    # 3. Mark session as approved
    # ------------------------------------------------------------------
    session.status = "approved"
    session.approved_at = datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # 4. Trigger orchestrator in background
    # ------------------------------------------------------------------
    # Flatten to list[dict] for the orchestrator (it expects the inner list)
    flat_records = [doc for group in adjusted_data for doc in group]
    background_tasks.add_task(_run_orchestrator_background, flat_records)

    logger.info(
        "Session %s approved with %d document(s). Orchestrator triggered in background.",
        session_id,
        len(flat_records),
    )

    return ApproveResponse(
        status="approved",
        message=(
            f"Session approved. {len(flat_records)} document(s) sent to the orchestrator. "
            f"{cached_count} mapping(s) cached."
        ),
        session=session.to_info(),
        adjusted_data=adjusted_data,
    )


# ===================================================================
# 9. POST /api/sessions/{session_id}/reject — Reject session
# ===================================================================

@app.post(
    "/api/sessions/{session_id}/reject",
    response_model=ReviewSessionInfo,
    summary="Reject / discard a session",
)
async def reject_session(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    if session.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Session is already '{session.status}'.",
        )

    session.status = "rejected"
    logger.info("Session %s rejected.", session_id)
    return session.to_info()


# ===================================================================
# 10. GET /api/mappings — View cached mappings
# ===================================================================

@app.get(
    "/api/mappings",
    summary="View all cached document mappings",
)
async def list_mappings():
    return get_all_mappings(CACHE_DB_PATH)


# ===================================================================
# 11. DELETE /api/mappings — Delete a cached mapping
# ===================================================================

@app.delete(
    "/api/mappings",
    summary="Delete a cached mapping by file_url",
)
async def remove_mapping(file_url: str = Query(..., description="The file_url to delete")):
    deleted = delete_mapping(CACHE_DB_PATH, file_url)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No mapping found for '{file_url}'.")
    return {"detail": f"Mapping for '{file_url}' deleted."}


# ===================================================================
# 12. DELETE /api/mappings/clear — Delete all cached mappings
# ===================================================================

@app.delete(
    "/api/mappings/clear",
    summary="Delete all cached document mappings",
)
async def clear_mappings():
    count = clear_all_mappings(CACHE_DB_PATH)
    logger.info("Cleared all cached mappings. Total deleted: %d", count)
    return {"detail": f"All {count} mappings deleted."}
