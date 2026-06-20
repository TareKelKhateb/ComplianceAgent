"""
database.py
-----------
SQLAlchemy database setup for the Compliance Mapping pipeline.
Manages connections for the Mapping bridge and the unified Legal Vault databases.

NOTE: corporate_chunks.db has been retired. Both corporate policy chunks
(corporate_chunks table) and country law chunks (document_chunks table) are
now read from legal_vault.db via SessionLaw.
"""

import os
from sqlalchemy import create_engine, Column, String, Float, Enum as SQLEnum
from sqlalchemy.orm import sessionmaker, declarative_base
from src.mapping.data_manager.schema import RelationshipType

# --- Path Configuration ---
# Navigate to the project root and locate the 'data' directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA_DIR = os.path.join(BASE_DIR, "data")

# --- 1. Engines & Session Factories ---

# Engine for Mapping Bridge (Read-Write)
engine_mapping = create_engine(
    f"sqlite:///{os.path.join(DATA_DIR, 'mapping.db')}",
    connect_args={"check_same_thread": False}
)

# Unified engine for both corporate policy chunks and country law chunks.
# Reads the `corporate_chunks` and `document_chunks` tables inside legal_vault.db.
engine_law = create_engine(
    f"sqlite:///{os.path.join(DATA_DIR, 'legal_vault.db')}",
    connect_args={"check_same_thread": False}
)

# Session factories
SessionMapping = sessionmaker(autocommit=False, autoflush=False, bind=engine_mapping)
SessionLaw = sessionmaker(autocommit=False, autoflush=False, bind=engine_law)

Base = declarative_base()

# --- 2. ORM Model Definition ---

class MappingBridgeTable(Base):
    """
    SQLAlchemy model representing a compliance mapping between 
    a corporate chunk and a country law chunk.
    """
    __tablename__ = "mapping_bridge"

    id = Column(String, primary_key=True, index=True)
    corporate_chunk_hash = Column(String, index=True, nullable=False)
    country_law_hash = Column(String, index=True, nullable=False)
    
    # Use the RelationshipType Enum directly in the column
    relation_type = Column(SQLEnum(RelationshipType), nullable=False)
    
    reasoning = Column(String, nullable=False)
    confidence_score = Column(Float, nullable=False)

# --- 3. Database Initialization Function ---

def init_db() -> None:
    """
    Creates tables in the Mapping database only.
    """
    Base.metadata.create_all(bind=engine_mapping)