"""
crud_country.py
---------------
Read-Only CRUD operations for Country Law chunks.

These functions query the `document_chunks` table inside legal_vault.db via
a SessionLaw session. No category filter is required here because internal
corporate policy chunks are stored in the separate `corporate_chunks` table
within the same database, so document_chunks contains only country-law data.
"""

from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


def get_chunk_by_hash(db: Session, chunk_hash: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves a single country law chunk and its metadata by its SHA-256 hash.
    
    Args:
        db: The SQLAlchemy database session.
        chunk_hash: The SHA-256 hash of the country law chunk.
        
    Returns:
        A dictionary representing the chunk row, or None if not found.
    """
    # Using document_chunks table based on the schema evaluation
    query = text("SELECT * FROM document_chunks WHERE chunk_hash = :hash LIMIT 1")
    try:
        result = db.execute(query, {"hash": chunk_hash}).mappings().first()
        return dict(result) if result else None
    except SQLAlchemyError as e:
        print(f"Database error during country get_chunk_by_hash: {e}")
        return None


def get_all_chunks(db: Session) -> List[Dict[str, Any]]:
    """
    Retrieves all available country law chunks.
    Filters by is_active = 1 to ensure only current chunks are processed.
    
    Args:
        db: The SQLAlchemy database session.
        
    Returns:
        A list of dictionaries containing chunk_hash, content, doc_id, and page_number.
    """
    query = text("""
        SELECT chunk_hash, content, doc_id, page_number 
        FROM document_chunks 
        WHERE is_active = 1
    """)
    try:
        results = db.execute(query).mappings().all()
        return [dict(row) for row in results]
    except SQLAlchemyError as e:
        print(f"Database error during country get_all_chunks: {e}")
        return []
