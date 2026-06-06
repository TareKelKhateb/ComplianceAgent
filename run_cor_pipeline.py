import logging
from pathlib import Path

from src.corporate_processor.config import CorporateConfig
from src.corporate_processor.corporate_pipeline import CorporateEndToEndPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    # 1. Load & validate configuration (fail-fast)
    try:
        config = CorporateConfig.load()
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        return

    # 2. Define the document to process
    pdf_path = "data/corporate/raw/2016.pdf"

    # 3. Run the end-to-end pipeline
    logger.info("Starting end-to-end corporate pipeline for: %s", pdf_path)
    pipeline = CorporateEndToEndPipeline(config=config)
    result   = pipeline.run(pdf_path=pdf_path)

    # 4. Report the outcome
    if result.success:
        logger.info("Pipeline succeeded: %s", result.message)
        if result.data:
            logger.info(
                "Chunks → inserted=%d  skipped=%d  failed=%d",
                result.data.inserted_count,
                result.data.skipped_count,
                result.data.failed_count,
            )
    else:
        logger.error("Pipeline failed: %s", result.message)


if __name__ == "__main__":
    main()