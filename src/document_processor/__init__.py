"""
document_processor
------------------
Strategy-pattern document processing pipeline.

Public surface
~~~~~~~~~~~~~~
* ``OCRPipeline``       – main orchestrator (reads config/document_processor_config.yaml)
* ``BaseExtractor``     – extractor interface
* ``EasyOcrExtractor``  – local GPU-based extractor
* ``MistralExtractor``  – cloud Mistral OCR extractor
* ``BaseChunker``       – chunker interface
* ``OverlappingChunker``– fixed-size overlapping window chunker
* ``SemanticChunker``   – article-header-aware chunker (best for Diff Engine)
* ``SemanticHasher``    – Arabic normalisation + SHA-256 hashing (Layer 2)
* ``DiffEngine``        – version comparison engine (Layer 3)
"""

from .pipeline_manager import OCRPipeline

from .extractors.base_extractor import BaseExtractor
from .extractors.easyocr_extractor import EasyOcrExtractor
from .extractors.mistral_extractor import MistralExtractor

from .chunkers.base_chunker import BaseChunker
from .chunkers.overlapping_chunker import OverlappingChunker
from .chunkers.semantic_chunker import SemanticChunker

from .semantic_hasher import SemanticHasher
from .diff_engine import DiffEngine

__all__ = [
    # Pipeline
    "OCRPipeline",
    # Extractors
    "BaseExtractor",
    "EasyOcrExtractor",
    "MistralExtractor",
    # Chunkers
    "BaseChunker",
    "OverlappingChunker",
    "SemanticChunker",
    # Supporting layers
    "SemanticHasher",
    "DiffEngine",
]
