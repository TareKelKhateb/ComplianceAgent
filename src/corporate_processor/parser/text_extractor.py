"""
text_extractor.py
-----------------
TextExtractor — pdfplumber-based raw text extraction.

Responsibility (single):
    Open a text-based PDF and concatenate the text from every page into a
    single string. No API calls, no JSON parsing, no routing logic.
"""

from __future__ import annotations

import logging
from pathlib import Path

try:
    import pdfplumber  # type: ignore[import]
except ImportError as _e:
    raise ImportError("pdfplumber is required: pip install pdfplumber") from _e

logger = logging.getLogger(__name__)


class TextExtractor:
    """
    Extracts the full text content of a text-based PDF using pdfplumber.

    The extractor is stateless — it holds no file handles between calls and
    is safe to reuse across multiple documents.

    Example
    -------
    ::

        extractor = TextExtractor()
        text = extractor.extract("path/to/document.pdf")
    """

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def extract(self, file_path: str) -> str:
        """
        Extract and concatenate text from all pages of a PDF.

        Each page's text is separated by ``"\\n\\n"`` to preserve the visual
        paragraph structure that helps the downstream LLM extract metadata
        more reliably.

        Parameters
        ----------
        file_path : str
            Absolute or relative path to the PDF file.

        Returns
        -------
        str
            Concatenated text from all pages. Empty string if no text is
            found (e.g. the file has zero pages or is image-based).

        Raises
        ------
        FileNotFoundError
            If the file does not exist at the given path.
        RuntimeError
            If pdfplumber raises an unexpected error during reading.
        """
        resolved = Path(file_path).expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(
                f"PDF not found at: '{file_path}'"
            )

        logger.info(
            "[TextExtractor] Extracting text from: %s", resolved.name
        )

        page_texts: list[str] = []
        try:
            with pdfplumber.open(str(resolved)) as pdf:
                total_pages = len(pdf.pages)
                for i, page in enumerate(pdf.pages, start=1):
                    text = page.extract_text()
                    if text:
                        page_texts.append(text.strip())
                    else:
                        logger.debug(
                            "[TextExtractor] Page %d/%d yielded no text.",
                            i, total_pages,
                        )
        except Exception as exc:
            raise RuntimeError(
                f"pdfplumber failed to read '{resolved}': {exc}"
            ) from exc

        full_text = "\n\n".join(page_texts)

        logger.info(
            "[TextExtractor] Extracted %d characters from %d/%d page(s).",
            len(full_text),
            len(page_texts),
            total_pages if "total_pages" in dir() else "?",
        )

        return full_text
