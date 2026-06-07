from typing import Optional, List, Dict, Any
from sqlmodel import SQLModel, Field, Column, JSON
from datetime import date, datetime, timezone

# ----------------------------------
# 1. User & RBAC Table (Unchanged)
# ----------------------------------
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    role: str = Field(default="USER") # "ADMIN" or "USER"
    permissions: List[str] = Field(default=[], sa_column=Column(JSON))

# ----------------------------------
# 2. Document Vault Table (Updated to your spec)
# ----------------------------------
class Document(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Core Categorization
    category: str = Field(index=True)
    subcategory: str = Field(index=True)
    title: str = Field(unique=True, index=True) # Enforcing unique titles as requested
    
    # Document Details
    document_type: str
    issuing_entity: str
    document_number: Optional[str] = None
    year: Optional[int] = Field(default=None, index=True)
    document_date: Optional[date] = None # Using 'document_date' to avoid SQL 'date' keyword conflicts
    language: str = Field(default="Arabic")
    
    # File Location Pointers
    file_url: Optional[str] = None
    local_path: Optional[str] = None
    pdf_name: Optional[str] = None
    
    # Audit & Tracking
    uploaded_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    extra_metadata: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))


    # Usage Tracking
    read_count: int = Field(default=0)
    last_read_at: Optional[datetime] = Field(default=None)
    added_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))