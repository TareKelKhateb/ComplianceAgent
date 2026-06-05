"""
src/corporate_processor/extractors/mistral_extractor.py
--------------------------------------------------------
CorporateMistralExtractor — adapter over the legacy MistralExtractor.

Delegates all work to ``src.document_processor.extractors.MistralExtractor``
without copying any logic, so fixes or improvements in the legacy class are
automatically available here.

Configuration
-------------
MISTRAL_API_KEY   Required (read by the legacy extractor from the environment).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

# pyrefly: ignore [missing-import]
from src.document_processor.extractors.mistral_extractor import (
    MistralExtractor as _LegacyMistralExtractor,
)

from .base_extractor import CorporateBaseExtractor

logger = logging.getLogger(__name__)


class CorporateMistralExtractor(CorporateBaseExtractor):
    """
    Corporate adapter for the Mistral OCR API extractor.

    Wraps the legacy ``MistralExtractor`` from ``document_processor`` and
    exposes the same ``extract_text(pdf_path) -> str`` interface required by
    ``CorporateBaseExtractor``.

    Parameters
    ----------
    api_key : str, optional
        Mistral API key. Falls back to the ``MISTRAL_API_KEY`` environment
        variable (same behaviour as the legacy implementation).
    model : str
        Mistral OCR model name. Defaults to ``"mistral-ocr-latest"``.
    table_format : str
        Table rendering format. Defaults to ``"markdown"``.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "mistral-ocr-latest",
        table_format: str = "markdown",
    ) -> None:
        self._delegate = _LegacyMistralExtractor(
            api_key=api_key or os.getenv("MISTRAL_API_KEY"),
            model=model,
            table_format=table_format,
        )
        logger.debug(
            "[CorporateMistralExtractor] Initialised — model=%s", model
        )

    def extract_text(self, pdf_path: str) -> str:
        """
        Send the PDF to the Mistral OCR API and return a Markdown string.

        Delegates entirely to the legacy ``MistralExtractor.extract_text()``.

        Parameters
        ----------
        pdf_path : str
            Path to the PDF file.

        Returns
        -------
        str
            Markdown-formatted full document text (one section per page).

        Raises
        ------
        FileNotFoundError
            If the PDF does not exist.
        RuntimeError
            If the Mistral API call fails.
        """
        logger.info(
            "[CorporateMistralExtractor] Extracting text from: %s", pdf_path
        )
        return self._delegate.extract_text(pdf_path)
