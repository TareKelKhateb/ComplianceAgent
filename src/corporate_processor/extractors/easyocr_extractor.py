"""
src/corporate_processor/extractors/easyocr_extractor.py
---------------------------------------------------------
CorporateEasyOCRExtractor — adapter over the legacy EasyOcrExtractor.

Delegates all work to ``src.document_processor.extractors.EasyOcrExtractor``
without copying any logic.

Configuration (all optional, with sensible defaults)
----------------------------------------------------
POPPLER_PATH   Path to Poppler binaries; defaults to None (relies on PATH).
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

# pyrefly: ignore [missing-import]
from src.document_processor.extractors.easyocr_extractor import (
    EasyOcrExtractor as _LegacyEasyOcrExtractor,
)

from .base_extractor import CorporateBaseExtractor

logger = logging.getLogger(__name__)


class CorporateEasyOCRExtractor(CorporateBaseExtractor):
    """
    Corporate adapter for the local EasyOCR extractor.

    Wraps the legacy ``EasyOcrExtractor`` from ``document_processor`` and
    exposes the ``extract_text(pdf_path) -> str`` interface required by
    ``CorporateBaseExtractor``.

    Parameters
    ----------
    languages : list[str]
        OCR languages passed to EasyOCR. Defaults to ``["ar", "en"]``.
    gpu : bool
        Whether to use GPU acceleration. Defaults to ``True``.
    poppler_path : str, optional
        Path to Poppler binaries for pdf2image. Falls back to the
        ``POPPLER_PATH`` environment variable, then to ``None`` (PATH-based).
    dpi : int
        Resolution for PDF-to-image conversion. Defaults to ``300``.
    """

    def __init__(
        self,
        languages: Optional[List[str]] = None,
        gpu: bool = True,
        poppler_path: Optional[str] = None,
        dpi: int = 300,
    ) -> None:
        resolved_poppler = (
            poppler_path
            or os.getenv("POPPLER_PATH")
            or None
        )
        self._delegate = _LegacyEasyOcrExtractor(
            languages=languages or ["ar", "en"],
            gpu=gpu,
            poppler_path=resolved_poppler,
            dpi=dpi,
        )
        logger.debug(
            "[CorporateEasyOCRExtractor] Initialised — languages=%s gpu=%s",
            languages or ["ar", "en"],
            gpu,
        )

    def extract_text(self, pdf_path: str) -> str:
        """
        Convert the PDF to images and extract text with EasyOCR.

        Delegates entirely to the legacy ``EasyOcrExtractor.extract_text()``.

        Parameters
        ----------
        pdf_path : str
            Path to the PDF file.

        Returns
        -------
        str
            Page-separated Markdown string with ``## Page N`` headers.

        Raises
        ------
        FileNotFoundError
            If the PDF does not exist.
        RuntimeError
            For any EasyOCR or pdf2image failure.
        """
        logger.info(
            "[CorporateEasyOCRExtractor] Extracting text from: %s", pdf_path
        )
        return self._delegate.extract_text(pdf_path)
