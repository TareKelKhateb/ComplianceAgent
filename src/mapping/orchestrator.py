"""
orchestrator.py
---------------
Exposes a class-based ComplianceMapper that encapsulates the full compliance
mapping pipeline.  Teams can instantiate the class and call .run() with a
list of raw text strings, or use it as a context manager for guaranteed
session cleanup.

Usage
-----
    # Direct usage
    mapper = ComplianceMapper()
    mapper.run(my_texts)

    # Context-manager usage (sessions are closed automatically)
    with ComplianceMapper() as mapper:
        mapper.run(my_texts)
"""

import hashlib
import json
import logging
import uuid
from typing import List, Optional

from src.mapping.data_manager.database import (
    MappingBridgeTable,
    SessionCorp,
    SessionMapping,
    init_db,
)
from src.mapping.data_manager.schema import MappingBridgeSchema, RelationshipType
from src.mapping.data_manager import crud_mapping, crud_corporate
from src.mapping.llm_engine.client import analyze_with_llm
from src.mapping.vector_search import get_law_chunks_by_similarity

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ComplianceMapper:
    """
    Orchestrates the compliance mapping pipeline using dual database sessions.

    The class lazily opens a SessionCorp (read-only corporate DB) and a
    SessionMapping (read-write mapping DB) on the first call to run(), and
    keeps them open for the lifetime of the instance so that multiple run()
    calls within one workflow reuse the same connections.

    Call .close() explicitly, or use the instance as a context manager, to
    release the sessions when done.
    """

    def __init__(self) -> None:
        # Sessions are created eagerly so that callers get an immediate error
        # if the database configuration is broken, rather than a silent failure
        # buried inside run().
        init_db()
        self._db_corp: SessionCorp = SessionCorp()       # read-only corporate DB
        self._db_mapping: SessionMapping = SessionMapping()  # read-write mapping DB
        logger.info("ComplianceMapper: database sessions opened.")

    # ------------------------------------------------------------------
    # Context-manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "ComplianceMapper":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close both database sessions and release all held connections."""
        self._db_corp.close()
        self._db_mapping.close()
        logger.info("ComplianceMapper: database sessions closed.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_hash(content: str) -> str:
        """
        Returns the SHA-256 hex digest of *content*.

        This is the single source of truth for chunk-hash generation inside
        the mapper, ensuring that every hash comparison is made on identical
        digests regardless of where the content originates.

        Args:
            content: The raw text string to hash.

        Returns:
            A 64-character lowercase hex string.
        """
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _is_chunk_processed(self, corp_hash: str) -> bool:
        """
        Returns True if *any* mapping record already exists in
        mapping_bridge for the given corporate_chunk_hash.

        Fails safe: logs a warning and returns False if the DB query errors,
        so the chunk will be re-processed rather than silently dropped.

        Args:
            corp_hash: SHA-256 hash of the corporate policy chunk to check.
        """
        try:
            record = (
                self._db_mapping.query(MappingBridgeTable)
                .filter(MappingBridgeTable.corporate_chunk_hash == corp_hash)
                .first()
            )
            return record is not None
        except Exception as exc:
            logger.warning(
                "ComplianceMapper._is_chunk_processed query failed for hash %s: %s",
                corp_hash,
                exc,
            )
            return False

    def _process_chunk(self, corp_hash: str, corp_text: str) -> None:
        """
        Execute the full mapping logic for a single corporate chunk.

        Steps
        -----
        1. Vector-similarity search against the law corpus.
        2. If no candidates found → persist a GAP record (idempotent).
        3. For each candidate law chunk → call LLM and persist the result
           (the existing per-pair duplicate check is preserved).

        Args:
            corp_hash: Pre-calculated SHA-256 hash of the chunk.
            corp_text: Raw text content of the chunk.
        """
        relevant_law_chunks = get_law_chunks_by_similarity(corp_text, threshold=0.88)

        # ── GAP scenario ──────────────────────────────────────────────
        if not relevant_law_chunks:
            if not crud_mapping.get_mapping_by_hashes(
                db=self._db_mapping,
                corp_hash=corp_hash,
                law_hash="NO_MATCH_FOUND",
            ):
                gap_data = MappingBridgeSchema(
                    id=str(uuid.uuid4()),
                    corporate_chunk_hash=corp_hash,
                    country_law_hash="NO_MATCH_FOUND",
                    relation_type=RelationshipType.GAP,
                    reasoning="No relevant law chunk found.",
                    confidence_score=1.0,
                )
                crud_mapping.create_mapping(db=self._db_mapping, mapping_data=gap_data)
                logger.info("ComplianceMapper: GAP record created for hash %s.", corp_hash)
            return

        # ── Match scenario ────────────────────────────────────────────
        for law_chunk in relevant_law_chunks:
            law_hash = law_chunk.get("chunk_hash")
            law_text = law_chunk.get("content")

            # Fine-grained per-pair duplicate check (preserved from original)
            if crud_mapping.get_mapping_by_hashes(
                db=self._db_mapping,
                corp_hash=corp_hash,
                law_hash=law_hash,
            ):
                continue

            context = f"Corporate Chunk: {corp_text}\n\nCountry Law Chunk: {law_text}"
            try:
                rel_type, reasoning, confidence = analyze_with_llm(context)
                mapping_data = MappingBridgeSchema(
                    id=str(uuid.uuid4()),
                    corporate_chunk_hash=corp_hash,
                    country_law_hash=law_hash,
                    relation_type=rel_type,
                    reasoning=reasoning,
                    confidence_score=confidence,
                )
                crud_mapping.create_mapping(
                    db=self._db_mapping, mapping_data=mapping_data
                )
            except Exception as exc:
                logger.error(
                    "ComplianceMapper: LLM analysis failed for corp_hash=%s, "
                    "law_hash=%s: %s",
                    corp_hash,
                    law_hash,
                    exc,
                )

    def _write_metrics(self) -> None:
        """Persist pipeline summary metrics to data/mapping_metrics.json."""
        all_mappings = self._db_mapping.query(MappingBridgeTable).all()
        total = len(all_mappings)
        gaps = sum(
            1 for m in all_mappings if m.relation_type == RelationshipType.GAP
        )
        with open("data/mapping_metrics.json", "w", encoding="utf-8") as fh:
            json.dump({"total_mappings": total, "total_gaps": gaps}, fh, indent=4)
        logger.info(
            "ComplianceMapper: metrics written — total=%d, gaps=%d.", total, gaps
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, texts: List[str]) -> None:
        """
        Process a list of raw text strings through the compliance mapping
        pipeline.

        For each text:
          • compute its SHA-256 hash via _calculate_hash
          • skip if the hash is already present in mapping_bridge
          • otherwise run vector search + LLM analysis and persist results

        After all texts are processed the method updates
        data/mapping_metrics.json with the current totals.

        Args:
            texts: List of raw corporate policy text strings to process.
        """
        logger.info(
            "ComplianceMapper.run: starting — %d text(s) to evaluate.", len(texts)
        )

        for corp_text in texts:
            if not isinstance(corp_text, str) or not corp_text.strip():
                logger.warning(
                    "ComplianceMapper.run: skipping empty or non-string entry."
                )
                continue

            corp_hash = self._calculate_hash(corp_text)

            # Idempotency guard
            if self._is_chunk_processed(corp_hash):
                logger.info("Skipping already processed chunk: %s", corp_hash)
                continue

            logger.info(
                "ComplianceMapper.run: processing chunk hash=%s …", corp_hash
            )
            self._process_chunk(corp_hash, corp_text)

        self._write_metrics()
        logger.info("ComplianceMapper.run: pipeline complete.")


# ---------------------------------------------------------------------------
# Convenience wrapper — keeps the original functional entry-point working
# so that existing DVC stages / scripts are not broken.
# ---------------------------------------------------------------------------

def run_mapping_pipeline(chunks_list: Optional[List[str]] = None) -> None:
    """
    Backward-compatible functional entry-point.

    If *chunks_list* is provided the texts are passed directly to
    ComplianceMapper.run(); otherwise all corporate chunks are fetched from
    the corporate database first.
    """
    with ComplianceMapper() as mapper:
        if chunks_list is not None:
            texts = chunks_list
            logger.info(
                "run_mapping_pipeline: batch mode — %d text(s) supplied.", len(texts)
            )
        else:
            db_corp = SessionCorp()
            try:
                raw_chunks = crud_corporate.get_all_chunks(db=db_corp)
            finally:
                db_corp.close()

            texts = [c["content"] for c in raw_chunks if c.get("content")]
            logger.info(
                "run_mapping_pipeline: full-scan mode — %d chunk(s) fetched from DB.",
                len(texts),
            )

        mapper.run(texts)


if __name__ == "__main__":
    run_mapping_pipeline()