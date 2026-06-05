"""
router.py
---------
PDFRouter — density-based PDF type classifier.

Responsibility (single):
    Open a PDF with pdfplumber, measure average extracted characters per page,
    and return a PdfType that tells the orchestrator which parse path to use.

No API calls, no file writes, no side-effects.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

try:
    import pdfplumber  # type: ignore[import]
except ImportError as _e:
    raise ImportError("pdfplumber is required: pip install pdfplumber") from _e

# pyrefly: ignore [missing-import]
from .models import ParserConfig, PdfType

logger = logging.getLogger(__name__)


class PDFRouter:
    """
    Classifies a PDF as text-based or image-based using character-density
    heuristics extracted by pdfplumber.

    Parameters
    ----------
    config : ParserConfig
        Only ``config.ocr_threshold`` is used here.

    Decision rule
    -------------
    avg_chars_per_page > threshold  →  PdfType.TEXT
    avg_chars_per_page <= threshold →  PdfType.IMAGE
    """

    def __init__(self, config: ParserConfig) -> None:
        self._threshold = config.ocr_threshold

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def detect(self, file_path: str) -> PdfType:
        """
        Inspect *file_path* and return a :class:`~models.PdfType`.

        Parameters
        ----------
        file_path : str
            Absolute or relative path to the PDF.

        Returns
        -------
        PdfType
            - ``TEXT``    — avg chars/page > ``ocr_threshold``
            - ``IMAGE``   — avg chars/page ≤ ``ocr_threshold``
            - ``UNKNOWN`` — file missing or pdfplumber raised an error

        Notes
        -----
        The method never raises; all errors are logged and result in
        ``PdfType.UNKNOWN`` so the orchestrator can handle the failure
        gracefully.
        """
        resolved = self._resolve(file_path)
        if resolved is None:
            return PdfType.UNKNOWN

        try:
            avg = self._measure_density(resolved)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[PDFRouter] Failed to measure text density for '%s': %s",
                resolved, exc,
            )
            return PdfType.UNKNOWN

        logger.info(
            "[PDFRouter] '%s' — avg chars/page=%.1f (threshold=%d) → %s",
            Path(resolved).name,
            avg,
            self._threshold,
            "TEXT" if avg > self._threshold else "IMAGE",
        )

        return PdfType.TEXT if avg > self._threshold else PdfType.IMAGE

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve(self, file_path: str) -> Optional[str]:
        """Return the absolute path string, or None if the file does not exist."""
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            logger.warning("[PDFRouter] File not found: %s", path)
            return None
        return str(path)

    def _measure_density(self, resolved_path: str) -> float:
        """
        Open the PDF and return average extracted characters per page.

        Parameters
        ----------
        resolved_path : str
            Absolute path (already validated to exist).

        Returns
        -------
        float
            Average chars/page. Returns 0.0 for empty or page-less PDFs.

        Raises
        ------
        RuntimeError
            Wraps any pdfplumber error so the caller can log it uniformly.
        """
        try:
            with pdfplumber.open(resolved_path) as pdf:
                if not pdf.pages:
                    return 0.0
                total = sum(
                    len(page.extract_text() or "") for page in pdf.pages
                )
                return total / len(pdf.pages)
        except Exception as exc:
            raise RuntimeError(
                f"pdfplumber could not read '{resolved_path}': {exc}"
            ) from exc
