import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, status
from typing import List
from datetime import datetime

# Import the new abstraction layer
from .. import repository_metadata_db as repository 

from ..schemas import (
    DocumentCreate, DocumentResponse, DocumentUpdate, 
    ImportPreviewItem, BulkImportResult, MapAndImportRequest
)

router = APIRouter(
    prefix="/documents",
    tags=["Documents"]
)

# ---------------------------------------------------------
# ⚙️ CONFIGURATION VARIABLE: Dynamic Scraped File Path
# ---------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent.parent
SCRAPED_JSON_PATH = PROJECT_ROOT / "output_1.json"


@router.post("/", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def add_document(doc_in: DocumentCreate):
    """Add a new document to the database with strict integrity checks."""
    try:
        return repository.add_document(doc_in)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/bulk-import", response_model=BulkImportResult)
def bulk_import_documents(selected_docs: List[DocumentCreate]):
    """Takes an array of documents and saves them all at once."""
    return repository.bulk_import_documents(selected_docs)

@router.delete("/title/{title}")
def delete_document_by_title(title: str):
    """Delete a document by its exact unique title."""
    success = repository.delete_document_by_title(title)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found.")
    return {"message": f"Document '{title}' deleted successfully."}

@router.delete("/category/{category}/subcategory/{subcategory}")
def delete_document_by_category(category: str, subcategory: str):
    """Delete a document where the combination of category and subcategory is unique."""
    success = repository.delete_document_by_category(category, subcategory)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found.")
    return {"message": f"Document in {category}/{subcategory} deleted successfully."}

@router.put("/{doc_id}", response_model=DocumentResponse)
def update_document(doc_id: int, doc_in: DocumentUpdate):
    """Update a document while enforcing uniqueness on Title and Category/Subcategory."""
    try:
        doc = repository.update_document(doc_id, doc_in)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found.")
        return doc
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.get("/preview-local-file", response_model=List[ImportPreviewItem])
def preview_local_scraped_file():
    """Reads local JSON and checks which files are new based on Title."""
    if not os.path.exists(SCRAPED_JSON_PATH):
        raise HTTPException(status_code=404, detail=f"File not found: {SCRAPED_JSON_PATH}")
    
    try:
        return repository.preview_local_scraped_file(SCRAPED_JSON_PATH)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")

@router.post("/map-and-import", response_model=DocumentResponse)
def map_and_import_document(req: MapAndImportRequest):
    """Takes a raw scraped document, maps it to a category, optionally renames it, and saves it."""
    try:
        return repository.map_and_import_document(req)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.get("/export-for-pipeline", response_model=List[List[DocumentResponse]])
def export_for_pipeline():
    """Exports all database documents for downstream pipelines and updates telemetry."""
    # Wrap in outer list to match the pipeline schema requirements
    return [repository.export_for_pipeline()]

@router.get("/get-unread-documents", response_model=List[DocumentResponse])
def get_unread_documents():
    """Fetch all new documents that have not been read yet."""
    return repository.get_unread_documents()

@router.get("/added-since", response_model=List[DocumentResponse])
def get_documents_added_since(since: datetime):
    """Fetch documents added after a specific time."""
    return repository.get_documents_added_since(since)

@router.get("/title/{title}", response_model=DocumentResponse)
def read_document_by_title(title: str):
    """Fetch a single document by its title and update telemetry."""
    doc = repository.read_document_by_title(title)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document '{title}' not found.")
    return doc

@router.post("/reset-telemetry")
def reset_all_telemetry():
    """Admin function: Resets read_count to 0 and last_read_at to None."""
    count = repository.reset_all_telemetry()
    return {"message": f"Successfully wiped telemetry data for {count} documents."}