"""
src/corporate_processor/ocr_engine.py
--------------------------------------
CorporateOCREngine — adapter over the legacy document_processor OCREngine.

Responsibility (single):
    Accept a ``CorporateBaseExtractor`` strategy, run it against a PDF, and
    return the extracted text string.  No routing, no API calls, no JSON.

Why an adapter instead of a direct import?
    The ``PipelineManager`` must only import from ``corporate_processor``.
    This thin wrapper satisfies that constraint while delegating all real
    OCR work to the battle-tested legacy engine in ``document_processor``.

The legacy ``OCREngine`` is injected at construction time (Strategy Pattern),
which keeps this class testable — pass a mock extractor in unit tests.
"""

from __future__ import annotations

import logging

# pyrefly: ignore [missing-import]
from src.document_processor.ocr_engine import OCREngine as _LegacyOCREngine

from .extractors.base_extractor import CorporateBaseExtractor
from .extractors.mistral_extractor import CorporateMistralExtractor

logger = logging.getLogger(__name__)


class CorporateOCREngine:
    """
    Corporate wrapper around the legacy ``OCREngine``.

    Accepts any ``CorporateBaseExtractor`` and uses the legacy engine's
    ``process_document()`` method — which applies extractor-specific
    formatting (light for Mistral, full clean-up for EasyOCR) — so the
    formatting logic stays in one place and is never duplicated.

    Parameters
    ----------
    extractor : CorporateBaseExtractor, optional
        The OCR strategy to use.  Defaults to ``CorporateMistralExtractor``
        (best quality for corporate compliance documents; requires
        ``MISTRAL_API_KEY`` in the environment).

    Example
    -------
    ::

        engine = CorporateOCREngine()                          # Mistral default
        text   = engine.process_document("scanned_doc.pdf")

        # Or inject EasyOCR for GPU-local processing:
        from src.corporate_processor.extractors import CorporateEasyOCRExtractor
        engine = CorporateOCREngine(CorporateEasyOCRExtractor(gpu=False))
    """

    def __init__(
        self,
        extractor: CorporateBaseExtractor | None = None,
    ) -> None:
        self._extractor: CorporateBaseExtractor = (
            extractor or CorporateMistralExtractor()
        )
        # The legacy engine expects a BaseExtractor (document_processor ABC).
        # CorporateBaseExtractor has the same interface, so we pass it directly.
        self._engine = _LegacyOCREngine(extractor=self._extractor)  # type: ignore[arg-type]

        logger.debug(
            "[CorporateOCREngine] Initialised — extractor=%s",
            type(self._extractor).__name__,
        )

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def process_document(self, pdf_path: str) -> str:
        """
        Run OCR on an image-based PDF and return the formatted text.

        Delegates to the legacy ``OCREngine.process_document()`` which:
        - Calls ``extractor.extract_text(pdf_path)`` for raw text.
        - Applies light formatting (Mistral) or full clean-up (EasyOCR).

        Parameters
        ----------
        pdf_path : str
            Absolute or relative path to the PDF file.

        Returns
        -------
        str
            Formatted Markdown string ready for the Llama API.

        Raises
        ------
        FileNotFoundError
            Propagated from the extractor if the file does not exist.
        RuntimeError
            Propagated from the extractor or formatter on engine failure.
        """
        logger.info(
            "[CorporateOCREngine] Processing (OCR): %s  extractor=%s",
            pdf_path,
            type(self._extractor).__name__,
        )
        result: str = self._engine.process_document(pdf_path)
        logger.info(
            "[CorporateOCREngine] OCR complete — %d characters extracted.",
            len(result),
        )
        return result
