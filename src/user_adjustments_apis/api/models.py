"""
models.py
---------
Pydantic models for the User Adjustments API.

Defines request/response schemas for:
  - Incoming scraper documents
  - Review documents (with user-adjustable fields)
  - Document updates
  - Session management
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Document models
# ---------------------------------------------------------------------------

class ScrapedDocument(BaseModel):
    """
    A single document as produced by the scraper.
    Matches the shape of each object in ``ouput_scrap_1.json``.
    """
    title: Optional[str] = None
    document_type: Optional[str] = None
    issuing_entity: Optional[str] = None
    document_number: Optional[str] = None
    year: Optional[str] = None
    date: Optional[str] = None
    language: Optional[str] = None
    file_url: str
    local_path: Optional[str] = None
    pdf_name: Optional[str] = None


class ReviewDocument(BaseModel):
    """
    A document ready for user review.
    Extends ScrapedDocument with the user-assignable classification fields.
    """
    # --- Original scraped fields ---
    title: Optional[str] = None
    document_type: Optional[str] = None
    issuing_entity: Optional[str] = None
    document_number: Optional[str] = None
    year: Optional[str] = None
    date: Optional[str] = None
    language: Optional[str] = None
    file_url: str
    local_path: Optional[str] = None
    pdf_name: Optional[str] = None

    # --- User-assignable classification fields ---
    category: Optional[str] = None
    subcategory: Optional[str] = None
    id: Optional[str] = None

    # --- Cache indicator ---
    cached: bool = Field(
        default=False,
        description="True when fields were auto-populated from the mapping cache.",
    )


class DocumentUpdate(BaseModel):
    """
    Partial update payload for a single document.
    Only non-None fields are applied.
    """
    title: Optional[str] = None
    document_type: Optional[str] = None
    issuing_entity: Optional[str] = None
    document_number: Optional[str] = None
    year: Optional[str] = None
    date: Optional[str] = None
    language: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    id: Optional[str] = None


# ---------------------------------------------------------------------------
# Session models
# ---------------------------------------------------------------------------

class ReviewSessionInfo(BaseModel):
    """Public-facing session metadata."""
    session_id: str
    status: Literal["pending", "approved", "rejected"]
    created_at: str
    document_count: int
    approved_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Request / Response wrappers
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    """
    Request body for ``POST /api/sessions``.

    The scraper output is ``list[list[dict]]`` — an array of groups,
    where each group is an array of documents.
    """
    documents: list[list[ScrapedDocument]]


class CreateSessionResponse(BaseModel):
    """Response for ``POST /api/sessions``."""
    session_id: str
    review_url: str
    session: ReviewSessionInfo


class ApproveResponse(BaseModel):
    """Response for ``POST /api/sessions/{session_id}/approve``."""
    status: str
    message: str
    session: ReviewSessionInfo
    adjusted_data: list[list[dict]]


class ErrorResponse(BaseModel):
    """Standard error response."""
    detail: str
