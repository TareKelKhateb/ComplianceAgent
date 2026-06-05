"""
orchestrator.py
---------------
DocumentParser — the single entry-point for all PDF parsing in the
corporate processor pipeline.

Responsibility:
    Coordinate the three specialist components:
        PDFRouter      → classify the PDF (text vs. image)
        TextExtractor  → pull raw text from text-based PDFs
        LlamaClient    → call the Llama API and return structured metadata

    The orchestrator also handles:
        - Path resolution and SHA-256 hashing
        - Store-compatible dict assembly
        - Deterministic doc-ID derivation
        - The OCR placeholder hook (documented, not yet implemented)

Zero side-effects: this module does NOT import from or modify any module
outside the ``src/corporate_processor/parser/`` package.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Optional

# pyrefly: ignore [missing-import]
from .models import ParseResult, ParserConfig, PdfType
from .router import PDFRouter
from .text_extractor import TextExtractor
from .llama_client import LlamaClient

logger = logging.getLogger(__name__)


class DocumentParser:
    """
    Orchestrates the full corporate PDF parsing pipeline.

    Parameters
    ----------
    config : ParserConfig, optional
        Configuration object built from environment variables by default.
        Pass an explicit instance to override in tests.

    Example
    -------
    ::

        parser = DocumentParser()

        result = parser.parse_text("./docs/aml_policy_2024.pdf")
        if result.success:
            # result.data is ready to pass to MetadataStore.insert_document()
            store.insert_document(result.data)
        else:
            print(result.message)

    Routing example (auto-detects PDF type)::

        result = parser.route("./docs/scanned_contract.pdf")
    """

    def __init__(self, config: Optional[ParserConfig] = None) -> None:
        self._cfg = config or ParserConfig()
        self._router    = PDFRouter(self._cfg)
        self._extractor = TextExtractor()
        self._llama     = LlamaClient(self._cfg)
        logger.debug(
            "[DocumentParser] Initialised — model=%s threshold=%d",
            self._cfg.model, self._cfg.ocr_threshold,
        )

    # ==================================================================
    # Public API
    # ==================================================================

    def route(self, file_path: str) -> ParseResult:
        """
        Inspect the PDF and dispatch to the correct parse strategy.

        Decision
        --------
        1. Delegate to :class:`~router.PDFRouter` to classify the file.
        2. ``PdfType.TEXT``    → :meth:`parse_text`
        3. ``PdfType.IMAGE``   → :meth:`_parse_with_ocr` (placeholder)
        4. ``PdfType.UNKNOWN`` → return a failure ``ParseResult``

        Parameters
        ----------
        file_path : str
            Path to the PDF file.

        Returns
        -------
        ParseResult
            Result from the dispatched strategy.
        """
        resolved = self._resolve_path(file_path)
        if resolved is None:
            return ParseResult(
                success=False,
                message=f"File not found: '{file_path}'",
            )

        pdf_type = self._router.detect(resolved)

        if pdf_type is PdfType.TEXT:
            logger.info("[DocumentParser.route] Text-based PDF → parse_text()")
            return self.parse_text(file_path)

        if pdf_type is PdfType.IMAGE:
            logger.info("[DocumentParser.route] Image-based PDF → _parse_with_ocr()")
            return self._parse_with_ocr(file_path)

        # PdfType.UNKNOWN
        logger.error(
            "[DocumentParser.route] Could not classify PDF: '%s'", file_path
        )
        return ParseResult(
            success=False,
            message=(
                f"Could not classify PDF type for '{file_path}'. "
                "The file may be corrupt or unreadable."
            ),
            pdf_type=pdf_type,
        )

    def parse_text(self, file_path: str) -> ParseResult:
        """
        Parse a **text-based** PDF end-to-end.

        Pipeline
        --------
        1. Resolve and validate the file path.
        2. Hash the raw PDF bytes (SHA-256) + capture file size.
        3. Extract text via :class:`~text_extractor.TextExtractor`.
        4. Validate extracted text length.
        5. Call the Llama API via :class:`~llama_client.LlamaClient`.
        6. Assemble and return a store-compatible ``ParseResult``.

        Parameters
        ----------
        file_path : str
            Path to the PDF file.

        Returns
        -------
        ParseResult
            - ``success=True``  → ``.data`` is ready for ``insert_document()``.
            - ``success=False`` → ``.data`` is ``None``; ``.message`` explains why.
        """
        # ── 1. Resolve path ──────────────────────────────────────────────────
        resolved = self._resolve_path(file_path)
        if resolved is None:
            return ParseResult(
                success=False,
                message=f"File not found: '{file_path}'",
                parse_method="text",
            )

        logger.info("[DocumentParser.parse_text] Processing: %s", resolved)

        # ── 2. Hash + size ───────────────────────────────────────────────────
        try:
            raw_bytes = Path(resolved).read_bytes()
        except OSError as exc:
            logger.error("[DocumentParser.parse_text] Cannot read file: %s", exc)
            return ParseResult(
                success=False,
                message=f"Cannot read file '{resolved}': {exc}",
                parse_method="text",
            )

        sha256_hash    = hashlib.sha256(raw_bytes).hexdigest()
        file_size_bytes = len(raw_bytes)

        # ── 3. Extract text ──────────────────────────────────────────────────
        try:
            raw_text = self._extractor.extract(resolved)
        except (FileNotFoundError, RuntimeError) as exc:
            logger.error("[DocumentParser.parse_text] Extraction failed: %s", exc)
            return ParseResult(
                success=False,
                message=f"Text extraction failed: {exc}",
                parse_method="text",
            )

        # ── 4. Guard: minimum content ────────────────────────────────────────
        if not raw_text or len(raw_text.strip()) < 20:
            return ParseResult(
                success=False,
                message=(
                    "Extracted text is empty or too short. "
                    "The PDF may be image-based — use route() to auto-detect."
                ),
                parse_method="text",
                raw_text=raw_text,
                pdf_type=PdfType.TEXT,
            )

        logger.info(
            "[DocumentParser.parse_text] Extracted %d characters.", len(raw_text)
        )

        # ── 5. Llama API ─────────────────────────────────────────────────────
        try:
            metadata = self._llama.extract_metadata(raw_text)
        except ValueError as exc:
            # Config / JSON parse errors — do not retry
            logger.error(
                "[DocumentParser.parse_text] Metadata extraction failed: %s", exc
            )
            return ParseResult(
                success=False,
                message=f"Metadata extraction failed: {exc}",
                parse_method="text",
                raw_text=raw_text,
                pdf_type=PdfType.TEXT,
            )
        except Exception as exc:  # noqa: BLE001  (openai.APIError, network, etc.)
            logger.error(
                "[DocumentParser.parse_text] Llama API error: %s", exc, exc_info=True
            )
            return ParseResult(
                success=False,
                message=f"Llama API call failed: {exc}",
                parse_method="text",
                raw_text=raw_text,
                pdf_type=PdfType.TEXT,
            )

        # ── 6. Assemble store-compatible payload ─────────────────────────────
        doc_id = self._derive_doc_id(resolved, metadata)
        store_payload: dict[str, Any] = {
            # Identity
            "id":               doc_id,
            "file_url":         "",           # Caller sets this from their context
            "sha256_hash":      sha256_hash,
            # LLM-extracted metadata
            "title":            metadata.get("title"),
            "document_type":    metadata.get("document_type"),
            "issuing_entity":   metadata.get("issuing_entity"),
            "document_number":  metadata.get("document_number"),
            "year":             metadata.get("year"),
            "date":             metadata.get("date"),
            "language":         metadata.get("language"),
            "category":         metadata.get("category"),
            "subcategory":      metadata.get("subcategory"),
            # File-level fields
            "file_path":        resolved,
            "file_size_bytes":  file_size_bytes,
            "download_status":  "downloaded",
        }

        logger.info(
            "[DocumentParser.parse_text] ✓ id='%s'  title='%s'",
            doc_id, store_payload.get("title", "—"),
        )

        return ParseResult(
            success=True,
            message=(
                f"Text-based PDF parsed successfully. "
                f"Extracted {len(raw_text):,} characters. "
                f"Derived id='{doc_id}'."
            ),
            parse_method="text",
            data=store_payload,
            raw_text=raw_text,
            pdf_type=PdfType.TEXT,
        )

    # ==================================================================
    # Placeholder: OCR path
    # ==================================================================

    def _parse_with_ocr(self, file_path: str) -> ParseResult:
        """
        PLACEHOLDER — Hook for integrating the legacy OCR engine.

        When implemented, this method should:

        1. Instantiate the appropriate extractor subclass from
           ``src.document_processor.extractors`` (e.g. ``MistralExtractor``).
        2. Wrap it in ``OCREngine`` from ``src.document_processor.ocr_engine``.
        3. Call ``ocr_engine.process_document(file_path)`` to obtain
           the formatted Markdown text.
        4. Pass that text to ``self._llama.extract_metadata(text)`` to get
           the structured metadata dict.
        5. Assemble a ``ParseResult`` with ``parse_method="ocr"`` using the
           same helper methods as :meth:`parse_text`.

        Integration sketch::

            # from src.document_processor.ocr_engine import OCREngine
            # from src.document_processor.extractors.mistral_extractor import (
            #     MistralExtractor,
            # )
            # extractor = MistralExtractor(model="mistral-ocr-latest")
            # engine    = OCREngine(extractor=extractor)
            # raw_text  = engine.process_document(file_path)
            # metadata  = self._llama.extract_metadata(raw_text)
            # ... assemble ParseResult ...

        Parameters
        ----------
        file_path : str
            Path to the image-based PDF requiring OCR.

        Returns
        -------
        ParseResult
            Currently returns a not-implemented failure result.
        """
        logger.warning(
            "[DocumentParser._parse_with_ocr] OCR not yet implemented for: %s",
            file_path,
        )
        return ParseResult(
            success=False,
            message=(
                "OCR parsing is not yet implemented. "
                "This PDF appears to be image-based. "
                "Integrate the legacy OCREngine via the documented hook in "
                "_parse_with_ocr()."
            ),
            parse_method="ocr",
            pdf_type=PdfType.IMAGE,
        )

    # ==================================================================
    # Private helpers
    # ==================================================================

    def _resolve_path(self, file_path: str) -> Optional[str]:
        """Return the absolute path string, or None if the file does not exist."""
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            logger.warning("[DocumentParser] File not found: %s", path)
            return None
        return str(path)

    def _derive_doc_id(self, resolved_path: str, metadata: dict[str, Any]) -> str:
        """
        Derive a URL-safe, human-readable document ID.

        Strategy
        --------
        1. Slugify ``metadata["title"]`` (or fall back to the filename stem).
        2. Prepend the 4-digit year when available.
        3. Append a 6-character SHA-256 prefix of the resolved path for
           uniqueness when multiple documents share a similar title.

        Returns
        -------
        str
            Lowercase, underscore-separated ID string compatible with the
            custom-ID convention used elsewhere in the project
            (e.g. ``"2024_aml_policy_a3f9c1"``).
        """
        title: str = metadata.get("title") or Path(resolved_path).stem
        year: str  = metadata.get("year") or ""

        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
        if len(slug) > 40:
            slug = slug[:40].rstrip("_")

        path_hash = hashlib.sha256(resolved_path.encode()).hexdigest()[:6]
        parts = [p for p in [year, slug, path_hash] if p]
        return "_".join(parts)
