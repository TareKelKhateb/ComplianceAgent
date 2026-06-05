"""
src/corporate_processor/extractors/base_extractor.py
-----------------------------------------------------
CorporateBaseExtractor — abstract interface for all corporate OCR extractors.

Mirrors the contract of ``src.document_processor.extractors.BaseExtractor``
so that the corporate pipeline never needs to import from document_processor
directly.  Concrete adapters (Mistral, EasyOCR) implement this class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class CorporateBaseExtractor(ABC):
    """
    Abstract base class for all corporate OCR extractor adapters.

    Every extractor — regardless of the underlying engine — must implement
    ``extract_text``.  The ``CorporateOCREngine`` and ``PipelineManager``
    depend only on this interface, never on concrete implementations.
    """

    @abstractmethod
    def extract_text(self, pdf_path: str) -> str:
        """
        Extract the full text content of a PDF and return it as a string.

        Args:
            pdf_path (str): Absolute or relative path to the input PDF file.

        Returns:
            str: A string (typically Markdown) containing the full document text.

        Raises:
            FileNotFoundError: If the PDF does not exist at the given path.
            RuntimeError:      For any engine-specific failure during extraction.
        """
        ...
