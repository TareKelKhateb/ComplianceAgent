"""
orchestrator.py
---------------
Orchestrates the compliance mapping process using dual database connections.
"""

import uuid
import logging
import json
from src.mapping.data_manager.database import SessionCorp, SessionMapping, init_db
from src.mapping.data_manager.schema import MappingBridgeSchema, RelationshipType
from src.mapping.data_manager import crud_mapping, crud_corporate
from src.mapping.llm_engine.client import analyze_with_llm
from src.mapping.vector_search import get_law_chunks_by_similarity

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def run_mapping_pipeline() -> None:
    logger.info("Starting compliance mapping pipeline.")
    
    # Initialize the mapping database tables
    init_db()
    
    # Open dual sessions
    db_corp = SessionCorp()      # Read-only access to corporate_chunks.db
    db_mapping = SessionMapping() # Read-write access to mapping.db
    
    try:
        # 1. Fetch corporate chunks using the corporate database session
        corporate_chunks = crud_corporate.get_all_chunks(db=db_corp)
        logger.info(f"Fetched {len(corporate_chunks)} corporate policy chunks.")
        
        for corp_chunk in corporate_chunks:
            corp_hash = corp_chunk.get("chunk_hash")
            corp_text = corp_chunk.get("content")
            
            if not corp_hash or not corp_text:
                continue
                
            relevant_law_chunks = get_law_chunks_by_similarity(corp_text, threshold=0.88)
            
            # Handle GAP scenario
            if not relevant_law_chunks:
                if not crud_mapping.get_mapping_by_hashes(db=db_mapping, corp_hash=corp_hash, law_hash="NO_MATCH_FOUND"):
                    gap_data = MappingBridgeSchema(
                        id=str(uuid.uuid4()),
                        corporate_chunk_hash=corp_hash,
                        country_law_hash="NO_MATCH_FOUND",
                        relation_type=RelationshipType.GAP,
                        reasoning="No relevant law chunk found.",
                        confidence_score=1.0
                    )
                    crud_mapping.create_mapping(db=db_mapping, mapping_data=gap_data)
                continue
            
            # Process matches
            for law_chunk in relevant_law_chunks:
                law_hash = law_chunk.get("chunk_hash")
                law_text = law_chunk.get("content")
                
                if crud_mapping.get_mapping_by_hashes(db=db_mapping, corp_hash=corp_hash, law_hash=law_hash):
                    continue
                
                context = f"Corporate Chunk: {corp_text}\n\nCountry Law Chunk: {law_text}"
                try:
                    rel_type, reasoning, confidence = analyze_with_llm(context)
                    mapping_data = MappingBridgeSchema(
                        id=str(uuid.uuid4()),
                        corporate_chunk_hash=corp_hash,
                        country_law_hash=law_hash,
                        relation_type=rel_type,
                        reasoning=reasoning,
                        confidence_score=confidence
                    )
                    crud_mapping.create_mapping(db=db_mapping, mapping_data=mapping_data)
                except Exception as e:
                    logger.error(f"Analysis failed: {e}")

        # Generate metrics
        all_mappings = db_mapping.query(crud_mapping.MappingBridgeTable).all()
        total = len(all_mappings)
        gaps = len([m for m in all_mappings if m.relation_type == RelationshipType.GAP])
        
        with open("data/mapping_metrics.json", "w") as f:
            json.dump({"total_mappings": total, "total_gaps": gaps}, f, indent=4)
            
    finally:
        db_corp.close()
        db_mapping.close()
        logger.info("Database sessions closed. Pipeline finished.")

if __name__ == "__main__":
    run_mapping_pipeline()