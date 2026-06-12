"""
retriever.py
------------
Retrieves relevant law chunks from the local Qdrant Vector Database
based on a user query. Updated to use Hybrid Search (Dense + Sparse).
"""

import sys
from unittest.mock import MagicMock

sys.modules["torchaudio"] = None
sys.modules["torchaudio.lib"] = None
sys.modules["torchaudio.lib.libtorchaudio"] = None

import os
import logging
from typing import Any, Dict, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

try:
    import torch
    # pyrefly: ignore [missing-import]
    from sentence_transformers import SentenceTransformer
    # pyrefly: ignore [missing-import]
    from fastembed import SparseTextEmbedding
    from qdrant_client import QdrantClient
    from qdrant_client import models
except ImportError as e:
    logger.error(f"Failed to import core inference libraries: {e}")
    logger.error("Please ensure you are running within the project's .venv and all dependencies are installed.")
    # Assign None to prevent NameErrors later
    torch = None
    SentenceTransformer = None
    SparseTextEmbedding = None
    QdrantClient = None
    models = None

class Retriever:
    """
    Connects to Qdrant and retrieves relevant law chunks based on 
    Hybrid Search (Semantic Similarity + BM25).
    """
    def __init__(self, 
                 collection_name: str = "law_chunks", 
                 dense_model_name: str = "all-MiniLM-L6-v2",
                 sparse_model_name: str = "Qdrant/bm25"):
        self.collection_name = collection_name
        self.dense_model_name = dense_model_name
        self.sparse_model_name = sparse_model_name
        
        # Resolve Qdrant path relative to project root
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.qdrant_path = os.path.join(base_dir, "data", "qdrant_db")
        
        try:
            logger.info(f"Connecting to Qdrant at {self.qdrant_path}")
            self.client = QdrantClient(path=self.qdrant_path)
            
            # Initialize Dense Embedding Model
            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"Loading dense model '{self.dense_model_name}' on {device.upper()}...")
            self.dense_model = SentenceTransformer(self.dense_model_name, device=device)
            
            # Initialize Sparse Embedding Model (BM25 via fastembed)
            logger.info(f"Loading sparse model '{self.sparse_model_name}'...")
            self.sparse_model = SparseTextEmbedding(model_name=self.sparse_model_name)
            
            logger.info("Retriever initialized successfully with Hybrid Search models.")
        except Exception as e:
            logger.error(f"Failed to initialize Retriever: {e}")
            raise

    def get_law_chunks(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """
        Embeds the query into Dense and Sparse vectors, and performs a 
        Hybrid Search against the Qdrant collection using RELATIVE_SCORE_FUSION.
        """
        if not query or not query.strip():
            logger.warning("Empty query provided to Retriever.")
            return []

        try:
            logger.debug(f"Encoding dense and sparse query vectors for: '{query}'")
            
            # 1. Calculate Dense Vector (Semantic Similarity)
            dense_vector = self.dense_model.encode(query).tolist()
            
            # 2. Calculate Sparse Vector (BM25) via fastembed
            sparse_embeddings = list(self.sparse_model.query_embed(query))
            if not sparse_embeddings:
                raise ValueError("Sparse embedding returned empty.")
                
            sparse_vector_data = sparse_embeddings[0] # Returns a SparseEmbedding object
            
            # Extract indices and values for Qdrant API
            sparse_vector = models.SparseVector(
                indices=sparse_vector_data.indices.tolist(),
                values=sparse_vector_data.values.tolist()
            )

            # 3. Construct Hybrid Query according to requirements
            # We configure specific weighting: 0.65 Sparse, 0.35 Dense
            hybrid_query = models.HybridQuery(
                dense=dense_vector,
                sparse=sparse_vector,
                dense_weight=0.35,
                sparse_weight=0.65,
                strategy=models.HybridStrategy.RELATIVE_SCORE_FUSION
            )

            # 4. Perform Qdrant Search using the requested hybrid construct
            search_results = self.client.search(
                collection_name=self.collection_name,
                query=hybrid_query,
                limit=limit,
                with_payload=True
            )
            
            formatted_results = []
            for point in search_results:
                payload = point.payload or {}
                formatted_results.append({
                    "hash": payload.get("chunk_hash", ""),
                    "content": payload.get("content", "")
                })
                
            logger.info(f"Retrieved {len(formatted_results)} relevant chunks from Hybrid Search.")
            return formatted_results

        except AttributeError as e:
            logger.error(f"HybridQuery/Strategy API not found in current qdrant_client.models. Please verify Qdrant client version: {e}")
            return []
        except Exception as e:
            logger.error(f"Error during hybrid vector search in Retriever: {e}")
            return []
