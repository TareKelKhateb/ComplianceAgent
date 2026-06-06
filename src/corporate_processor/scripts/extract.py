"""
Stage 1 — Extract raw text and metadata from all PDFs in data/corporate/raw/.
Outputs saved automatically to data/metadata/ and data/text/ by PipelineManager.
Run: uv run python src/corporate_processor/scripts/extract.py
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.corporate_processor.config import CorporateConfig
from src.corporate_processor.pipeline_manager import PipelineManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger(__name__)

RAW_DIR = Path("data/corporate/raw")


def main():
    try:
        config = CorporateConfig.load()
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)

    pdf_files = sorted(RAW_DIR.glob("*.pdf"))
    if not pdf_files:
        logger.warning("No PDF files found in %s", RAW_DIR)
        sys.exit(0)

    logger.info("Found %d PDF(s) to extract.", len(pdf_files))
    manager = PipelineManager(config=config)
    succeeded, failed = 0, 0

    for pdf_path in pdf_files:
        logger.info("Processing: %s", pdf_path.name)
        result = manager.process(str(pdf_path))
        if result.success:
            logger.info("  ✓ id='%s'", result.data.get("id"))
            succeeded += 1
        else:
            logger.error("  ✗ %s", result.message)
            failed += 1

    logger.info("Done: %d succeeded, %d failed.", succeeded, failed)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
