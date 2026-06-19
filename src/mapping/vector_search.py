"""
vector_search.py
----------------
Semantic search module for the Compliance Mapping pipeline.
Provides vector-based retrieval of relevant country law chunks using sentence-transformers.
"""

import logging
import numpy as np
from typing import List, Dict, Any
from sklearn.metrics.pairwise import cosine_similarity
# pyrefly: ignore [missing-import]
from sentence_transformers import SentenceTransformer

# Ensure these imports point to your correctly updated database.py
from src.mapping.data_manager.database import SessionLaw
from src.mapping.data_manager.crud_country import get_all_chunks

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load the embedding model globally
logger.info("Loading embedding model 'all-MiniLM-L6-v2'...")
try:
    embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
    logger.info("Embedding model loaded successfully.")
except Exception as e:
    logger.error(f"Failed to load embedding model: {e}")
    raise

# Global cache for law chunks and their embeddings
_LAW_CHUNKS_CACHE: List[Dict[str, Any]] = []
_LAW_EMBEDDINGS_CACHE: np.ndarray = np.array([])
_IS_CACHE_LOADED: bool = False

def _ensure_law_embeddings_loaded() -> None:
    """
    Ensures that all active country law chunks are loaded and embedded.
    Uses SessionLaw to connect to the law-specific database.
    """
    global _LAW_CHUNKS_CACHE, _LAW_EMBEDDINGS_CACHE, _IS_CACHE_LOADED
    
    if _IS_CACHE_LOADED:
        return
        
    logger.info("Loading and embedding country law chunks for semantic search...")
    
    # This session MUST connect to the database containing the 'document_chunks' table
    db = SessionLaw()
    try:
        chunks = get_all_chunks(db=db)
        if not chunks:
            logger.warning("No active country law chunks found in the database.")
            _IS_CACHE_LOADED = True
            return
            
        texts = [chunk.get("content", "") for chunk in chunks]
        
        # Compute embeddings for all chunks at once
        embeddings = embedding_model.encode(texts, convert_to_numpy=True)
        
        _LAW_CHUNKS_CACHE = chunks
        _LAW_EMBEDDINGS_CACHE = embeddings
        _IS_CACHE_LOADED = True
        logger.info(f"Successfully cached embeddings for {len(chunks)} country law chunks.")
        
    except Exception as e:
        logger.error(f"Error loading country law embeddings: {e}")
    finally:
        db.close()

def get_law_chunks_by_similarity(corporate_text: str, threshold: float = 0.75) -> List[Dict[str, Any]]:
    """
    Finds relevant country law chunks that have a cosine similarity score >= threshold.
    """
    if not corporate_text or not corporate_text.strip():
        logger.warning("Empty corporate_text provided to vector search.")
        return []
        
    _ensure_law_embeddings_loaded()
    
    if not _LAW_CHUNKS_CACHE or _LAW_EMBEDDINGS_CACHE.size == 0:
        logger.warning("Cannot perform search: No law embeddings available.")
        return []
        
    try:
        # Encode the corporate text
        corp_embedding = embedding_model.encode([corporate_text], convert_to_numpy=True)
        
        # Compute cosine similarity
        similarities = cosine_similarity(corp_embedding, _LAW_EMBEDDINGS_CACHE)[0]
        
        # Filter chunks that meet or exceed the threshold
        relevant_chunks = []
        for idx, score in enumerate(similarities):
            if score >= threshold:
                chunk = _LAW_CHUNKS_CACHE[idx].copy()
                chunk["similarity_score"] = float(score)
                relevant_chunks.append(chunk)
                
        # Sort by highest score first
        relevant_chunks.sort(key=lambda x: x["similarity_score"], reverse=True)
        
        logger.info(f"Vector search returned {len(relevant_chunks)} law chunks meeting threshold >= {threshold}.")
        return relevant_chunks
        
    except Exception as e:
        logger.error(f"Error performing vector search: {e}")
        return []