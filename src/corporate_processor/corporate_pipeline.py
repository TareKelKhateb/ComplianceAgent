"""
corporate_pipeline.py
---------------------
End-to-end corporate compliance document processing pipeline.

Linear Flow:
    PDF Path
        │
        ▼
    PipelineManager.process()        ← OCR / Text extraction + Metadata + File save
        │
        ├─► raw_text  (str)
        └─► metadata  (dict)
              │
              ▼
    CorporateChunker                 ← split_text_by_headers + refine_chunk (LLM)
              │
              ▼
    CorporateChunkStore.insert_chunks_batch()   ← SQLite persistence
              │
              ▼
    ChunkStorageResult               ← returned to the caller

Usage:
    from src.corporate_processor.corporate_pipeline import CorporateEndToEndPipeline

    pipeline = CorporateEndToEndPipeline()
    result = pipeline.run(pdf_path="data/corporate/raw/2016.pdf", doc_id="2016_580ab4")
    print(result.success, result.message)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from src.corporate_processor.config import CorporateConfig
from src.corporate_processor.pipeline_manager import PipelineManager
from src.corporate_processor.chunkers.corporate_chunker import CorporateChunker
from src.corporate_processor.corporate_metadata_manager.corporate_store import CorporateChunkStore
from src.corporate_processor.corporate_metadata_manager.models import ChunkStorageResult

logger = logging.getLogger(__name__)


class CorporateEndToEndPipeline:
    """
    Orchestrates the complete corporate document lifecycle:
    OCR extraction → chunking → LLM refinement → database persistence.

    Parameters
    ----------
    config : CorporateConfig, optional
        Loaded CorporateConfig instance. Auto-loaded from .env if not supplied.
    db_path : str, optional
        Path to the SQLite database for corporate_chunks.
        Defaults to data/corporate_chunks.db.
    """

    def __init__(
        self,
        config: Optional[CorporateConfig] = None,
        db_path: Optional[str] = None,
    ) -> None:
        self.config   = config or CorporateConfig.load()
        self.manager  = PipelineManager(config=self.config)
        self.chunker  = CorporateChunker()
        self.store    = CorporateChunkStore(db_path=db_path)

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def _log_gpu_status(self):
        """Checks and logs if PyTorch detects a GPU for hardware acceleration."""
        try:
            import torch
            if torch.cuda.is_available():
                device_name = torch.cuda.get_device_name(0)
                logger.info("[Hardware Check] GPU Detected: %s. Hardware acceleration enabled.", device_name)
            else:
                logger.info("[Hardware Check] No GPU detected by PyTorch. Running on CPU.")
        except ImportError:
            logger.info("[Hardware Check] PyTorch not installed. Hardware acceleration status unknown.")
        except Exception as e:
            logger.debug("[Hardware Check] Could not determine GPU status: %s", e)

    def run(self, pdf_path: str, doc_id: Optional[str] = None) -> ChunkStorageResult:
        """
        Execute the full pipeline for a single PDF document.

        Parameters
        ----------
        pdf_path : str
            Path to the PDF file.
        doc_id   : str, optional
            Override the derived document ID. If not supplied, the ID generated
            by PipelineManager is used.

        Returns
        -------
        ChunkStorageResult
            .success  — True if chunks were stored.
            .message  — Human-readable pipeline status.
            .data     — ChunkBatchResult with inserted/skipped/failed counts.
        """
        logger.info("[Pipeline] ──────────────────────────────────────────")
        self._log_gpu_status()
        logger.info("[Pipeline] Starting: %s", pdf_path)

        # ── Stage 1: OCR / Extraction + Metadata ────────────────────────────
        parse_result = self._stage_extraction(pdf_path)
        if not parse_result.success:
            return ChunkStorageResult(
                success=False,
                message=f"[Stage 1 FAILED] Extraction: {parse_result.message}",
            )

        # Use the caller-supplied doc_id or the one derived by PipelineManager
        effective_doc_id = doc_id or parse_result.data.get("id", Path(pdf_path).stem)
        metadata         = parse_result.data       # Full store-compatible dict
        raw_text         = parse_result.raw_text   # Raw extracted text

        logger.info("[Pipeline] Stage 1 ✓  doc_id='%s'  chars=%d", effective_doc_id, len(raw_text))

        # ── Stage 2 & 3: Chunking + LLM Refinement + Incremental Storage ────────
        storage_result = self._stage_chunking_and_refinement(
            raw_text=raw_text, 
            doc_id=effective_doc_id, 
            metadata=metadata, 
            store=self.store
        )
        
        if not storage_result.success and storage_result.data.total_count == 0:
            return ChunkStorageResult(
                success=False,
                message=f"[Stage 2 FAILED] Chunking produced no output for '{effective_doc_id}'.",
            )

        logger.info("[Pipeline] Stage 2 & 3 ✓  %s", storage_result.message)
        logger.info("[Pipeline] ──────────────────────────────────────────")

        return storage_result

    # -----------------------------------------------------------------------
    # Private stage methods
    # -----------------------------------------------------------------------

    def _stage_extraction(self, pdf_path: str):
        """
        Stage 1: OCR / text extraction + metadata + intermediate file save.
        Delegates entirely to PipelineManager — no reimplementation.
        """
        logger.info("[Pipeline] Stage 1: Extraction & OCR → %s", pdf_path)
        return self.manager.process(pdf_path)

    def _stage_chunking_and_refinement(
        self, raw_text: str, doc_id: str, metadata: dict, store: CorporateChunkStore
    ) -> ChunkStorageResult:
        """
        Stage 2 & 3: Split the raw text by headers and refine each chunk via LLM.
        Incrementally stores each chunk into the database as soon as it's refined.
        Falls back to the raw chunk content if LLM refinement fails for any chunk.
        """
        from src.corporate_processor.corporate_metadata_manager.models import ChunkBatchResult

        logger.info("[Pipeline] Stage 2 & 3: Chunking, Refinement, and Incremental Storage for '%s'", doc_id)

        # 2a. Split by Markdown headers (##, ###, ####)
        raw_sections = self.chunker.split_text_by_headers(raw_text)
        if not raw_sections:
            logger.warning("[Pipeline] No sections found after split for '%s'. Using full text as one chunk.", doc_id)
            raw_sections = [raw_text]

        # 2b. Refine each section and store immediately
        total = len(raw_sections)
        inserted = 0
        skipped = 0
        failed = 0
        errors = []

        for index, section in enumerate(raw_sections):
            content = section.strip()
            if not content:
                total -= 1
                continue

            try:
                refined_content = self.chunker.refine_chunk(content)
                final_content = refined_content if refined_content else content
            except Exception as exc:
                logger.warning(
                    "[Pipeline] LLM refinement failed for chunk %d of '%s' — falling back to raw text. Error: %s",
                    index, doc_id, exc
                )
                final_content = content  # Guaranteed fallback: no data loss

            # 3. Incremental Storage
            chunk_payload = [{
                "chunk_index": index,
                "content":     final_content,
            }]
            
            # Use the passed store instance
            res = store.insert_chunks_batch(doc_id=doc_id, chunks=chunk_payload, metadata=metadata)
            
            if res.success and res.data:
                inserted += res.data.inserted_count
                skipped += res.data.skipped_count
                failed += res.data.failed_count
                if res.data.errors:
                    errors.extend(res.data.errors)
            else:
                failed += 1
                errors.append(res.message)

        batch_result = ChunkBatchResult(
            total_count=total,
            inserted_count=inserted,
            skipped_count=skipped,
            failed_count=failed,
            errors=errors
        )
        
        success = failed == 0 and total > 0
        
        return ChunkStorageResult(
            success=success,
            message=(
                f"Incremental batch complete for '{doc_id}': "
                f"{inserted} inserted, {skipped} skipped (duplicates), {failed} failed."
            ),
            data=batch_result,
        )
