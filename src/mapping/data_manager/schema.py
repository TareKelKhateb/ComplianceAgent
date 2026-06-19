"""
schema.py
---------
Pydantic v2 schema definitions for the Mapping Bridge layer.
Defines the data contract for LLM-generated compliance relationship records.

Location: src/mapping/data_manager/mapping/schema.py
"""

from enum import Enum
from pydantic import BaseModel, Field


class RelationshipType(str, Enum):
    """
    Enumerates all valid relationship types between a corporate chunk
    and a country law chunk as determined by LLM analysis.
    """
    COMPLIANT    = "COMPLIANT"
    CONFLICTING  = "CONFLICTING"
    COVERS       = "COVERS"
    SUPPLEMENTS  = "SUPPLEMENTS"
    GAP          = "GAP"


class MappingBridgeSchema(BaseModel):
    """
    Represents a single LLM-generated compliance mapping record that bridges
    a corporate policy chunk to a country law chunk.

    Attributes:
        id:                   Unique identifier for this mapping record.
        corporate_chunk_hash: SHA-256 hash of the source corporate chunk.
        country_law_hash:     SHA-256 hash of the target country law chunk.
        relation_type:        Semantic relationship type between the two chunks.
        reasoning:            LLM-generated justification for the classification.
        confidence_score:     Confidence level of the LLM analysis (0.0 – 1.0).
    """

    id:                   str              = Field(..., description="Unique identifier for this mapping record.")
    corporate_chunk_hash: str              = Field(..., description="SHA-256 hash of the corporate policy chunk.")
    country_law_hash:     str              = Field(..., description="SHA-256 hash of the country law chunk.")
    relation_type:        RelationshipType = Field(..., description="Semantic relationship type between the two chunks.")
    reasoning:            str              = Field(..., description="LLM-generated justification for the classification.")
    confidence_score:     float            = Field(..., ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0.")

    model_config = {"use_enum_values": True}
