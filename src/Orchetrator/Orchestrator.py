"""
Pipeline Orchestrator
=====================
Coordinates the four pipeline stages in sequence:

  1. Scraper          — fetches raw document listings from a source URL
  2. User Adjustments — human-in-the-loop metadata review & correction (UI layer)
  3. Parsing & Metadata Extractor — downloads PDFs, computes hashes, detects diffs
  4. Document Processor (OCR / Chunking / Diff) — full-text extraction on changed docs

Simulation mode
---------------
While the Scraper and UI layers are not yet wired up, two helper functions
simulate their outputs by loading from local JSON files:

  * simulate_scraper_output()      → replaces the live scraper
  * simulate_user_adjustments()    → replaces the live UI approval step

Replace each function body with the real integration when ready.
"""

import os
import sys
import json
import logging
import logging.handlers

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so sibling packages resolve correctly
# ---------------------------------------------------------------------------
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.metadata_manager.metadata_store import MetadataStore
from src.Parsing_and_metadata_extractor.parsing_and_metadata_extractor import ParsingMetaDataExtractor
from src.document_processor.pipeline_manager import OCRPipeline

# ---------------------------------------------------------------------------
# Logging — coloured console output (stdlib only, no extra packages)
# ---------------------------------------------------------------------------

class _ColorFormatter(logging.Formatter):
    """ANSI-coloured log formatter."""

    _GREY   = "\033[38;5;245m"
    _CYAN   = "\033[38;5;87m"
    _GREEN  = "\033[38;5;82m"
    _YELLOW = "\033[38;5;220m"
    _RED    = "\033[38;5;196m"
    _BOLD_RED = "\033[1;38;5;196m"
    _RESET  = "\033[0m"
    _DIM    = "\033[2m"
    _BOLD   = "\033[1m"

    # (level) -> (level-colour, message-colour)
    _LEVEL_STYLES: dict[int, tuple[str, str]] = {
        logging.DEBUG:    (_CYAN,     _GREY),
        logging.INFO:     (_GREEN,    ""),
        logging.WARNING:  (_YELLOW,   _YELLOW),
        logging.ERROR:    (_RED,      _RED),
        logging.CRITICAL: (_BOLD_RED, _BOLD_RED),
    }

    _FMT = "{dim}{asctime}{reset}  {lvl_color}{bold}[{levelname:<8}]{reset}  {dim}{name}{reset}  {msg_color}{message}{reset}"

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        lvl_color, msg_color = self._LEVEL_STYLES.get(record.levelno, ("", ""))
        fmt = self._FMT.format(
            dim=self._DIM,
            reset=self._RESET,
            bold=self._BOLD,
            lvl_color=lvl_color,
            msg_color=msg_color,
            asctime="%(asctime)s",
            levelname="%(levelname)s",
            name="%(name)s",
            message="%(message)s",
        )
        formatter = logging.Formatter(fmt, datefmt="%H:%M:%S")
        return formatter.format(record)


def _setup_logging(level: int = logging.INFO) -> None:
    """Attach a coloured StreamHandler and a RotatingFileHandler to the root logger (idempotent)."""
    root = logging.getLogger()
    if root.handlers:
        return  # already configured (e.g. when imported as a module)
    root.setLevel(level)
    
    # 1. Console Stream Handler (coloured)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(_ColorFormatter())
    root.addHandler(console_handler)
    
    # 2. File Handler (saved to logs/orchestrator.log with a standard format)
    log_dir = os.path.join(project_root, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "orchestrator.log")
    
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(file_formatter)
    root.addHandler(file_handler)


_setup_logging()
logger = logging.getLogger("Orchestrator")


# ---------------------------------------------------------------------------
# Simulation helpers  (replace internals when real integrations are ready)
# ---------------------------------------------------------------------------

def simulate_scraper_output() -> list[dict]:
    """
    Simulate Stage 1 (Scraper).

    Currently loads from ``ouput_scrap_1.json`` in the project root.
    Replace the body of this function with a real scraper call when available.

    Returns
    -------
    list[dict]
        Raw document metadata as produced by the scraper.
    """
    path = os.path.join(project_root, "ouput_scrap_1.json")
    if not os.path.exists(path):
        logger.warning("Scraper simulation file not found: %s", path)
        return []

    logger.info("simulate_scraper_output: loading from %s", os.path.basename(path))
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def simulate_user_adjustments() -> list[dict]:
    """
    Simulate Stage 2 (User Adjustments / UI approval).

    Currently loads from ``output_1.json`` in the project root.
    Replace the body of this function with the real UI callback / API endpoint
    that returns the user-confirmed (and possibly corrected) metadata records.

    Returns
    -------
    list[dict]
        Metadata records after human review.  Falls back to the raw scraper
        simulation if the adjustments file is absent.
    """
    path = os.path.join(project_root, "output_1.json")
    if os.path.exists(path):
        logger.info("simulate_user_adjustments: loading from %s", os.path.basename(path))
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    logger.warning(
        "User-adjustments file not found (%s). Falling back to raw scraper output.",
        os.path.basename(path),
    )
    return simulate_scraper_output()


