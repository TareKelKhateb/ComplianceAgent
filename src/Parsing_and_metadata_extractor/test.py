"""
test.py — Data Ingestion Pipeline Entry-Point
----------------------------------------------
Thin entry-point: loads a scraped JSON file and delegates the entire
ingestion pipeline to ``ParsingMetaDataExtractor.process_pipeline_general()``.

The pipeline will:
  1. Check for local files first or download each PDF.
  2. Insert / update the metadata DB record.
  3. Push the file to DagsHub via DVC under a content-addressed filename
     (``<stem>__<hash8>.pdf``) so vault conflicts are impossible even when
     document content changes between runs.

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
    print(f"  {'Total processed':<28} {total}")
    print(f"  {'[NEW] New inserts':<28} {stats.get('new', 0)}")
    print(f"  {'[UPD] Updated versions':<28} {stats.get('updated', 0)}")
    print(f"  {'[SKP] Skipped (unchanged)':<28} {stats.get('skipped', 0)}")
    print(f"  {'[ERR] Failed':<28} {stats.get('failed', 0)}")
    if stats.get("pushed", 0) or stats.get("push_failed", 0):
        print()
        print(f"  {'[HUB] Pushed to DagsHub':<28} {stats.get('pushed', 0)}")
        print(f"  {'[WRN] DagsHub push failed':<28} {stats.get('push_failed', 0)}")
    print("═" * 64 + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _print_banner("Compliance Agent - Metadata Ingestion Pipeline")

    # 1. Load JSON -----------------------------------------------------------
    try:
        with open(JSON_INPUT_FILE, "r", encoding="utf-8") as fh:
            scraped_data = json.load(fh)
        logger.info("Loaded '%s' successfully.", JSON_INPUT_FILE)
    except FileNotFoundError:
        logger.critical("Input file not found: '%s'. Aborting.", JSON_INPUT_FILE)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        logger.critical("Failed to parse JSON: %s", exc)
        sys.exit(1)

    # Count total documents for the summary (works for flat & nested layouts).
    if scraped_data and isinstance(scraped_data[0], list):
        total_docs = sum(len(g) for g in scraped_data)
    else:
        total_docs = len(scraped_data)

    # 2. Initialise the extractor and show current DB state -----------------
    parser = ParsingMetaDataExtractor()


    _print_banner("Current Database State (before pipeline run)")
    parser.print_database_stats()
    parser.print_all_documents()

    # 3. Run the pipeline (with DagsHub push enabled) -----------------------
    _print_banner("Running Ingestion Pipeline")
    stats = parser.process_pipeline_general(
        scraped_data=scraped_data,
        push_to_dagshub=True,   # set False to skip DVC push (dry-run)
    )

    # 4. Print summary -------------------------------------------------------
    _print_stats(stats, total=total_docs)