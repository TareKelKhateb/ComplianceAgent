"""
test.py — Data Ingestion Pipeline Entry-Point
----------------------------------------------
Thin entry-point: loads a scraped JSON file and delegates the entire
ingestion pipeline to ``ParsingMetaDataExtractor.process_pipeline()``.

Usage (from the project root):
    uv run python -m src.Parsing_and_metadata_extractor.test
"""

import json
import logging
import sys

# pyrefly: ignore [missing-import]
from src.Parsing_and_metadata_extractor.parsing_and_metadata_extractor import (
    ParsingMetaDataExtractor,
)

# ---------------------------------------------------------------------------
# Logging — configured once at the entry-point.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

JSON_INPUT_FILE = "output_1.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_banner(text: str, char: str = "═", width: int = 64) -> None:
    print(f"\n{char * width}\n  {text}\n{char * width}")


def _print_stats(stats: dict, total: int) -> None:
    _print_banner("PIPELINE RUN SUMMARY")
    print(f"  {'Total processed':<25} {total}")
    print(f"  {'✅  New inserts':<25} {stats.get('new', 0)}")
    print(f"  {'⬆️   Updated versions':<25} {stats.get('updated', 0)}")
    print(f"  {'🔄  Skipped (unchanged)':<25} {stats.get('skipped', 0)}")
    print(f"  {'❌  Failed':<25} {stats.get('failed', 0)}")
    print("═" * 64 + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _print_banner("🚀  Compliance Agent — Metadata Ingestion Pipeline")

    # 1. Load JSON -----------------------------------------------------------
    try:
        with open(JSON_INPUT_FILE, "r", encoding="utf-8") as fh:
            scraped_data = json.load(fh)
        logger.info("📂  Loaded '%s' successfully.", JSON_INPUT_FILE)
    except FileNotFoundError:
        logger.critical("❌  Input file not found: '%s'. Aborting.", JSON_INPUT_FILE)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        logger.critical("❌  Failed to parse JSON: %s", exc)
        sys.exit(1)

    # Count total documents for the summary (works for flat & nested layouts).
    if scraped_data and isinstance(scraped_data[0], list):
        total_docs = sum(len(g) for g in scraped_data)
    else:
        total_docs = len(scraped_data)

    # 2. Initialise the extractor and show current DB state -----------------
    parser = ParsingMetaDataExtractor()
    
    _print_banner("📊  Current Database State (before pipeline run)")
    parser.print_database_stats()
    parser.print_all_documents()

    # 3. Run the pipeline ----------------------------------------------------
    _print_banner("⚙️   Running Ingestion Pipeline")
    stats = parser.process_pipeline(scraped_data=scraped_data)

    # 4. Print summary -------------------------------------------------------
    _print_stats(stats, total=total_docs)

    # ---------------------------------------------------------------------------
    # 5. TEST: DagsHub Push (Using the official function 🚀)
    # ---------------------------------------------------------------------------
    _print_banner("🧪 TESTING: DagsHub Push Experiment")
    
    test_pdf_path = r"D:\ITI\dummy.pdf"
    test_url = "https://example.com/dummy-test-file"
    fake_hash = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z0123456789abc"

    logger.info("Starting push test for: %s", test_pdf_path)
    
    sync_success = parser.push_to_dagshub(
        local_pdf_path=test_pdf_path, 
        file_url=test_url,
        content_hash=fake_hash
    )

    if sync_success:
        _print_banner("✅ PUSH TEST PASSED!")
        print(f"File should now be in the vault with a name like: dummy__{fake_hash[:8]}.pdf")
    else:
        _print_banner("❌ PUSH TEST FAILED")
        print("Check the logs above to see if it's a DVC or Git error.")