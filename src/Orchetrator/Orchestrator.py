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
# Sibling imports (imported after logging setup to ensure colored formatting takes precedence)
# ---------------------------------------------------------------------------
from src.metadata_manager.metadata_store import MetadataStore
from src.Parsing_and_metadata_extractor.parsing_and_metadata_extractor import ParsingMetaDataExtractor
from src.document_processor.pipeline_manager import OCRPipeline
from src.Scrapper.ScrapperClient import ScrapperClient, ScrapperClientError
import requests
from src.Orchetrator.email_sender import send_review_email
from src.mapping.orchestrator import run_mapping_pipeline


# ---------------------------------------------------------------------------
# Live Scraper Integration
# ---------------------------------------------------------------------------

def scrape_live_data(url: str, is_crawl: bool = False, limit: int = 1) -> list[dict]:
    """
    Call the live Scrapper microservice to extract document metadata from a target URL.

    Parameters
    ----------
    url : str
        The web page (or site root) to scrape / crawl.
    is_crawl : bool
        Whether to crawl the site.
    limit : int
        Maximum number of pages to crawl when is_crawl is True.

    Returns
    -------
    list[dict]
        Raw document metadata records.
    """
    logger.info("Starting live scraping from: %s (crawl=%s, limit=%d)", url, is_crawl, limit)
    client = ScrapperClient()
    try:
        data = client.extract_data(url=url, is_crawl=is_crawl, limit=limit)
        if not data:
            logger.warning("Live scraping yielded 0 records.")
            return []
        logger.info("Live scraping successful: fetched %d record(s).", len(data))
        return data
    except ScrapperClientError as exc:
        logger.error("ScrapperClientError during live scraping: %s", exc)
        return []




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

    def __init__(self, *, push_to_dagshub: bool = False, use_adjustments: bool = True) -> None:
        self.push_to_dagshub = push_to_dagshub
        self.use_adjustments = use_adjustments

        logger.info("Initialising shared metadata store…")
        self._store = MetadataStore()

        logger.info("Initialising Parsing & Metadata Extractor…")
        self._parsing_extractor = ParsingMetaDataExtractor(metadata_store=self._store)

        logger.info("Resetting Metadata…")
        # self._parsing_extractor.reset_metadate()

        logger.info("Initialising OCR Pipeline…")
        self._ocr_pipeline = OCRPipeline(metadata_store=self._store)

    # ------------------------------------------------------------------
    # Private stage methods — each maps to one pipeline stage
    # ------------------------------------------------------------------

    def _stage_acquire(
        self,
        url: str | None = None,
        is_crawl: bool = False,
        limit: int = 1,
    ) -> list[dict]:
        """
        Stage 2: Acquire metadata records.

        If a target URL is supplied, calls the live Scraper microservice.
        Otherwise, falls back to simulated/mock user adjustments.
        """
        if url:
            records = scrape_live_data(url=url, is_crawl=is_crawl, limit=limit)
        else:
            records = simulate_user_adjustments()

        if not records:
            logger.error("No metadata records available after acquire stage.")
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

    def run_with_local_file(
        self,
        local_pdf_path: str,
        title: str | None = None,
        metadata: dict | None = None,
        is_internal: bool = False,
    ) -> str | None:
        """
        Ingest a local PDF file, either by creating a human-in-the-loop review session
        or running it directly through the ingestion and OCR stages.

        Parameters
        ----------
        local_pdf_path : str
            Absolute or relative path to the local PDF file.
        title : str, optional
            A descriptive title for the document. Defaults to the filename.
        metadata : dict, optional
            Optional metadata fields (e.g., document_type, issuing_entity, year, language, etc.).
        is_internal : bool, optional
            If True, automatically classifies this document as an internal policy/procedure.

        Returns
        -------
        str | None
            The review URL if `use_adjustments` is True, or None if processed immediately.
        """
        import uuid

        logger.info("=" * 60)
        logger.info("STARTING PIPELINE FOR LOCAL FILE: %s", local_pdf_path)
        logger.info("=" * 60)

        if not os.path.exists(local_pdf_path):
            raise FileNotFoundError(f"Local file not found at: {local_pdf_path}")

        local_path = os.path.dirname(os.path.abspath(local_pdf_path))
        pdf_name = os.path.basename(local_pdf_path)
        default_title = os.path.splitext(pdf_name)[0]

        meta = metadata or {}
        category = "Internal" if is_internal else meta.get("category")
        record = {
            "id": meta.get("id") or default_title.replace(" ", "_"),
            "title": title or default_title,
            "document_type": meta.get("document_type"),
            "issuing_entity": meta.get("issuing_entity"),
            "document_number": meta.get("document_number"),
            "year": meta.get("year"),
            "date": meta.get("date"),
            "language": meta.get("language"),
            "file_url": f"local://{uuid.uuid4().hex[:8]}/{pdf_name}",
            "local_path": local_path,
            "pdf_name": pdf_name,
            "category": category,
            "subcategory": meta.get("subcategory"),
        }

        if self.use_adjustments:
            logger.info("Creating a metadata review session on the User Adjustments API…")
            api_url = os.getenv("USER_ADJUSTMENTS_API_URL", "http://localhost:8080")
            payload = {"documents": [[record]]}
            
            try:
                response = requests.post(f"{api_url}/api/sessions", json=payload, timeout=15)
                response.raise_for_status()
                session_data = response.json()
                
                session_id = session_data["session_id"]
                review_url = f"{api_url.rstrip('/')}{session_data['review_url']}"
                
                logger.info("Successfully created review session: %s", session_id)
                logger.info("Review link: %s", review_url)
                
                send_review_email(review_url)
                
                logger.info("=" * 60)
                logger.info("ORCHESTRATION PAUSED — AWAITING HUMAN REVIEW & APPROVAL")
                logger.info("=" * 60)
                return review_url
            except Exception as exc:
                logger.error("Failed to create review session: %s. Falling back to immediate ingestion…", exc)

        self._stage_ingest([record])
        self._stage_ocr()
        
        logger.info("Starting Compliance Mapping pipeline...")
        run_mapping_pipeline()
        return None

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

        # Run Compliance Mapping
        logger.info("Starting Compliance Mapping pipeline...")
        run_mapping_pipeline()

        logger.info("=" * 60)
        logger.info("PIPELINE WITH PRE-APPROVED DATA FINISHED")
        logger.info("=" * 60)

    def run(
        self,
        url: str | None = None,
        is_crawl: bool = False,
        limit: int = 1,
    ) -> str | None:
        """
        Execute a full orchestration cycle (all pipeline stages in order).

        Parameters
        ----------
        url : str, optional
            The URL to scrape. If not provided, simulated metadata is loaded.
        is_crawl : bool
            Whether to crawl multiple pages when scraping.
        limit : int
            Crawl page limit.

        Returns
        -------
        str | None
            The review URL if a human-review session was created, or None
            if the pipeline ran to completion without user adjustments.
        """
        logger.info("=" * 60)
        logger.info("STARTING PIPELINE ORCHESTRATION CYCLE")
        logger.info("=" * 60)

        # Stage 2 — acquire
        records = self._stage_acquire(url=url, is_crawl=is_crawl, limit=limit)
        if not records:
            logger.error("Aborting orchestration cycle: no records to process.")
            return None

        if self.use_adjustments:
            logger.info("Creating a metadata review session on the User Adjustments API…")
            api_url = os.getenv("USER_ADJUSTMENTS_API_URL", "http://localhost:8080")
            # Ensure documents payload is exactly list[list[dict]] (2D list)
            if records and isinstance(records[0], list):
                documents_payload = records
            else:
                documents_payload = [records]
            payload = {"documents": documents_payload}
            
            try:
                response = requests.post(f"{api_url}/api/sessions", json=payload, timeout=15)
                response.raise_for_status()
                session_data = response.json()
                
                session_id = session_data["session_id"]
                review_url = f"{api_url.rstrip('/')}{session_data['review_url']}"
                
                logger.info("Successfully created review session: %s", session_id)
                logger.info("Review link: %s", review_url)
                
                # Send email containing this review_url
                send_review_email(review_url)
                
                logger.info("=" * 60)
                logger.info("ORCHESTRATION PAUSED — AWAITING HUMAN REVIEW & APPROVAL")
                logger.info("=" * 60)
                return review_url
            except requests.exceptions.ConnectionError:
                logger.error(
                    "Cannot reach the User Adjustments API at '%s'. "
                    "Make sure the FastAPI server is running (`python -m src.user_adjustments_apis.api.run_server`). "
                    "Falling back to immediate ingestion…",
                    api_url
                )
            except Exception as exc:
                logger.error("Failed to create review session: %s. Falling back to immediate ingestion…", exc)

        # Stage 3 — ingest & hash-diff
        self._stage_ingest(records)

        # Stage 4 — OCR & chunking for changed documents
        self._stage_ocr()

        # Run Compliance Mapping
        logger.info("Starting Compliance Mapping pipeline...")
        run_mapping_pipeline()

        logger.info("=" * 60)
        logger.info("ORCHESTRATION CYCLE FINISHED")
        logger.info("=" * 60)
        return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    orchestrator = Orchestrator(push_to_dagshub=False)
    orchestrator.run()