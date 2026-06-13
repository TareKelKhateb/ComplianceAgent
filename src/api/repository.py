from typing import List, Optional
from datetime import datetime
from pathlib import Path

# Import your unified database models from the metadata_manager here
# from metadata_manager.models import Document 

from .schemas import (
    DocumentCreate, DocumentUpdate, ImportPreviewItem, 
    BulkImportResult, MapAndImportRequest
)

def add_document(doc_in: DocumentCreate): # -> Document
    """Saves a new document. Should raise ValueError if title or category combo exists."""
    pass

def bulk_import_documents(selected_docs: List[DocumentCreate]) -> BulkImportResult:
    """Takes an array of documents, saves valid ones, and skips duplicates safely."""
    pass

def delete_document_by_title(title: str) -> bool:
    """Deletes by title. Returns True if successful, False if not found."""
    pass

def delete_document_by_category(category: str, subcategory: str) -> bool:
    """Deletes by category structure. Returns True if successful, False if not found."""
    pass

def update_document(doc_id: int, doc_in: DocumentUpdate): # -> Optional[Document]
    """Updates a document. Raises ValueError on constraints, returns None if not found."""
    pass

def preview_local_scraped_file(filepath: Path) -> List[ImportPreviewItem]:
    """Reads the JSON file and checks titles against the database to flag duplicates."""
    pass

def map_and_import_document(req: MapAndImportRequest): # -> Document
    """Merges scraped data with categories and saves. Raises ValueError on conflicts."""
    pass

def export_for_pipeline(): # -> List[Document]
    """Fetches all documents and globally updates their read_count/last_read_at telemetry."""
    pass

def get_unread_documents(): # -> List[Document]
    """Fetches documents where read_count == 0, and updates their telemetry to mark as read."""
    pass

def get_documents_added_since(since: datetime): # -> List[Document]
    """Fetches documents added_at >= since, and updates their telemetry to mark as read."""
    pass

def read_document_by_title(title: str): # -> Optional[Document]
    """Fetches a specific document by title and updates its specific telemetry."""
    pass

def reset_all_telemetry() -> int:
    """Resets read metrics for all files. Returns the integer count of files reset."""
    pass