import os
import re
import numpy as np
from typing import List, Dict, Any
from PIL import Image
from pdf2image import convert_from_path

import easyocr

from .base_extractor import BaseExtractor


class EasyOcrExtractor(BaseExtractor):
    """
    Extractor implementation backed by EasyOCR (local, no API required).

    Processes a PDF page-by-page, detects Arabic article headers,
    and returns one unified Markdown string for the whole document.
    """

    def __init__(
        self,
        languages: List[str] | None = None,
        gpu: bool = True,
        poppler_path: str | None = None,
        dpi: int = 300,
    ) -> None:
        """
        Args:
            languages (list[str]): Language codes for EasyOCR. Defaults to ['ar', 'en'].
            gpu (bool):            Enable CUDA acceleration. Defaults to True.
            poppler_path (str):    Path to the Poppler bin directory (Windows only).
            dpi (int):             Resolution used when converting PDF pages to images.
        """
        self.languages = languages or ["ar", "en"]
        self.gpu = gpu
        self.poppler_path = poppler_path
        self.dpi = dpi

        # Lazily initialized so the heavy EasyOCR model loads only on first call
        self._reader: easyocr.Reader | None = None

        self._article_pattern = re.compile(
            r'^(مادة|المادة)'
            r'\s*[\(\（]?\s*'
            r'(\d+|[٠-٩]+|[أ-ي]+)'
            r'\s*[\)\）]?\s*:?\s*$'
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_reader(self) -> easyocr.Reader:
        if self._reader is None:
            self._reader = easyocr.Reader(self.languages, gpu=self.gpu)
            mode = "GPU" if self.gpu else "CPU"
            print(f"[!] EasyOCR: Initialized in {mode} mode.")
        return self._reader

    def _pdf_to_images(self, pdf_path: str):
        """Yields PIL Images for each page of the PDF."""
        kwargs: Dict[str, Any] = {"dpi": self.dpi, "thread_count": 2}
        if self.poppler_path:
            kwargs["poppler_path"] = self.poppler_path
        return convert_from_path(pdf_path, **kwargs)

    def _format_line(self, text: str) -> str:
        """Apply Markdown heading to detected article lines."""
        content = text.strip()
        if self._article_pattern.match(content):
            return f"### {content}"
        return content

    # ------------------------------------------------------------------
    # BaseExtractor contract
    # ------------------------------------------------------------------

    def extract_text(self, pdf_path: str) -> str:
        """
        Run EasyOCR on every page and return a single Markdown string.

        Page boundaries are marked with a ``## Page N`` heading so that
        downstream chunkers can optionally split on them.
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"[EasyOCR] PDF not found: {pdf_path}")

        reader = self._get_reader()
        pages = self._pdf_to_images(pdf_path)
        markdown_parts: List[str] = []

        print(f"[*] EasyOCR: Extracting {len(pages)} page(s) from '{pdf_path}'…")

        for i, page_image in enumerate(pages):
            img_array = np.array(page_image)
            results = reader.readtext(img_array)

            page_lines: List[str] = []
            for _, text, _ in results:
                formatted = self._format_line(text)
                if formatted:
                    page_lines.append(formatted)

            page_md = f"## Page {i + 1}\n\n" + "\n".join(page_lines)
            markdown_parts.append(page_md)

            # Release memory ASAP — pages can be large at 300 DPI
            page_image.close()

        full_markdown = "\n\n---\n\n".join(markdown_parts)
        print(f"[+] EasyOCR: Extraction complete ({len(full_markdown):,} chars).")
        return full_markdown
