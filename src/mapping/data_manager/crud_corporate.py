"""
crud_corporate.py
-----------------
Read-Only CRUD operations for Corporate Policy chunks.
Uses raw SQLAlchemy text queries to retrieve data without altering existing DB schemas.
"""

from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


def get_chunk_by_hash(db: Session, chunk_hash: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves a single corporate chunk and its metadata by its SHA-256 hash.
    
    Args:
        db: The SQLAlchemy database session.
        chunk_hash: The SHA-256 hash of the corporate policy chunk.
        
    Returns:
        A dictionary representing the chunk row, or None if not found.
    """
    query = text("SELECT * FROM corporate_chunks WHERE chunk_hash = :hash LIMIT 1")
    try:
        result = db.execute(query, {"hash": chunk_hash}).mappings().first()
        return dict(result) if result else None
    except SQLAlchemyError as e:
        print(f"Database error during corporate get_chunk_by_hash: {e}")
        return None


def get_all_chunks(db: Session) -> List[Dict[str, Any]]:
    """
    Retrieves all available corporate policy chunks.
    
    Args:
        db: The SQLAlchemy database session.
        
    Returns:
        A list of dictionaries containing chunk_hash, content, and metadata.
    """
    query = text("SELECT chunk_hash, content, metadata FROM corporate_chunks")
    try:
        results = db.execute(query).mappings().all()
        return [dict(row) for row in results]
    except SQLAlchemyError as e:
        print(f"Database error during corporate get_all_chunks: {e}")
        return []
