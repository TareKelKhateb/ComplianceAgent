"""
src/corporate_processor/extractors/__init__.py
----------------------------------------------
Public surface for the corporate OCR extractor adapters.

These classes are thin adapters over the legacy extractors that live in
``src.document_processor.extractors``.  They present the same
``extract_text(pdf_path) -> str`` interface so the rest of the corporate
pipeline never imports from ``document_processor`` directly.

Usage::

    from src.corporate_processor.extractors import (
        CorporateBaseExtractor,
        CorporateMistralExtractor,
        CorporateEasyOCRExtractor,
    )
"""

# pyrefly: ignore [missing-import]
from .base_extractor import CorporateBaseExtractor
# pyrefly: ignore [missing-import]
from .mistral_extractor import CorporateMistralExtractor
# pyrefly: ignore [missing-import]
from .easyocr_extractor import CorporateEasyOCRExtractor

__all__ = [
    "CorporateBaseExtractor",
    "CorporateMistralExtractor",
    "CorporateEasyOCRExtractor",
]
