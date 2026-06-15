"""
Compliance Agent Inference Package
------------------------------------
This package provides the core inference and orchestration components 
for the Compliance Agent, including vector retrieval, SQLite mapping, 
BGE reranking, Llama 3 routing, and the central Qwen 2.5 LLM engine.

Upgraded Pipeline (Phase 1-3):
    Raw Query
        -> AgenticRouter   (Llama 3)       [router.py]
        -> Retriever       (Qdrant Hybrid) [retriever.py]
        -> BGEReranker     (bge-v2-m3)     [reranker.py]
        -> Mapper          (SQLite)        [mapper.py]
        -> ComplianceEngine (Qwen 2.5)    [engine.py]
"""

__version__ = "0.2.0"

# pyrefly: ignore [missing-import]
from src.inference.retriever import Retriever
# pyrefly: ignore [missing-import]
from src.inference.mapper import Mapper
# pyrefly: ignore [missing-import]
from src.inference.reranker import BGEReranker
# pyrefly: ignore [missing-import]
from src.inference.router import AgenticRouter
# pyrefly: ignore [missing-import]
from src.inference.engine import ComplianceEngine

__all__ = [
    "Retriever",
    "Mapper",
    "BGEReranker",
    "AgenticRouter",
    "ComplianceEngine",
]
