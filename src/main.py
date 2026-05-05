"""
main.py — ComplianceAgent entry point (example)

Demonstrates how to use ScrapperClient to call the Scraper Extractor
microservice. Make sure the Docker container is running first:

    docker compose up -d          (from the ComplianceAgent root)

Then run this file:

    python -m src.main            (from the ComplianceAgent root)
"""

import json
import logging
from src.Scrapper.ScrapperClient import ScrapperClient, ScrapperClientError

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s — %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Example helper
# ---------------------------------------------------------------------------

def run_example(client: ScrapperClient, url: str, is_crawl: bool = False, limit: int = 1) -> None:
    """Run one extraction and pretty-print the result."""
    mode = f"crawl (limit={limit})" if is_crawl else "single-page scrape"
    logger.info("▶  Starting %s for: %s", mode, url)

    try:
        data = client.extract_data(url=url, is_crawl=is_crawl, limit=limit)

        if data:
            logger.info("✅  Extraction successful — %d record(s) returned.", len(data))
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            logger.warning("⚠️  Extraction returned no data for: %s", url)

    except ScrapperClientError as e:
        logger.error("❌  ScrapperClientError: %s", e)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    client = ScrapperClient()   # reads base_url / timeout from config/config.yaml

    # ── Example 1: single-page scrape ────────────────────────────────────────
    run_example(
        client,
        url="https://www.cbe.org.eg/en/laws-regulations/laws/banking-laws",
        is_crawl=False,
        limit=1,
    )

    # ── Example 2: crawl up to 5 pages ───────────────────────────────────────
    # run_example(
    #     client,
    #     url="https://www.example.com",
    #     is_crawl=True,
    #     limit=5,
    #
