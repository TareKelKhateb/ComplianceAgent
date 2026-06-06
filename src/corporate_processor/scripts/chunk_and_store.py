"""
Stage 2 — Read pre-extracted text/metadata from Stage 1, refine via LLM,
and persist to data/corporate_chunks.db.
Run: uv run python src/corporate_processor/scripts/chunk_and_store.py
"""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# pyrefly: ignore [missing-import]
from src.corporate_processor.config import CorporateConfig
# pyrefly: ignore [missing-import]
from src.corporate_processor.chunkers.corporate_chunker import CorporateChunker
# pyrefly: ignore [missing-import]
from src.corporate_processor.corporate_metadata_manager.corporate_store import CorporateChunkStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger(__name__)

METADATA_DIR = Path("data/metadata")
TEXT_DIR     = Path("data/text")


def main():
    try:
        CorporateConfig.load()
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)

    metadata_files = sorted(METADATA_DIR.glob("*.json"))
    if not metadata_files:
        logger.warning("No metadata files in %s — run Stage 1 first.", METADATA_DIR)
        sys.exit(1)

    logger.info("Found %d document(s) to chunk and store.", len(metadata_files))
    chunker = CorporateChunker()
    store   = CorporateChunkStore()
    total_inserted, total_skipped = 0, 0

    for meta_path in metadata_files:
        doc_id    = meta_path.stem
        text_path = TEXT_DIR / f"{doc_id}.txt"
        if not text_path.exists():
            logger.warning("Missing text file for '%s' — skipping.", doc_id)
            continue

        with open(meta_path, encoding="utf-8") as f:
            metadata = json.load(f)
        with open(text_path, encoding="utf-8") as f:
            raw_text = f.read()

        logger.info("Chunking '%s' (%d chars).", doc_id, len(raw_text))
        sections = chunker.split_text_by_headers(raw_text) or [raw_text]

        for index, section in enumerate(sections):
            content = section.strip()
            if not content:
                continue
            try:
                final = chunker.refine_chunk(content) or content
            except Exception as exc:
                logger.warning("Refinement failed chunk %d of '%s': %s — using raw.", index, doc_id, exc)
                final = content

            res = store.insert_chunks_batch(
                doc_id=doc_id,
                chunks=[{"chunk_index": index, "content": final}],
                metadata=metadata,
            )
            if res.success and res.data:
                total_inserted += res.data.inserted_count
                total_skipped  += res.data.skipped_count

    logger.info("Done: %d inserted, %d skipped (duplicates).", total_inserted, total_skipped)


if __name__ == "__main__":
    main()
