from pydantic import BaseModel
from typing import Optional
from datetime import date

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