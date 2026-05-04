"""
models.py
---------
Dataclass definitions for the storage layer.
These are the structures passed between teammates and the storage module.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime



@dataclass
class DocumentMetadata:
    """
    Represents the metadata scraped by the ingestion team.
    This is what your teammates pass IN to the storage layer.
    """
    file_url: str                              # Required: URL of the PDF
    title: Optional[str] = None
    document_type: Optional[str] = None       # e.g. "LAW", "REGULATION"
    issuing_entity: Optional[str] = None
    document_number: Optional[str] = None
    year: Optional[str] = None
    date: Optional[str] = None                # ISO string e.g. "2024-01-15"
    language: Optional[str] = None


@dataclass
class StoredDocument:
    """
    Represents a fully stored document record — what comes OUT of the DB.
    Includes everything in DocumentMetadata plus storage-layer fields.
    """
    # --- Identity ---
    id: int
    file_url: str

    # --- Scraped Metadata ---
    title: Optional[str]
    document_type: Optional[str]
    issuing_entity: Optional[str]
    document_number: Optional[str]
    year: Optional[str]
    date: Optional[str]
    language: Optional[str]

    # --- Storage Layer Fields ---
    sha256_hash: str                           # Hash of PDF binary content
    version: int                               # 1, 2, 3... increments on content change
    is_last: bool                              # True = latest version of this URL
    file_path: Optional[str]                   # Relative path to PDF on filesystem
    file_size_bytes: Optional[int]             # Size of downloaded PDF
    download_status: str                       # "pending" | "downloaded" | "failed"
    created_at: str                            # ISO timestamp of when record was inserted


@dataclass
class StorageResult:
    """
    Returned by every public function in storage_manager.py.
    Lets teammates check success/failure without catching exceptions.
    """
    success: bool
    message: str
    data: Optional[object] = None             # StoredDocument or list or None


@dataclass
class HashCheckResult:
    """Result of checking a hash against the DB."""
    status: str                                # "exact_match" | "new_url" | "changed_content"
    existing_document: Optional[StoredDocument] = None
    new_version: int = 1

@dataclass
class BatchStorageResult:
    """Batch Insert Results"""
    total_count: int
    inserted_count: int
    failed_count: int
    errors: list[str] = field(default_factory=list)