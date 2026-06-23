"""
crud_mapping.py
---------------
CRUD operations for the Mapping Bridge layer.
Provides database access methods for mapping records.
"""

from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from src.mapping.data_manager.database import MappingBridgeTable
from src.mapping.data_manager.schema import MappingBridgeSchema


def create_mapping(db: Session, mapping_data: MappingBridgeSchema) -> Optional[MappingBridgeTable]:
    """
    Inserts a new MappingBridgeSchema record into the database.
    
    Args:
        db: The SQLAlchemy database session.
        mapping_data: The Pydantic model containing the new mapping data.
        
    Returns:
        The created MappingBridgeTable instance, or None if an error occurred.
    """
    db_record = MappingBridgeTable(
        id=mapping_data.id,
        corporate_chunk_hash=mapping_data.corporate_chunk_hash,
        country_law_hash=mapping_data.country_law_hash,
        relation_type=mapping_data.relation_type,
        reasoning=mapping_data.reasoning,
        confidence_score=mapping_data.confidence_score
    )
    
    try:
        db.add(db_record)
        db.commit()
        db.refresh(db_record)
        return db_record
    except SQLAlchemyError as e:
        db.rollback()
        print(f"Database error during create_mapping: {e}")
        return None


def get_mappings_by_corporate_hash(db: Session, corporate_hash: str) -> List[MappingBridgeTable]:
    """
    Fetches all mapping records linked to a specific corporate policy chunk hash.
    
    Args:
        db: The SQLAlchemy database session.
        corporate_hash: The SHA-256 hash of the corporate policy chunk.
        
    Returns:
        A list of MappingBridgeTable instances.
    """
    try:
        return db.query(MappingBridgeTable).filter(
            MappingBridgeTable.corporate_chunk_hash == corporate_hash
        ).all()
    except SQLAlchemyError as e:
        print(f"Database error during get_mappings_by_corporate_hash: {e}")
        return []


def get_mapping_by_hashes(db: Session, corp_hash: str, law_hash: str) -> Optional[MappingBridgeTable]:
    """
    Checks if a mapping link already exists between a specific corporate chunk 
    and a specific country law chunk.
    
    Args:
        db: The SQLAlchemy database session.
        corp_hash: The SHA-256 hash of the corporate policy chunk.
        law_hash: The SHA-256 hash of the country law chunk.
        
    Returns:
        The MappingBridgeTable instance if it exists, otherwise None.
    """
    try:
        return db.query(MappingBridgeTable).filter(
            MappingBridgeTable.corporate_chunk_hash == corp_hash,
            MappingBridgeTable.country_law_hash == law_hash
        ).first()
    except SQLAlchemyError as e:
        print(f"Database error during get_mapping_by_hashes: {e}")
        return None
