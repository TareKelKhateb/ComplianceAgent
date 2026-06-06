"""
src/corporate_processor/pipeline_manager.py
--------------------------------------------
PipelineManager — unified entry-point for corporate PDF processing.

This is the ONLY interface external code should use to process documents.
All specialist components are internal implementation details:

    PDFRouter          → classifies the PDF (TEXT or IMAGE)
    TextExtractor      → extracts text from text-based PDFs (pdfplumber)
    CorporateOCREngine → extracts text from image-based PDFs (OCR)
    LlamaClient        → sends raw text to Llama API, returns structured JSON

Pipeline flow
-------------

    file_path
        │
        ▼
    PDFRouter.detect()
        │
        ├─ PdfType.TEXT  ──► TextExtractor.extract()     ─┐
        │                                                  ├─► LlamaClient.extract_metadata()
        └─ PdfType.IMAGE ──► CorporateOCREngine.process() ─┘
                                                            │
                                                            ▼
                                                     ParseResult
                                                     (.data = store-compatible dict)

Zero side-effects:
    All imports are from ``src.corporate_processor.*``.
    No file from ``document_processor``, ``metadata_manager``, or
    ``shared_services`` is modified or even imported directly here.

Backward compatibility:
    The ``process()`` and ``process_batch()`` public methods preserve the
    functional interface expected by any existing external callers.
"""

from __future__ import annotations

import json
import hashlib
import logging
import re
from pathlib import Path
from typing import Any, List, Optional

# Relative imports — pipeline_manager lives inside corporate_processor, so
# sibling packages must be imported relatively, not via the src.* prefix.
# (Using src.* here would require the parser.__init__ chain to succeed at
#  import time, which fails when optional deps like openai are not yet installed.)
from .parser.models import ParseResult, ParserConfig, PdfType
from .parser.router import PDFRouter
from .parser.text_extractor import TextExtractor
from .parser.llama_client import LlamaClient
from .ocr_engine import CorporateOCREngine
from .extractors.base_extractor import CorporateBaseExtractor
# pyrefly: ignore [missing-import]
from src.corporate_processor.config import CorporateConfig
import re 

logger = logging.getLogger(__name__)

def detect_legal_structure(text: str) -> bool:
    """
    Analyzes the text to detect if the document has a formal legal structure.
    Returns True if at least 3 lines start with the pattern '^مادة' (Article).
    Uses Early Exit for performance: it stops scanning as soon as the threshold is met.
    """
    # Regex pattern: ^ matches the start of the line, followed by 'مادة' 
    # and then one or more digits (Arabic or Western).
    pattern = re.compile(r"^مادة\s*[\d١٢٣٤٥٦٧٨٩٠]+")
    
    match_count = 0
    
    # Iterate through lines; Early Exit ensures we don't scan unnecessarily
    for line in text.splitlines():
        clean_line = line.strip()
        
        # Check if the line is not empty and matches the pattern
        if clean_line and pattern.match(clean_line):
            match_count += 1
            
            # Threshold of 3 confirms we are in the main body, not an intro reference
            if match_count >= 3:
                return True
                
    return False


