from pydantic import BaseModel
from typing import Optional
from datetime import date
from typing import List


# ----------------------------------
# 1. Schema for Adding a Document
# ----------------------------------
class DocumentCreate(BaseModel):
    category: str
    subcategory: str
    title: str
    document_type: str
    issuing_entity: str
    document_number: Optional[str] = None
    year: Optional[int] = None
    document_date: Optional[date] = None
    language: str
    
    # At least one of these should ideally be provided, but we make them optional here
    file_url: Optional[str] = None
    local_path: Optional[str] = None
    pdf_name: Optional[str] = None

class BulkImportResult(BaseModel):
    """Summary of the final bulk import process."""
    successful: int
    failed: int
    errors: List[str]

# ----------------------------------
# 2. Schema for Sending Document Data back to UI
# ----------------------------------
class DocumentResponse(DocumentCreate):
    id: int
    
    class Config:
        from_attributes = True # Tells Pydantic to read the SQLModel object

# ----------------------------------
# 3. Schema for Updating a Document
# ----------------------------------
class DocumentUpdate(BaseModel):
    category: Optional[str] = None
    subcategory: Optional[str] = None
    title: Optional[str] = None
    document_type: Optional[str] = None
    issuing_entity: Optional[str] = None
    document_number: Optional[str] = None
    year: Optional[int] = None
    document_date: Optional[date] = None
    language: Optional[str] = None
    file_url: Optional[str] = None
    local_path: Optional[str] = None
    pdf_name: Optional[str] = None


# ------------------------------
# 4. Scraper Integration Schemas
# ------------------------------

class ImportPreviewItem(BaseModel):
    """Represents a single scraped item and its database compatibility status."""
    index: int                  # So the UI can keep track of which item in the array this is
    document: DocumentCreate    # The scraped metadata
    status: str                 # "READY", "TITLE_CONFLICT", or "COMBO_CONFLICT"
    message: str                # Human-readable explanation

class BulkImportResult(BaseModel):
    """Summary of the final import process."""
    successful: int
    failed: int
    errors: List[str]


# ----------------------------------
# 5. Scraped Data Mapping Schemas
# ----------------------------------
class ScrapedDocument(BaseModel):
    """Schema for the raw data coming from the JSON file."""
    title: str
    document_type: str
    issuing_entity: str
    document_number: Optional[str] = None
    year: Optional[int] = None
    document_date: Optional[date] = None
    language: str
    file_url: Optional[str] = None
    local_path: Optional[str] = None
    pdf_name: Optional[str] = None

class ImportPreviewItem(BaseModel):
    """The report sent back to the UI showing if a scraped file is a duplicate."""
    index: int                  
    document: ScrapedDocument   # Notice we use the ScrapedDocument here
    status: str                 # "READY_TO_MAP" or "TITLE_CONFLICT"
    message: str                

class MapAndImportRequest(BaseModel):
    """The payload the UI sends when the user maps categories and optionally renames a file."""
    scraped_data: ScrapedDocument
    category: str
    subcategory: str
    override_title: Optional[str] = None  # Allow users to change the title on the fly!