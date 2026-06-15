"""
reranker.py
-----------
Phase 1 of the RAG Pipeline Upgrade.

Implements the BGEReranker class, which acts as a refinement layer between
the Qdrant Hybrid Search Retriever and the final LLM inference step.

Flow:
    Retriever (Top-20 broad results)
        -> BGEReranker (re-scores & filters to Top-N)
            -> ComplianceEngine / Mapper

Model: BAAI/bge-reranker-v2-m3
  - A cross-encoder model: it evaluates each (query, document) pair jointly,
    giving it deeper semantic understanding than a bi-encoder retriever.
  - 568M parameters; can run on CPU if GPU VRAM is exhausted by the LLMs.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# --- Dependency Guard ---
# sentence-transformers is required. Install via:
#   pip install sentence-transformers
try:
    from sentence_transformers import CrossEncoder
    _CROSS_ENCODER_AVAILABLE = True
except ImportError:
    CrossEncoder = None
    _CROSS_ENCODER_AVAILABLE = False
    logger.error(
        "sentence-transformers is not installed. "
        "Please run: pip install sentence-transformers"
    )


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class RerankedDocument:
    """
    Represents a single document chunk after reranking.
    Extends the raw retriever output dict with a relevance score.
    """
    hash: str
    content: str
    score: float
    # Preserve any extra metadata from the retriever payload
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Returns a plain dict for backward compatibility with the engine."""
        return {
            "hash": self.hash,
            "content": self.content,
            "score": self.score,
            **self.metadata,
        }


# ---------------------------------------------------------------------------
# BGEReranker
# ---------------------------------------------------------------------------

class BGEReranker:
    """
    Reranking layer using BAAI/bge-reranker-v2-m3.

    Takes a broad list of document chunks returned by the Qdrant Retriever
    and re-scores each (query, document) pair with a cross-encoder, then
    returns only the top_n most semantically relevant chunks.

    This filters noise introduced by approximate nearest-neighbour search
    and BM25 keyword matching, providing the LLM with a tight, high-signal
    context window.

    Usage:
        reranker = BGEReranker()
        refined = reranker.rerank(query, broad_chunks, top_n=5)
        # refined -> List[Dict]  (same shape as Retriever output + "score")
    """

    MODEL_NAME: str = "BAAI/bge-reranker-v2-m3"

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        max_length: int = 512,
    ):
        """
        Loads the BGE cross-encoder model.

        Args:
            model_name:  HuggingFace model ID. Defaults to BAAI/bge-reranker-v2-m3.
            device:      'cuda', 'cpu', or None (auto-detects GPU if available).
                         Set 'cpu' explicitly to offload from GPU when VRAM is
                         shared with Llama 3 / Qwen 2.5.
            max_length:  Maximum token length for (query + document) pairs.
                         512 is the model's native limit.
        """
        if not _CROSS_ENCODER_AVAILABLE:
            raise ImportError(
                "sentence-transformers is required for BGEReranker. "
                "Install it with: pip install sentence-transformers"
            )

        self.model_name = model_name or self.MODEL_NAME
        self.max_length = max_length

        # Auto-detect device if not specified
        if device is None:
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        self.device = device
        logger.info(
            "Loading reranker model '%s' on %s...",
            self.model_name,
            self.device.upper(),
        )

        try:
            self.model = CrossEncoder(
                model_name_or_path=self.model_name,
                device=self.device,
                max_length=self.max_length,
            )
            logger.info("BGEReranker initialized successfully.")
        except Exception as e:
            logger.error("Failed to load reranker model '%s': %s", self.model_name, e)
            raise

    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_n: int = 5,
        score_threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Re-scores and re-orders a list of document chunks by relevance to the query.

        Args:
            query:           The (optionally Llama-3-optimized) search query.
            documents:       A list of dicts from the Retriever, each containing
                             at minimum: {"hash": str, "content": str}.
            top_n:           Number of top-scoring documents to return.
            score_threshold: Optional minimum score cutoff. Documents scoring
                             below this value are discarded even if within top_n.

        Returns:
            A list of dicts (top_n or fewer), sorted by descending relevance score.
            Each dict is the original retriever payload enriched with a "score" key.

        Raises:
            ValueError: If query or documents are empty.
        """
        if not query or not query.strip():
            raise ValueError("BGEReranker.rerank() received an empty query.")

        if not documents:
            logger.warning("BGEReranker received an empty document list. Returning [].")
            return []

        # --- 1. Build (query, document_text) pairs for batch inference ---
        pairs = []
        valid_documents = []

        for doc in documents:
            content = doc.get("content", "").strip()
            if not content:
                logger.debug("Skipping document with empty content (hash: %s).", doc.get("hash"))
                continue
            pairs.append([query, content])
            valid_documents.append(doc)

        if not pairs:
            logger.warning("All documents had empty content. Returning [].")
            return []

        logger.info(
            "Reranking %d document(s) against query (top_n=%d)...",
            len(pairs),
            top_n,
        )

        # --- 2. Score all pairs in a single batched forward pass ---
        try:
            scores: List[float] = self.model.predict(pairs, show_progress_bar=False).tolist()
        except Exception as e:
            logger.error("CrossEncoder.predict() failed: %s", e)
            raise

        # --- 3. Attach scores and filter ---
        reranked: List[RerankedDocument] = []
        for doc, score in zip(valid_documents, scores):
            # Apply optional score threshold
            if score_threshold is not None and score < score_threshold:
                continue

            reranked.append(
                RerankedDocument(
                    hash=doc.get("hash", ""),
                    content=doc.get("content", ""),
                    score=round(float(score), 6),
                    # Carry forward any extra keys (e.g. source, article_id)
                    metadata={
                        k: v for k, v in doc.items()
                        if k not in ("hash", "content")
                    },
                )
            )

        # --- 4. Sort descending by score and slice ---
        reranked.sort(key=lambda d: d.score, reverse=True)
        top_results = reranked[:top_n]

        logger.info(
            "Reranking complete. Returning %d/%d documents. "
            "Top score: %.4f | Bottom score: %.4f",
            len(top_results),
            len(pairs),
            top_results[0].score if top_results else 0.0,
            top_results[-1].score if top_results else 0.0,
        )

        # Return as plain dicts for backward compatibility with engine.py
        return [doc.to_dict() for doc in top_results]