# ---------------------------------------------------------------------------
# Orchestrator class
# ---------------------------------------------------------------------------

class Orchestrator:
    """
    Coordinates the end-to-end compliance document pipeline.

    Parameters
    ----------
    push_to_dagshub : bool
        Whether to push ingested metadata to DagsHub after processing.
    """

    def __init__(self, *, push_to_dagshub: bool = False) -> None:
        self.push_to_dagshub = push_to_dagshub

        logger.info("Initialising shared metadata store…")
        self._store = MetadataStore()

        logger.info("Initialising Parsing & Metadata Extractor…")
        self._parsing_extractor = ParsingMetaDataExtractor(metadata_store=self._store)
        # self._parsing_extractor.reset_metadate()

        logger.info("Initialising OCR Pipeline…")
        self._ocr_pipeline = OCRPipeline(metadata_store=self._store)

    # ------------------------------------------------------------------
    # Private stage methods — each maps to one pipeline stage
    # ------------------------------------------------------------------

    def _stage_acquire(self) -> list[dict]:
        """Stage 2: return user-adjusted (or simulated) metadata records."""
        records = simulate_user_adjustments()
        if not records:
            logger.error("No metadata records available after user-adjustment stage.")
        else:
            logger.info("Acquired %d metadata record(s) for ingestion.", len(records))
        return records

    def _stage_ingest(self, records: list[dict]) -> dict:
        """
        Stage 3: download PDFs, compute hashes, detect diffs, persist to store.

        Returns
        -------
        dict
            Ingestion statistics from :pymeth:`ParsingMetaDataExtractor.process_pipeline_general`.
        """
        logger.info("Starting ingestion of %d record(s)…", len(records))
        stats = self._parsing_extractor.process_pipeline_general(
            scraped_data=records,
            push_to_dagshub=self.push_to_dagshub,
        )
        logger.info("Ingestion complete — stats: %s", stats)
        return stats

    def _stage_ocr(self) -> None:
        """
        Stage 4: run OCR & diff engine on all pending documents.

        Pending documents are those inserted or updated by the ingestion stage
        whose full-text has not yet been extracted.
        """
        logger.info("============================================================")
        logger.info("============================================================")
        logger.info("Starting docment processing.")
        logger.info("============================================================")
        logger.info("============================================================")
        
        pending = self._store.get_pending_documents()
        logger.info("Found %d document(s) pending OCR processing.", len(pending))

        if not pending:
            logger.info("No pending documents — OCR stage skipped.")
            return

        logger.info("Launching OCR & document processing for %d document(s)…", len(pending))
        self._ocr_pipeline.run_batch(documents=pending)
        logger.info("OCR stage completed successfully.")

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def run_with_data(self, records: list[dict]) -> None:
        """
        Execute the pipeline with externally-provided (user-approved) records.

        This is the integration point for the User Adjustments API.
        Skips the simulated scraper/UI stage and proceeds directly to
        ingestion (Stage 3) and OCR (Stage 4).

        Parameters
        ----------
        records : list[dict]
            Metadata records that have been reviewed and approved by the user.
        """
        logger.info("=" * 60)
        logger.info("STARTING PIPELINE WITH PRE-APPROVED DATA (%d records)", len(records))
        logger.info("=" * 60)

        if not records:
            logger.error("Aborting: no records provided.")
            return

        # Stage 3 — ingest & hash-diff
        self._stage_ingest(records)

        # Stage 4 — OCR & chunking for changed documents
        self._stage_ocr()

        logger.info("=" * 60)
        logger.info("PIPELINE WITH PRE-APPROVED DATA FINISHED")
        logger.info("=" * 60)

    def run(self) -> None:
        """Execute a full orchestration cycle (all pipeline stages in order)."""
        logger.info("=" * 60)
        logger.info("STARTING PIPELINE ORCHESTRATION CYCLE")
        logger.info("=" * 60)

        # Stage 2 — acquire (simulated until real scraper / UI is wired)
        records = self._stage_acquire()
        if not records:
            logger.error("Aborting orchestration cycle: no records to process.")
            return

        # Stage 3 — ingest & hash-diff
        self._stage_ingest(records)

        # Stage 4 — OCR & chunking for changed documents
        self._stage_ocr()

        logger.info("=" * 60)
        logger.info("ORCHESTRATION CYCLE FINISHED")
        logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    orchestrator = Orchestrator(push_to_dagshub=False)
    orchestrator.run()