class PipelineManager:
    """
    Orchestrates the full corporate document processing pipeline.

    Parameters
    ----------
    config : ParserConfig, optional
        Configuration object (API keys, thresholds).  Built from environment
        variables by default.
    ocr_extractor : CorporateBaseExtractor, optional
        The OCR strategy to inject into ``CorporateOCREngine``.  Defaults to
        ``CorporateMistralExtractor`` (requires ``MISTRAL_API_KEY``).
        Inject ``CorporateEasyOCRExtractor`` for GPU-local OCR.

    Example — single document
    --------------------------
    ::

        from src.corporate_processor.pipeline_manager import PipelineManager

        mgr    = PipelineManager()
        result = mgr.process("./docs/aml_policy_2024.pdf")

        if result.success:
            store.insert_document(result.data)   # drop-in with MetadataStore

    Example — custom OCR extractor
    --------------------------------
    ::

        from src.corporate_processor.extractors import CorporateEasyOCRExtractor

        mgr = PipelineManager(ocr_extractor=CorporateEasyOCRExtractor(gpu=False))
        result = mgr.process("./docs/scanned_contract.pdf")

    Example — batch
    ----------------
    ::

        results = mgr.process_batch(["doc1.pdf", "doc2.pdf", "doc3.pdf"])
        for r in results:
            print(r.success, r.message)
    """

    def __init__(
        self,
        config: Optional[CorporateConfig] = None,
        ocr_extractor: Optional[CorporateBaseExtractor] = None,
    ) -> None:
        # Enforce dependency injection from CorporateConfig
        self.config = config or CorporateConfig.load()
        
        # Build ParserConfig locally to satisfy legacy components without os.environ lookups
        self._cfg = ParserConfig(
            api_key=self.config.llama_api_key,
            base_url=self.config.llama_api_base_url,
            model=self.config.llama_model,
            ocr_threshold=self.config.ocr_threshold,
        )
        
        self._router     = PDFRouter(self._cfg)
        self._extractor  = TextExtractor()
        self._llama      = LlamaClient(self.config)
        self._ocr_engine = CorporateOCREngine(extractor=ocr_extractor)

        logger.debug(
            "[PipelineManager] Initialised — model=%s  ocr=%s  threshold=%d",
            self._cfg.model,
            type(self._ocr_engine._extractor).__name__,
            self._cfg.ocr_threshold,
        )

    # ==================================================================
    # Public API
    # ==================================================================

    def process(self, file_path: str) -> ParseResult:
        """
        Process a single PDF through the unified pipeline.

        Steps
        ~~~~~
        1. Validate the file exists.
        2. Hash raw bytes + measure file size.
        3. Route: classify the PDF as TEXT or IMAGE.
        4. Extract raw text via the appropriate engine.
        5. Call LlamaClient to extract structured metadata.
        6. Assemble and return a store-compatible ``ParseResult``.

        Parameters
        ----------
        file_path : str
            Absolute or relative path to the PDF file.

        Returns
        -------
        ParseResult
            - ``success=True`` → ``.data`` dict is ready for
              ``MetadataStore.insert_document()``.
            - ``success=False`` → ``.data`` is ``None``; ``.message`` explains
              the failure.
        """
        # ── 1. Resolve & validate path ───────────────────────────────────────
        resolved = self._resolve(file_path)
        if resolved is None:
            return ParseResult(
                success=False,
                message=f"File not found: '{file_path}'",
            )

        logger.info("[PipelineManager] Processing: %s", resolved)

        # ── 2. Hash + size ───────────────────────────────────────────────────
        try:
            raw_bytes = Path(resolved).read_bytes()
        except OSError as exc:
            logger.error("[PipelineManager] Cannot read file: %s", exc)
            return ParseResult(
                success=False,
                message=f"Cannot read file '{resolved}': {exc}",
            )

        sha256_hash     = hashlib.sha256(raw_bytes).hexdigest()
        file_size_bytes = len(raw_bytes)

        # ── 3. Route ─────────────────────────────────────────────────────────
        pdf_type = self._router.detect(resolved)

        if pdf_type is PdfType.UNKNOWN:
            return ParseResult(
                success=False,
                message=(
                    f"Could not classify PDF type for '{resolved}'. "
                    "The file may be corrupt or unreadable."
                ),
                pdf_type=pdf_type,
            )

        # ── 4. Extract raw text ──────────────────────────────────────────────
        raw_text, parse_method = self._extract(resolved, pdf_type)

        if raw_text is None:
            # _extract already logged the error; return the failure result
            return ParseResult(
                success=False,
                message=(
                    f"Text extraction failed for '{resolved}' "
                    f"(method={parse_method}). Check logs for details."
                ),
                parse_method=parse_method,
                pdf_type=pdf_type,
            )

        if len(raw_text.strip()) < 20:
            return ParseResult(
                success=False,
                message=(
                    f"Extracted text is too short ({len(raw_text)} chars). "
                    "The PDF may be empty or heavily image-based."
                ),
                parse_method=parse_method,
                raw_text=raw_text,
                pdf_type=pdf_type,
            )

        logger.info(
            "[PipelineManager] %d characters extracted via '%s'.",
            len(raw_text), parse_method,
        )

        # ── 5. Llama API — structured metadata extraction ────────────────────
        try:
            metadata = self._llama.extract_metadata(raw_text)
        except ValueError as exc:
            # Config error or unparseable JSON — do not retry
            logger.error(
                "[PipelineManager] Llama metadata extraction failed: %s", exc
            )
            return ParseResult(
                success=False,
                message=f"Metadata extraction failed: {exc}",
                parse_method=parse_method,
                raw_text=raw_text,
                pdf_type=pdf_type,
            )
        except Exception as exc:          # noqa: BLE001  (network, openai.APIError…)
            logger.error(
                "[PipelineManager] Llama API error: %s", exc, exc_info=True
            )
            return ParseResult(
                success=False,
                message=f"Llama API call failed: {exc}",
                parse_method=parse_method,
                raw_text=raw_text,
                pdf_type=pdf_type,
            )

        # ── 6. Assemble store-compatible payload ─────────────────────────────
        metadata["is_legal_structure"] = detect_legal_structure(raw_text)
        
        doc_id        = self._derive_doc_id(resolved, metadata)
        store_payload = self._build_payload(
            doc_id, sha256_hash, file_size_bytes, resolved, metadata
        )

        logger.info(
            "[PipelineManager] ✓ id='%s'  title='%s'  method='%s'",
            doc_id,
            store_payload.get("title", "—"),
            parse_method,
        )

        # ── 7. Save outputs ──────────────────────────────────────────────────
        try:
            metadata_dir = Path("data/metadata")
            text_dir = Path("data/text")
            
            metadata_dir.mkdir(parents=True, exist_ok=True)
            text_dir.mkdir(parents=True, exist_ok=True)
            
            metadata_path = metadata_dir / f"{doc_id}.json"
            text_path = text_dir / f"{doc_id}.txt"
            
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(store_payload, f, indent=4, ensure_ascii=False)
                
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(raw_text)
                
            logger.info(
                "[PipelineManager] Saved metadata -> %s, text -> %s",
                metadata_path, text_path
            )
        except Exception as e:
            logger.error("[PipelineManager] Failed to save outputs: %s", e)

        return ParseResult(
            success=True,
            message=(
                f"Document processed successfully via '{parse_method}' path. "
                f"Extracted {len(raw_text):,} characters. "
                f"Derived id='{doc_id}'."
            ),
            parse_method=parse_method,
            data=store_payload,
            raw_text=raw_text,
            pdf_type=pdf_type,
        )

    def process_batch(self, file_paths: List[str]) -> List[ParseResult]:
        """
        Process multiple PDFs sequentially and return one result per file.

        Each document is processed independently — a failure on one file
        does not abort the rest of the batch.

        Parameters
        ----------
        file_paths : list[str]
            List of PDF paths to process.

        Returns
        -------
        list[ParseResult]
            Results in the same order as ``file_paths``.
        """
        if not file_paths:
            logger.warning("[PipelineManager] process_batch called with empty list.")
            return []

        logger.info(
            "[PipelineManager] Starting batch — %d document(s).", len(file_paths)
        )

        results: List[ParseResult] = []
        for i, fp in enumerate(file_paths, start=1):
            logger.info(
                "[PipelineManager] Batch [%d/%d]: %s", i, len(file_paths), fp
            )
            results.append(self.process(fp))

        succeeded = sum(1 for r in results if r.success)
        logger.info(
            "[PipelineManager] Batch complete — %d/%d succeeded.",
            succeeded, len(file_paths),
        )
        return results

    # ==================================================================
    # Private helpers
    # ==================================================================

    def _extract(
        self, resolved: str, pdf_type: PdfType
    ) -> tuple[Optional[str], str]:
        """
        Dispatch to the correct extractor based on *pdf_type*.

        Returns
        -------
        tuple[str | None, str]
            (raw_text, parse_method) — raw_text is None on failure.
        """
        if pdf_type is PdfType.TEXT:
            return self._run_text_extractor(resolved), "text"
        else:  # PdfType.IMAGE
            return self._run_ocr_engine(resolved), "ocr"

    def _run_text_extractor(self, resolved: str) -> Optional[str]:
        """Run pdfplumber extraction; return None on any error."""
        try:
            return self._extractor.extract(resolved)
        except (FileNotFoundError, RuntimeError) as exc:
            logger.error(
                "[PipelineManager] TextExtractor failed: %s", exc
            )
            return None

    def _run_ocr_engine(self, resolved: str) -> Optional[str]:
        """Run CorporateOCREngine; return None on any error."""
        try:
            return self._ocr_engine.process_document(resolved)
        except (FileNotFoundError, RuntimeError) as exc:
            logger.error(
                "[PipelineManager] CorporateOCREngine failed: %s", exc
            )
            return None
        except Exception as exc:          # noqa: BLE001
            logger.error(
                "[PipelineManager] CorporateOCREngine unexpected error: %s",
                exc, exc_info=True,
            )
            return None

    def _resolve(self, file_path: str) -> Optional[str]:
        """Return absolute path string, or None if the file does not exist."""
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            logger.warning("[PipelineManager] File not found: %s", path)
            return None
        return str(path)

    def _build_payload(
        self,
        doc_id: str,
        sha256_hash: str,
        file_size_bytes: int,
        resolved: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Assemble the store-compatible dict from hashed file fields and
        LLM-extracted metadata.

        The returned dict matches the ``MetadataStore.insert_document()``
        contract exactly — the caller can pass ``.data`` directly to the store.
        """
        return {
            # Identity
            "id":               doc_id,
            "file_url":         "",           # Caller sets from their context
            "sha256_hash":      sha256_hash,
            # LLM-extracted metadata (keys match StoredDocument fields)
            "title":            metadata.get("title"),
            "document_type":    metadata.get("document_type"),
            "issuing_entity":   metadata.get("issuing_entity"),
            "document_number":  metadata.get("document_number"),
            "year":             metadata.get("year"),
            "date":             metadata.get("date"),
            "language":         metadata.get("language"),
            "category":         metadata.get("category"),
            "subcategory":      metadata.get("subcategory"),
            "is_legal_structure": metadata.get("is_legal_structure"),
            # File-level fields
            "file_path":        resolved,
            "file_size_bytes":  file_size_bytes,
            "download_status":  "downloaded",
        }

    def _derive_doc_id(
        self, resolved_path: str, metadata: dict[str, Any]
    ) -> str:
        """
        Derive a URL-safe, human-readable document ID.

        Format: ``<year>_<title-slug>_<6-char-path-hash>``
        e.g.    ``2024_aml_policy_a3f9c1``
        """
        title: str = metadata.get("title") or Path(resolved_path).stem
        year: str  = metadata.get("year") or ""

        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
        if len(slug) > 40:
            slug = slug[:40].rstrip("_")

        path_hash = hashlib.sha256(resolved_path.encode()).hexdigest()[:6]
        parts = [p for p in [year, slug, path_hash] if p]
        return "_".join(parts)
