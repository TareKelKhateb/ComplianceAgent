"""
parsing_and_metadata_extractor.py
----------------------------------
Tier 1B: Data ingestion pipeline.

Responsibilities:
  - Fetch document metadata via the ScrapperClient microservice.
  - Download PDFs with bot-bypass headers and content-type validation.
  - Compute SHA-256 hashes for change detection.
  - Persist new/updated documents through the MetadataStore layer.
  - Orchestrate the full pipeline via process_pipeline().

This module NEVER modifies metadata_store.py or db.py. It adapts
to the StorageResult / StoredDocument contract defined in models.py.
"""

import io
import logging
import os
import hashlib
import json
from typing import Any, Optional
from urllib.parse import urlparse

import requests

# pyrefly: ignore [missing-import]
from src.Scrapper.ScrapperClient import ScrapperClient, ScrapperClientError
# pyrefly: ignore [missing-import]
from src.metadata_manager.metadata_store import MetadataStore
# pyrefly: ignore [missing-import]
from src.metadata_manager.models import StorageResult

# ---------------------------------------------------------------------------
# Module-level logger — basicConfig belongs in the entry-point, not here.
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Download headers that bypass basic bot-protection on government portals.
# ---------------------------------------------------------------------------
_DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    # Strictly request PDF or binary stream — do NOT list text/html so that
    # captcha / redirect pages are rejected by the content-type guard below.
    "Accept": "application/pdf, application/octet-stream, */*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.cbe.org.eg/",
}

# Content-type values that are acceptable for a PDF download.
_VALID_PDF_CONTENT_TYPES = {"application/pdf", "application/octet-stream"}


class ParsingMetaDataExtractor:
    """
    Main class for the data ingestion pipeline.

    Dependency injection is supported for both ScrapperClient and
    MetadataStore — pass custom instances for unit-testing.

    Parameters
    ----------
    temp_download_dir : str
        Local directory where downloaded PDFs are saved.
    client : ScrapperClient, optional
        Injected scraper client. Defaults to a new ScrapperClient().
    metadata_store : MetadataStore, optional
        Injected storage layer. Defaults to a new MetadataStore().
    """

    def __init__(
        self,
        temp_download_dir: str = "./local_download",
        client: Optional[ScrapperClient] = None,
        metadata_store: Optional[MetadataStore] = None,
    ) -> None:
        self.logger = logging.getLogger(__name__)

        # Upper-layer scraping API
        self.client = client or ScrapperClient()

        # Local filesystem staging area
        self.temp_download_dir = temp_download_dir

        # Storage layer (source of truth — never modified here)
        self.metadata_store = metadata_store or MetadataStore()

    # =========================================================================
    # STEP 1 — Fetch raw metadata from the scraper microservice
    # =========================================================================

    def fetch_incoming_data(
        self,
        url: str,
        is_crawl: bool = False,
        limit: int = 1,
    ) -> list[Any] | None:
        """
        Call the ScrapperClient to extract document metadata from a target URL.

        Returns
        -------
        list[Any] | None
            List of extracted records, or None if extraction failed / empty.
        """
        mode = f"crawl (limit={limit})" if is_crawl else "single-page scrape"
        self.logger.info("▶  Starting %s for: %s", mode, url)

        data = None
        try:
            data = self.client.extract_data(url=url, is_crawl=is_crawl, limit=limit)
            if data:
                self.logger.info(
                    "✅  Extraction successful — %d record(s) returned.", len(data)
                )
                self.logger.debug(
                    "Extracted Payload:\n%s",
                    json.dumps(data, indent=2, ensure_ascii=False),
                )
            else:
                self.logger.warning("⚠️  Extraction returned no data for: %s", url)
        except ScrapperClientError as e:
            self.logger.error("❌  ScrapperClientError: %s", e)

        return data

    # =========================================================================
    # STEP 2 — Query the storage layer for existing records
    # =========================================================================

    def does_document_exist(self, file_url: str) -> StorageResult:
        """
        Check whether a document URL is already present in the database.

        Returns
        -------
        StorageResult
            .success = True always (check_document_exists never raises).
            .data    = True if found, False if not.
        """
        return self.metadata_store.check_document_exists(file_url=file_url)

    # Keep the old name as an alias so existing callers don't break.
    does_document_exists = does_document_exist

    def fetch_existing_metadata(self, file_url: str) -> StorageResult:
        """
        Retrieve the latest stored version of a document by its URL.

        NOTE: We intentionally use ``get_all_versions_by_url`` here instead of
        ``get_latest_document_by_url``.  ``metadata_store.py`` contains a second
        definition of ``get_latest_document_by_url`` (lines 966-982) that
        overrides the correct one and queries a non-existent ``metadata`` table,
        always returning ``None``.  Since that file is immutable, we route
        through ``get_all_versions_by_url`` (which correctly targets the
        ``documents`` table) and extract the highest-version record ourselves.

        Returns
        -------
        StorageResult
            .success = True if a record was found, False otherwise.
            .data    = StoredDocument (latest version) on success, None on failure.
        """
        versions_result = self.metadata_store.get_all_versions_by_url(file_url=file_url)

        # get_all_versions_by_url returns success=False when no records exist.
        if not versions_result.success or not versions_result.data:
            return StorageResult(
                success=False,
                message=f"No document found for URL '{file_url}'.",
                data=None,
            )

        # The list is ordered v1 → vN; pick the highest version explicitly.
        latest = max(versions_result.data, key=lambda d: d.version)
        return StorageResult(
            success=True,
            message=f"Latest version of '{file_url}' is version {latest.version}.",
            data=latest,
        )

    # =========================================================================
    # STEP 3.1 — Download PDF
    # =========================================================================

    def download_pdf(
        self,
        file_url: str,
        file_name: str,
        save_directory: str,
    ) -> bytes:
        """
        Download a PDF to *save_directory* and return its raw bytes.

        The download is streamed into an in-memory buffer first (avoiding a
        redundant disk-read) and then flushed to disk in one write. Bot-bypass
        headers are applied and the response Content-Type is validated to
        reject captcha/redirect HTML pages disguised as PDFs.

        Parameters
        ----------
        file_url : str
            Direct URL to the PDF document.
        file_name : str
            Desired filename (`.pdf` extension appended if missing).
        save_directory : str
            Target folder path; created automatically if absent.

        Returns
        -------
        bytes
            Raw PDF bytes. Returns ``b""`` on any error.
        """
        self.logger.info("⬇  Downloading PDF: %s", file_url)

        # --- Guard 1: URL scheme validation -----------------------------------
        parsed = urlparse(file_url)
        if parsed.scheme not in {"http", "https"}:
            self.logger.error(
                "❌  Invalid URL scheme '%s' for: %s", parsed.scheme, file_url
            )
            return b""

        # --- Guard 2: Ensure .pdf extension -----------------------------------
        if not file_name.lower().endswith(".pdf"):
            file_name += ".pdf"

        # --- Prepare destination path -----------------------------------------
        os.makedirs(save_directory, exist_ok=True)
        local_file_path = os.path.join(save_directory, file_name)

        try:
            # Stream the response into memory — no disk I/O until fully received.
            buffer = io.BytesIO()
            with requests.get(
                file_url,
                headers=_DOWNLOAD_HEADERS,
                timeout=30,
                stream=True,
                allow_redirects=True,
            ) as response:
                response.raise_for_status()

                # --- Guard 3: Content-Type validation -------------------------
                raw_content_type = response.headers.get("Content-Type", "").lower()
                # Extract base MIME type (strip charset/boundary params)
                base_content_type = raw_content_type.split(";")[0].strip()
                if base_content_type not in _VALID_PDF_CONTENT_TYPES:
                    self.logger.warning(
                        "⚠️  Download blocked — server returned '%s' instead of a PDF "
                        "for: %s",
                        raw_content_type,
                        file_url,
                    )
                    return b""

                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        buffer.write(chunk)

            pdf_bytes = buffer.getvalue()

            if not pdf_bytes:
                self.logger.warning(
                    "⚠️  Download produced 0 bytes for: %s", file_url
                )
                return b""

            # Flush to disk in one write — no second file-read required.
            try:
                with open(local_file_path, "wb") as fh:
                    fh.write(pdf_bytes)
            except OSError as io_err:
                self.logger.error(
                    "❌  Failed to save PDF to '%s': %s", local_file_path, io_err
                )
                # We still have the bytes in memory — return them even if disk
                # write failed so the hash + DB steps can proceed.

            self.logger.info(
                "✅  Downloaded %d bytes → %s", len(pdf_bytes), local_file_path
            )
            return pdf_bytes

        except requests.exceptions.Timeout:
            self.logger.error("❌  Request timed out for: %s", file_url)
        except requests.exceptions.ConnectionError as e:
            self.logger.error("❌  Connection error for %s: %s", file_url, e)
        except requests.exceptions.HTTPError as e:
            self.logger.error(
                "❌  HTTP %s for %s: %s",
                e.response.status_code if e.response else "???",
                file_url,
                e,
            )
        except requests.exceptions.RequestException as e:
            self.logger.error("❌  Request failed for %s: %s", file_url, e)

        return b""

    # =========================================================================
    # STEP 3.2 — Hash computation
    # =========================================================================

    def calculate_hash(self, file_content: bytes) -> str:
        """
        Compute a SHA-256 hash of the given bytes.

        Returns
        -------
        str
            Hex digest string, or ``""`` if *file_content* is empty.
        """
        if not file_content:
            self.logger.warning("⚠️  Empty file content provided for hashing — skipping.")
            return ""

        self.logger.debug("▶  Calculating SHA-256 hash...")
        final_hash = hashlib.sha256(file_content).hexdigest()
        self.logger.info(
            "🔑  Hash: %s...%s", final_hash[:8], final_hash[-8:]
        )
        return final_hash

    # =========================================================================
    # STEP 3.3 — Change detection
    # =========================================================================

    def has_file_changed(self, new_hash: str, old_hash: str) -> bool:
        """
        Compare the new hash against the hash stored in the database.

        Returns
        -------
        bool
            True  — file is new or its content has changed.
            False — file is identical to the stored version, or new hash is invalid.
        """
        if not new_hash:
            self.logger.warning(
                "⚠️  Invalid or empty new hash — skipping change comparison."
            )
            return False

        if not old_hash:
            self.logger.info("➕  No previous version found — treating as new file.")
            return True

        if new_hash != old_hash:
            self.logger.info(
                "⚠️  Content change detected: %s...  →  %s...",
                old_hash[:8],
                new_hash[:8],
            )
            return True

        self.logger.info("🔄  Hash matches stored version — no changes detected.")
        return False

    # =========================================================================
    # STEP 3.4 — Persist new version
    # =========================================================================

    def store_new_version(self, pdf_metadata: dict) -> StorageResult:
        """
        Insert a new document record (or version) via MetadataStore.

        The storage layer handles versioning and deduplication automatically.
        `is_last` demotions for previous versions are performed atomically
        inside `db.insert_document`.

        Parameters
        ----------
        pdf_metadata : dict
            Must contain ``file_url`` and ``sha256_hash`` at minimum.

        Returns
        -------
        StorageResult
        """
        return self.metadata_store.insert_document(data=pdf_metadata)

    def update_old_version(self, pdf_url: str, fields: dict) -> StorageResult:
        """
        Update metadata fields on the latest version of a document by URL.

        Parameters
        ----------
        pdf_url : str
            URL of the document whose latest record will be updated.
        fields : dict
            Column-value pairs to update (e.g. ``{"is_last": False}``).

        Returns
        -------
        StorageResult
        """
        return self.metadata_store.update_document_by_url(
            file_url=pdf_url, fields=fields
        )

    def delete_all_versions(self, pdf_url: str) -> StorageResult:
        """
        Permanently delete all stored versions for a given URL.

        Returns
        -------
        StorageResult
        """
        return self.metadata_store.delete_all_versions_by_url(file_url=pdf_url)

    # =========================================================================
    # DAGSHUB SYNC
    # =========================================================================

    def push_to_dagshub(
        self,
        local_pdf_path: str,
        file_url: str,
        content_hash: str,
    ) -> bool:
        """
        Copy the locally-downloaded PDF into the DVC vault under a
        **content-addressed filename** and push it to DagsHub via DVC.

        Why content-addressed naming?
        ------------------------------
        ``metadata_store.sync_to_dagshub()`` copies the file into the vault
        using its existing filename.  If the file content changes between runs
        but the name stays the same, the old .dvc pointer would be silently
        overwritten in Git, corrupting version history.  By embedding the first
        8 characters of the SHA-256 hash in the filename we guarantee that
        every unique piece of content gets a unique vault path, so previous
        versions remain intact.

        Naming convention
        -----------------
        ``<base_stem>__<hash8>.<ext>``

        Example:
            ``CBE_Law_No._194_of_2020.pdf``  →
            ``CBE_Law_No._194_of_2020__a57db178.pdf``

        Delegates to
        ------------
        :py:meth:`MetadataStore.sync_to_dagshub` which:

        1. Copies the file to ``self.vault_path`` (``data/`` by default).
        2. Runs ``dvc add <file>`` to create a ``.dvc`` pointer.
        3. Stages the pointer with ``git add``.
        4. Commits the pointer to the local Git history.
        5. Runs ``dvc push`` to upload the heavy binary to DagsHub storage.
        6. Updates the document's ``download_status`` to ``'uploaded'`` in
           the metadata database.

        Parameters
        ----------
        local_pdf_path : str
            Absolute or relative path to the PDF on the local filesystem.
            The file must already exist (downloaded by :meth:`download_pdf`).
        file_url : str
            Source URL of the PDF.  Passed to ``sync_to_dagshub`` so the DB
            record can be updated with ``download_status = 'uploaded'``.
        content_hash : str
            Full SHA-256 hex digest of the file content (64 chars).  The
            first 8 characters are embedded in the vault filename.

        Returns
        -------
        bool
            ``True``  — file pushed to DagsHub and DB record updated.
            ``False`` — file not found locally, hash missing, or any
                        DVC / Git subprocess error occurred.

        Example
        -------
        >>> ok = parser.push_to_dagshub(
        ...     local_pdf_path="./local_download/CBE_Law_No._194_of_2020.pdf",
        ...     file_url="https://cbe.org.eg/law194.pdf",
        ...     content_hash="a57db178865f...",
        ... )
        >>> if ok:
        ...     print("Pushed to DagsHub ✅")
        """
        if not os.path.exists(local_pdf_path):
            self.logger.error(
                "❌  [DAGSHUB] Local file not found, cannot push: %s", local_pdf_path
            )
            return False

        if not content_hash:
            self.logger.error(
                "❌  [DAGSHUB] Empty content hash for '%s' — skipping push.",
                local_pdf_path,
            )
            return False

        # ------------------------------------------------------------------
        # Build a content-addressed filename to avoid vault conflicts.
        # Pattern: <stem>__<hash8>.<ext>
        # ------------------------------------------------------------------
        hash_prefix = content_hash[:8]
        base   = os.path.basename(local_pdf_path)
        stem, ext = os.path.splitext(base)
        vault_filename = f"{stem}__{hash_prefix}{ext}"

        # Derive the directory from local_pdf_path and build the vault copy.
        local_dir       = os.path.dirname(os.path.abspath(local_pdf_path))
        vault_local_copy = os.path.join(local_dir, vault_filename)

        try:
            import shutil
            shutil.copy2(local_pdf_path, vault_local_copy)
            self.logger.info(
                "📋  [DAGSHUB] Staging vault copy: %s", vault_filename
            )
        except OSError as copy_err:
            self.logger.error(
                "❌  [DAGSHUB] Failed to create vault copy '%s': %s",
                vault_local_copy,
                copy_err,
            )
            return False

        # ------------------------------------------------------------------
        # Delegate to MetadataStore.sync_to_dagshub — it handles DVC + Git.
        # ------------------------------------------------------------------
        self.logger.info(
            "☁️   [DAGSHUB] Pushing '%s' via DVC...", vault_filename
        )
        success = self.metadata_store.sync_to_dagshub(
            local_pdf_path=vault_local_copy,
            file_url=file_url,
        )

        # Clean up the staging copy from the local download dir regardless
        # of outcome — the permanent copy now lives in the vault.
        try:
            os.remove(vault_local_copy)
        except OSError:
            pass  # Non-fatal: file will just remain as a duplicate locally.

        if success:
            self.logger.info(
                "✅  [DAGSHUB] Successfully pushed '%s' to DagsHub storage.",
                vault_filename,
            )
        else:
            self.logger.error(
                "❌  [DAGSHUB] DVC push failed for '%s'. "
                "The DB record may still be marked as 'downloaded'.",
                vault_filename,
            )

        return success

    # =========================================================================
    # REPORTING — pretty-print database contents as aligned tables
    # =========================================================================

    # ------------------------------------------------------------------
    # Internal table renderer — no third-party deps required.
    # ------------------------------------------------------------------
    @staticmethod
    def _render_table(
        headers: list[str],
        rows: list[list[str]],
        title: str = "",
    ) -> None:
        """
        Print a plain-text aligned table to stdout.

        Parameters
        ----------
        headers : list[str]
            Column header labels.
        rows : list[list[str]]
            Each inner list is one row; values are already stringified.
        title : str, optional
            Banner printed above the table.
        """
        if not rows:
            print(f"\n  (no records to display)\n")
            return

        # Determine column widths from data + header lengths.
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(cell))

        sep   = "┼".join("─" * (w + 2) for w in col_widths)
        h_sep = "╪".join("═" * (w + 2) for w in col_widths)
        top   = "┬".join("─" * (w + 2) for w in col_widths)
        bot   = "┴".join("─" * (w + 2) for w in col_widths)

        def fmt_row(cells: list[str], widths: list[int]) -> str:
            return "│".join(f" {c:<{w}} " for c, w in zip(cells, widths))

        if title:
            total_width = sum(col_widths) + 3 * (len(col_widths) - 1) + 2
            print(f"\n╒{'═' * total_width}╕")
            print(f"│ {title:<{total_width - 1}}│")
            print(f"╞{'═' * total_width}╡")

        print(f"┌{top}┐")
        print(f"│{fmt_row(headers, col_widths)}│")
        print(f"╞{h_sep}╡")
        for i, row in enumerate(rows):
            print(f"│{fmt_row(row, col_widths)}│")
            if i < len(rows) - 1:
                print(f"├{sep}┤")
        print(f"└{bot}┘")
        print()

    @staticmethod
    def _trunc(value: Any, max_len: int = 40) -> str:
        """Stringify and truncate a value to *max_len* characters."""
        s = str(value) if value is not None else "—"
        return s if len(s) <= max_len else s[: max_len - 1] + "…"

    # ------------------------------------------------------------------
    # Public reporting methods
    # ------------------------------------------------------------------

    def print_all_documents(self, latest_only: bool = True) -> None:
        """
        Print a summary table of all documents in the database.

        Uses :py:meth:`MetadataStore.get_all_latest_documents` (default) or
        :py:meth:`MetadataStore.get_all_documents_all_versions` when
        *latest_only* is False.

        Parameters
        ----------
        latest_only : bool
            True  — one row per unique document (latest version only).
            False — one row per stored version (full history).
        """
        if latest_only:
            result = self.metadata_store.get_all_latest_documents()
            title = "📋  All Documents — Latest Versions Only"
        else:
            result = self.metadata_store.get_all_documents_all_versions()
            title = "📋  All Documents — Full Version History"

        if not result.success or not result.data:
            self.logger.warning("⚠️  No documents found in the database.")
            return

        docs = result.data
        headers = ["ID", "Ver", "Status", "Type", "Title", "Hash (prefix)", "Size (KB)", "Stored At"]
        rows = [
            [
                str(d.id),
                str(d.version),
                "✅ latest" if d.is_last else "🔁 old",
                self._trunc(d.document_type, 20),
                self._trunc(d.title, 45),
                d.sha256_hash[:12] + "…" if d.sha256_hash else "—",
                f"{d.file_size_bytes / 1024:.1f}" if d.file_size_bytes else "—",
                (d.created_at or "")[:19],
            ]
            for d in docs
        ]

        self._render_table(headers, rows, title=f"{title}  ({len(docs)} record(s))")
        self.logger.info("🖨️  Displayed %d document(s).", len(docs))

    def print_document_versions(self, file_url: str) -> None:
        """
        Print the full version history of a single document by URL.

        Uses :py:meth:`MetadataStore.get_all_versions_by_url`.

        Parameters
        ----------
        file_url : str
            The URL of the document whose history you want to inspect.
        """
        result = self.metadata_store.get_all_versions_by_url(file_url=file_url)

        if not result.success or not result.data:
            self.logger.warning(
                "⚠️  No versions found for URL: %s", file_url
            )
            return

        docs = result.data
        headers = ["Ver", "Status", "Hash", "Size (KB)", "Download", "Stored At"]
        rows = [
            [
                str(d.version),
                "✅ latest" if d.is_last else "🔁 old",
                d.sha256_hash[:16] + "…" if d.sha256_hash else "—",
                f"{d.file_size_bytes / 1024:.1f}" if d.file_size_bytes else "—",
                d.download_status or "—",
                (d.created_at or "")[:19],
            ]
            for d in docs
        ]

        short_url = self._trunc(file_url, 60)
        self._render_table(
            headers,
            rows,
            title=f"🔍  Version history for: {short_url}  ({len(docs)} version(s))",
        )

    def print_database_stats(self) -> None:
        """
        Print a high-level statistics summary of the database.

        Uses :py:meth:`MetadataStore.get_database_stats`.
        """
        result = self.metadata_store.get_database_stats()

        if not result.success or not result.data:
            self.logger.warning("⚠️  Could not retrieve database statistics.")
            return

        stats = result.data
        headers = ["Metric", "Value"]
        rows = [
            ["Total records (all versions)", str(stats.get("total_records", 0))],
            ["Unique documents",             str(stats.get("unique_documents", 0))],
            ["Latest versions",              str(stats.get("latest_versions", 0))],
            ["Failed downloads",             str(stats.get("failed", 0))],
            ["Pending downloads",            str(stats.get("pending", 0))],
        ]

        self._render_table(headers, rows, title="📊  Database Statistics")

    def search_and_print(
        self,
        title:           Optional[str] = None,
        document_type:   Optional[str] = None,
        issuing_entity:  Optional[str] = None,
        document_number: Optional[str] = None,
        year:            Optional[str] = None,
        language:        Optional[str] = None,
        download_status: Optional[str] = None,
        latest_only:     bool = True,
    ) -> None:
        """
        Search documents by any metadata field combination and print the
        results as a table.

        Uses :py:meth:`MetadataStore.search_documents`. All parameters are
        optional — pass only the fields you want to filter on.

        Parameters
        ----------
        title : str, optional
            Partial title match (LIKE search).
        document_type : str, optional
            Exact match (e.g. ``"LAW"``, ``"REGULATION"``).
        issuing_entity : str, optional
            Partial match.
        document_number : str, optional
            Exact match.
        year : str, optional
            Exact match (e.g. ``"2020"``).
        language : str, optional
            Exact match (e.g. ``"Arabic"``, ``"English"``).
        download_status : str, optional
            Exact match (``"downloaded"``, ``"failed"``, ``"pending"``).
        latest_only : bool
            True — only latest version of each document (default).
            False — include all historical versions.
        """
        result = self.metadata_store.search_documents(
            title=title,
            document_type=document_type,
            issuing_entity=issuing_entity,
            document_number=document_number,
            year=year,
            language=language,
            download_status=download_status,
            latest_only=latest_only,
        )

        if not result.success or not result.data:
            self.logger.info("🔍  Search returned no results.")
            return

        docs = result.data
        active_filters = {k: v for k, v in {
            "title": title, "type": document_type,
            "entity": issuing_entity, "year": year,
            "language": language, "status": download_status,
        }.items() if v}
        filter_str = "  |  ".join(f"{k}={v}" for k, v in active_filters.items()) or "none"

        headers = ["ID", "Ver", "Type", "Title", "Year", "Lang", "Status"]
        rows = [
            [
                str(d.id),
                str(d.version),
                self._trunc(d.document_type, 18),
                self._trunc(d.title, 45),
                d.year or "—",
                d.language or "—",
                d.download_status or "—",
            ]
            for d in docs
        ]

        self._render_table(
            headers,
            rows,
            title=f"🔍  Search Results — {len(docs)} match(es)  [filters: {filter_str}]",
        )

    # =========================================================================
    # ANALYSIS — derive insights from the metadata stored in the DB
    # =========================================================================

    def analyze_type_distribution(self, latest_only: bool = True) -> dict[str, int]:
        """
        Count how many documents exist per ``document_type`` and print a
        terminal bar chart.

        Uses :py:meth:`MetadataStore.get_all_latest_documents` (default) or
        :py:meth:`MetadataStore.get_all_documents_all_versions`.

        Parameters
        ----------
        latest_only : bool, optional
            When True (default) only the latest version of each document is
            counted. Set to False to include all historical versions.

        Returns
        -------
        dict[str, int]
            Mapping of ``{document_type: count}`` sorted descending by count.
            An empty dict is returned when the database is empty.

        Example
        -------
        >>> dist = parser.analyze_type_distribution()
        >>> # {'LAW': 3, 'PRESIDENTIAL_DECREE': 6}
        """
        if latest_only:
            result = self.metadata_store.get_all_latest_documents()
        else:
            result = self.metadata_store.get_all_documents_all_versions()

        if not result.success or not result.data:
            self.logger.warning("⚠️  No documents available for type analysis.")
            return {}

        docs = result.data
        counts: dict[str, int] = {}
        for d in docs:
            key = d.document_type or "UNKNOWN"
            counts[key] = counts.get(key, 0) + 1

        sorted_counts = dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))

        # --- Render bar chart ------------------------------------------------
        total = len(docs)
        bar_max = 30
        max_count = max(sorted_counts.values(), default=1)

        print(f"\n╒{'═' * 62}╕")
        print(f"│ 📊  Document Type Distribution  ({total} total){'':>14}│")
        print(f"╞{'═' * 62}╡")
        for doc_type, count in sorted_counts.items():
            bar_len = int((count / max_count) * bar_max)
            bar = "█" * bar_len + "░" * (bar_max - bar_len)
            pct = count / total * 100
            label = f"{doc_type:<22}"
            print(f"│ {label} {bar} {count:>3} ({pct:5.1f}%) │")
        print(f"╘{'═' * 62}╛\n")

        return sorted_counts

    def analyze_file_sizes(self, latest_only: bool = True) -> dict:
        """
        Compute file-size statistics (min, max, mean, total) broken down by
        ``document_type`` and print a summary table.

        Uses :py:meth:`MetadataStore.get_all_latest_documents` or
        :py:meth:`MetadataStore.get_all_documents_all_versions`.

        Parameters
        ----------
        latest_only : bool, optional
            When True (default) only the latest version is analysed.

        Returns
        -------
        dict
            ``{
                "overall": {"min_kb", "max_kb", "mean_kb", "total_mb"},
                "by_type": {document_type: {"count", "mean_kb", "total_kb"}}
            }``
            Returns an empty dict when no data is available.

        Example
        -------
        >>> sizes = parser.analyze_file_sizes()
        >>> print(sizes["overall"]["mean_kb"])
        """
        if latest_only:
            result = self.metadata_store.get_all_latest_documents()
        else:
            result = self.metadata_store.get_all_documents_all_versions()

        if not result.success or not result.data:
            self.logger.warning("⚠️  No documents available for size analysis.")
            return {}

        docs = [d for d in result.data if d.file_size_bytes]
        if not docs:
            self.logger.warning("⚠️  No documents with recorded file sizes.")
            return {}

        sizes_kb = [d.file_size_bytes / 1024 for d in docs]
        overall = {
            "min_kb":   round(min(sizes_kb), 2),
            "max_kb":   round(max(sizes_kb), 2),
            "mean_kb":  round(sum(sizes_kb) / len(sizes_kb), 2),
            "total_mb": round(sum(sizes_kb) / 1024, 2),
        }

        by_type: dict[str, dict] = {}
        for d in docs:
            key = d.document_type or "UNKNOWN"
            kb = d.file_size_bytes / 1024
            if key not in by_type:
                by_type[key] = {"count": 0, "total_kb": 0.0}
            by_type[key]["count"] += 1
            by_type[key]["total_kb"] += kb
        for key, vals in by_type.items():
            vals["mean_kb"] = round(vals["total_kb"] / vals["count"], 2)
            vals["total_kb"] = round(vals["total_kb"], 2)

        # --- Render table ----------------------------------------------------
        headers = ["Document Type", "Count", "Mean (KB)", "Total (KB)"]
        rows = [
            [
                key,
                str(vals["count"]),
                f"{vals['mean_kb']:.1f}",
                f"{vals['total_kb']:.1f}",
            ]
            for key, vals in sorted(by_type.items(), key=lambda x: x[1]["total_kb"], reverse=True)
        ]
        rows.append(["─" * 20, "─" * 5, "─" * 9, "─" * 10])
        rows.append([
            "TOTAL",
            str(len(docs)),
            f"{overall['mean_kb']:.1f}",
            f"{overall['total_mb'] * 1024:.1f}",
        ])

        self._render_table(headers, rows, title=f"📦  File Size Analysis  ({len(docs)} documents with size data)")

        return {"overall": overall, "by_type": by_type}

    def analyze_version_history(self) -> dict[str, int]:
        """
        Identify documents that have been updated at least once (version > 1)
        and print a table showing each URL's version count.

        Uses :py:meth:`MetadataStore.get_all_documents_all_versions`.

        Returns
        -------
        dict[str, int]
            ``{file_url: version_count}`` for documents with version_count > 1,
            sorted descending. Returns an empty dict when no multi-version
            documents exist.

        Example
        -------
        >>> history = parser.analyze_version_history()
        >>> # {'https://cbe.org.eg/law194.pdf': 3, ...}
        """
        result = self.metadata_store.get_all_documents_all_versions()

        if not result.success or not result.data:
            self.logger.warning("⚠️  No documents available for version analysis.")
            return {}

        docs = result.data

        # Group by URL
        url_versions: dict[str, list] = {}
        for d in docs:
            url_versions.setdefault(d.file_url, []).append(d)

        multi = {
            url: len(versions)
            for url, versions in url_versions.items()
            if len(versions) > 1
        }
        multi = dict(sorted(multi.items(), key=lambda x: x[1], reverse=True))

        stable = len(url_versions) - len(multi)

        print(f"\n╒{'═' * 62}╕")
        print(f"│ 🔄  Version History Analysis{'':>33}│")
        print(f"╞{'═' * 62}╡")
        print(f"│  Unique documents tracked : {len(url_versions):<32}│")
        print(f"│  Never updated (v1 only)  : {stable:<32}│")
        print(f"│  Updated (version > 1)    : {len(multi):<32}│")
        print(f"╘{'═' * 62}╛")

        if multi:
            headers = ["Versions", "Title (latest)", "URL (truncated)"]
            rows_data = []
            for url, ver_count in multi.items():
                latest = max(
                    [d for d in docs if d.file_url == url], key=lambda d: d.version
                )
                rows_data.append([
                    str(ver_count),
                    self._trunc(latest.title, 35),
                    self._trunc(url, 50),
                ])
            self._render_table(
                headers, rows_data,
                title=f"📝  Multi-Version Documents ({len(multi)} URLs)"
            )

        return multi

    def analyze_download_status(self) -> dict[str, int]:
        """
        Break down all database records by their ``download_status`` field
        and print a percentage bar chart.

        Uses :py:meth:`MetadataStore.get_all_documents_all_versions`.

        Possible status values
        ----------------------
        ``"downloaded"`` — PDF successfully downloaded and stored on disk.
        ``"pending"``    — Record inserted but download not yet attempted.
        ``"failed"``     — Download was attempted but failed.
        ``"uploaded"``   — Synced to DagsHub / remote DVC storage.

        Returns
        -------
        dict[str, int]
            ``{status: count}`` mapping, e.g.
            ``{"downloaded": 9, "failed": 0, "pending": 0}``.
            Returns an empty dict when the database is empty.

        Example
        -------
        >>> status = parser.analyze_download_status()
        >>> failed_count = status.get("failed", 0)
        """
        result = self.metadata_store.get_all_documents_all_versions()

        if not result.success or not result.data:
            self.logger.warning("⚠️  No documents available for status analysis.")
            return {}

        docs = result.data
        counts: dict[str, int] = {}
        for d in docs:
            key = d.download_status or "unknown"
            counts[key] = counts.get(key, 0) + 1

        total = len(docs)
        bar_max = 30
        max_count = max(counts.values(), default=1)

        STATUS_ICONS = {
            "downloaded": "✅",
            "failed":     "❌",
            "pending":    "⏳",
            "uploaded":   "☁️ ",
            "unknown":    "❓",
        }

        print(f"\n╒{'═' * 62}╕")
        print(f"│ 📥  Download Status Breakdown  ({total} total records){'':>8}│")
        print(f"╞{'═' * 62}╡")
        for status, count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
            bar_len = int((count / max_count) * bar_max)
            bar = "█" * bar_len + "░" * (bar_max - bar_len)
            pct = count / total * 100
            icon = STATUS_ICONS.get(status, "•")
            label = f"{icon} {status:<12}"
            print(f"│ {label} {bar} {count:>3} ({pct:5.1f}%) │")
        print(f"╘{'═' * 62}╛\n")

        return counts

    def analyze_by_year(self, latest_only: bool = True) -> dict[str, int]:
        """
        Group documents by their ``year`` metadata field and print a
        chronological bar chart.

        Uses :py:meth:`MetadataStore.get_all_latest_documents` or
        :py:meth:`MetadataStore.get_all_documents_all_versions`.

        Parameters
        ----------
        latest_only : bool, optional
            When True (default) each unique document is counted once
            (its latest version). Set to False to count every stored version.

        Returns
        -------
        dict[str, int]
            ``{year: count}`` mapping sorted chronologically.
            Documents without a ``year`` value are grouped under ``"Unknown"``.
            Returns an empty dict when no data is available.

        Example
        -------
        >>> by_year = parser.analyze_by_year()
        >>> # {'2018': 1, '2019': 4, '2020': 1, '2021': 1, 'Unknown': 2}
        """
        if latest_only:
            result = self.metadata_store.get_all_latest_documents()
        else:
            result = self.metadata_store.get_all_documents_all_versions()

        if not result.success or not result.data:
            self.logger.warning("⚠️  No documents available for year analysis.")
            return {}

        docs = result.data
        counts: dict[str, int] = {}
        for d in docs:
            key = str(d.year).strip() if d.year else "Unknown"
            counts[key] = counts.get(key, 0) + 1

        # Sort chronologically; push "Unknown" to the end
        def sort_key(k: str) -> tuple:
            return (1, k) if k == "Unknown" else (0, k)

        sorted_counts = dict(sorted(counts.items(), key=lambda x: sort_key(x[0])))
        total = len(docs)
        bar_max = 30
        max_count = max(sorted_counts.values(), default=1)

        print(f"\n╒{'═' * 62}╕")
        print(f"│ 📅  Documents by Year  ({total} total){'':>23}│")
        print(f"╞{'═' * 62}╡")
        for year, count in sorted_counts.items():
            bar_len = int((count / max_count) * bar_max)
            bar = "█" * bar_len + "░" * (bar_max - bar_len)
            pct = count / total * 100
            label = f"{year:<10}"
            print(f"│ {label} {bar} {count:>3} ({pct:5.1f}%) │")
        print(f"╘{'═' * 62}╛\n")

        return sorted_counts

    def generate_health_report(self) -> dict:
        """
        Run all analysis methods in sequence and print a consolidated
        health report for the metadata store.

        The report covers:

        1. **Database statistics** — total records, unique docs, latest
           versions, failed/pending counts.
        2. **Type distribution** — document counts per ``document_type``.
        3. **Download status** — breakdown of ``downloaded / failed / pending``.
        4. **File size analysis** — min / max / mean sizes per type.
        5. **Version history** — documents that have been updated (version > 1).
        6. **Year distribution** — document counts per year.

        Uses the following MetadataStore methods internally:
            - ``get_database_stats()``
            - ``get_all_latest_documents()``
            - ``get_all_documents_all_versions()``

        Returns
        -------
        dict
            ``{
                "stats":           dict,        # from get_database_stats()
                "type_dist":       dict[str, int],
                "status_dist":     dict[str, int],
                "size_analysis":   dict,
                "version_history": dict[str, int],
                "year_dist":       dict[str, int],
            }``
            Any sub-report that fails returns an empty dict for that key.

        Example
        -------
        >>> report = parser.generate_health_report()
        >>> print(report["stats"]["failed"])       # 0
        >>> print(report["type_dist"]["LAW"])      # 3
        """
        _W = 64
        print(f"\n{'╔' + '═' * (_W - 2) + '╗'}")
        print(f"║{'  🏥  Metadata Store Health Report':^{_W - 2}}║")
        print(f"{'╚' + '═' * (_W - 2) + '╝'}")

        report: dict = {}

        # 1. DB stats
        stats_result = self.metadata_store.get_database_stats()
        report["stats"] = stats_result.data if stats_result.success else {}
        if stats_result.success and stats_result.data:
            s = stats_result.data
            headers = ["Metric", "Value"]
            rows = [
                ["Total records (all versions)", str(s.get("total_records", 0))],
                ["Unique documents",             str(s.get("unique_documents", 0))],
                ["Latest versions",              str(s.get("latest_versions", 0))],
                ["Failed downloads",             str(s.get("failed", 0))],
                ["Pending downloads",            str(s.get("pending", 0))],
            ]
            self._render_table(headers, rows, title="1️⃣   Database Overview")

        # 2. Type distribution
        report["type_dist"] = self.analyze_type_distribution()

        # 3. Download status
        report["status_dist"] = self.analyze_download_status()

        # 4. File sizes
        report["size_analysis"] = self.analyze_file_sizes()

        # 5. Version history
        report["version_history"] = self.analyze_version_history()

        # 6. Year distribution
        report["year_dist"] = self.analyze_by_year()

        print(f"\n{'═' * _W}")
        print(f"  ✅  Health report complete.")
        print(f"{'═' * _W}\n")

        return report

    # =========================================================================
    # MAIN ORCHESTRATOR
    # =========================================================================


    def process_pipeline(
        self,
        target_url: str = "",
        is_crawl: bool = False,
        limit: int = 1,
        save_directory: Optional[str] = None,
        scraped_data: Optional[list] = None,
        push_to_dagshub: bool = True,
    ) -> dict:
        """
        Full end-to-end ingestion pipeline.

        Flow
        ----
        1. Obtain document metadata — either from *scraped_data* (if supplied)
           or by scraping *target_url* via the ScrapperClient.
        2. Normalise the payload — handles both flat ``[dict]`` and nested
           ``[[dict]]`` structures.
        3. For each document:
           a. Validate required fields (``file_url``).
           b. Download the PDF; skip if download fails.
           c. Compute SHA-256 hash; skip if empty.
           d. Check DB existence; branch into INSERT (new) or UPDATE (changed).
           e. Skip if the stored hash matches (content unchanged).
           f. If the document was stored (new or updated) and *push_to_dagshub*
              is True, push the file to DagsHub via DVC under a content-
              addressed filename (``<stem>__<hash8>.pdf``) to prevent vault
              conflicts when file content changes between runs.
        4. Return a stats dict summarising the run.

        Parameters
        ----------
        target_url : str, optional
            Entry-point URL to scrape. Ignored when *scraped_data* is provided.
        is_crawl : bool
            Whether to crawl multiple pages (only used when scraping).
        limit : int
            Maximum pages to crawl when *is_crawl* is True.
        save_directory : str, optional
            Where to save PDFs locally. Defaults to ``self.temp_download_dir``.
        scraped_data : list, optional
            Pre-loaded document list (flat or nested). When provided, the
            ScrapperClient is bypassed completely — useful for processing
            a local JSON file without running the scraper microservice.
        push_to_dagshub : bool, optional
            When True (default) each newly stored or updated document is
            pushed to DagsHub remote storage via DVC after insertion.
            Set to False for dry-runs or when DVC is not configured.

        Returns
        -------
        dict
            ``{"new": int, "updated": int, "skipped": int, "failed": int,
               "pushed": int, "push_failed": int}``
        """
        save_dir = save_directory or self.temp_download_dir
        stats = {"new": 0, "updated": 0, "skipped": 0, "failed": 0,
                 "pushed": 0, "push_failed": 0}

        # ------------------------------------------------------------------
        # Step 1: Obtain raw data — pre-loaded or scraped
        # ------------------------------------------------------------------
        if scraped_data is not None:
            self.logger.info(
                "📂  Using pre-loaded data (%d top-level item(s)).", len(scraped_data)
            )
            raw_data = scraped_data
        else:
            if not target_url:
                self.logger.error(
                    "❌  No target_url provided and no scraped_data supplied. "
                    "Pipeline halted."
                )
                return stats
            raw_data = self.fetch_incoming_data(
                url=target_url, is_crawl=is_crawl, limit=limit
            )

        if not raw_data:
            self.logger.warning("🚫  No data available. Pipeline halted.")
            return stats

        # ------------------------------------------------------------------
        # Step 2: Normalise — handle both flat and nested list structures.
        #   Flat:   [doc_dict, doc_dict, ...]
        #   Nested: [[doc_dict, ...], [doc_dict, ...], ...]
        # ------------------------------------------------------------------
        if raw_data and isinstance(raw_data[0], list):
            # Nested structure — flatten one level
            document_groups = raw_data
        else:
            # Flat structure — wrap in a single group
            document_groups = [raw_data]

        total_docs = sum(len(g) for g in document_groups)
        self.logger.info(
            "📋  Processing %d document(s) across %d page group(s).",
            total_docs,
            len(document_groups),
        )

        # ------------------------------------------------------------------
        # Step 3: Process each document
        # ------------------------------------------------------------------
        for group_idx, document_group in enumerate(document_groups, start=1):
            self.logger.info(
                "━━━  Group %d / %d  (%d docs)",
                group_idx,
                len(document_groups),
                len(document_group),
            )

            for doc_dict in document_group:
                title = doc_dict.get("title", "Unknown Title")
                file_url = doc_dict.get("file_url")

                self.logger.info("📄  Processing: %s", title)

                # Isolate each document — one failure must never crash the run.
                try:
                    # ---- Guard: file_url required --------------------------
                    if not file_url:
                        self.logger.warning(
                            "⚠️  [SKIP] No file_url found for '%s'.", title
                        )
                        stats["skipped"] += 1
                        continue

                    # ---- Step 3a: Download ----------------------------------
                    safe_name = (
                        title.replace(" ", "_").replace("/", "-").replace("\\", "-")
                    )
                    pdf_bytes = self.download_pdf(
                        file_url=file_url,
                        file_name=safe_name,
                        save_directory=save_dir,
                    )

                    if not pdf_bytes:
                        self.logger.error(
                            "❌  [FAIL] Download failed for '%s'. Skipping.", title
                        )
                        stats["failed"] += 1
                        continue

                    # ---- Step 3b: Hash -------------------------------------
                    new_hash = self.calculate_hash(file_content=pdf_bytes)
                    if not new_hash:
                        self.logger.error(
                            "❌  [FAIL] Hash computation failed for '%s'. Skipping.", title
                        )
                        stats["failed"] += 1
                        continue

                    # Build the payload once — shared by both INSERT branches.
                    insert_payload = {
                        "file_url": file_url,
                        "sha256_hash": new_hash,
                        "is_last": True,
                        "title": title,
                        "document_type": doc_dict.get("document_type"),
                        "issuing_entity": doc_dict.get("issuing_entity"),
                        "document_number": doc_dict.get("document_number"),
                        "year": doc_dict.get("year"),
                        "date": doc_dict.get("date"),
                        "language": doc_dict.get("language"),
                        "file_path": os.path.join(
                            save_dir, safe_name if safe_name.endswith(".pdf") else safe_name + ".pdf"
                        ),
                        "file_size_bytes": len(pdf_bytes),
                        "download_status": "downloaded",
                    }

                    # ---- Step 3c: DB existence check -----------------------
                    exist_result = self.does_document_exist(file_url=file_url)

                    # check_document_exists always returns StorageResult with
                    # .success=True; .data is bool. Guard anyway for safety.
                    if not exist_result.success:
                        self.logger.error(
                            "❌  [FAIL] DB existence check failed for '%s': %s",
                            title,
                            exist_result.message,
                        )
                        stats["failed"] += 1
                        continue

                    document_exists: bool = bool(exist_result.data)

                    # ---- Step 3d: Branch — existing document ----------------
                    if document_exists:
                        self.logger.info(
                            "🗃️  Record found in database. Checking for changes..."
                        )

                        meta_result = self.fetch_existing_metadata(file_url=file_url)

                        if not meta_result.success or meta_result.data is None:
                            self.logger.error(
                                "❌  [FAIL] Could not fetch stored metadata for '%s': %s",
                                title,
                                meta_result.message,
                            )
                            stats["failed"] += 1
                            continue

                        stored_doc = meta_result.data
                        is_changed = self.has_file_changed(
                            new_hash=new_hash,
                            old_hash=stored_doc.sha256_hash,
                        )

                        if is_changed:
                            self.logger.info(
                                "⬆️  [UPDATE] Content changed. Storing new version..."
                            )
                            # The DB layer atomically demotes is_last on insert
                            # when version > 1, so no explicit update_old_version
                            # call is needed. However we call it explicitly for
                            # clarity and auditability.
                            self.update_old_version(
                                pdf_url=file_url, fields={"is_last": False}
                            )
                            store_result = self.store_new_version(insert_payload)
                            if store_result.success:
                                self.logger.info(
                                    "✅  [UPDATE] New version stored: %s",
                                    store_result.message,
                                )
                                stats["updated"] += 1
                                # Push updated file to DagsHub under a new
                                # content-addressed name to avoid vault conflicts.
                                if push_to_dagshub:
                                    pushed = self.push_to_dagshub(
                                        local_pdf_path=insert_payload["file_path"],
                                        file_url=file_url,
                                        content_hash=new_hash,
                                    )
                                    stats["pushed" if pushed else "push_failed"] += 1
                            else:
                                self.logger.error(
                                    "❌  [FAIL] Failed to store new version for '%s': %s",
                                    title,
                                    store_result.message,
                                )
                                stats["failed"] += 1
                        else:
                            self.logger.info(
                                "🔄  [SKIP] Document is up-to-date: '%s'", title
                            )
                            stats["skipped"] += 1

                    # ---- Step 3e: Branch — new document --------------------
                    else:
                        self.logger.info(
                            "➕  [NEW] No existing record. Inserting as version 1..."
                        )
                        store_result = self.store_new_version(insert_payload)
                        if store_result.success:
                            self.logger.info(
                                "✅  [NEW] Document stored: %s", store_result.message
                            )
                            stats["new"] += 1
                            # Push new file to DagsHub with content-addressed name.
                            if push_to_dagshub:
                                pushed = self.push_to_dagshub(
                                    local_pdf_path=insert_payload["file_path"],
                                    file_url=file_url,
                                    content_hash=new_hash,
                                )
                                stats["pushed" if pushed else "push_failed"] += 1
                        else:
                            self.logger.error(
                                "❌  [FAIL] DB insertion failed for '%s': %s",
                                title,
                                store_result.message,
                            )
                            stats["failed"] += 1

                except Exception as exc:
                    # Per-document safety net — the pipeline must never crash.
                    self.logger.exception(
                        "💥  [UNHANDLED] Unexpected error processing '%s': %s",
                        title,
                        exc,
                    )
                    stats["failed"] += 1

        return stats
    
    def reset_metadate(self):
        self.metadata_store.reset_all_data()

    # ------------------------------------------------------------------------------------------------------
    # ## General Pipeline For Local Files & Remote URLs
    # ------------------------------------------------------------------------------------------------------

    def process_pipeline_general(
        self,
        target_url: str = "",
        is_crawl: bool = False,
        limit: int = 1,
        save_directory: Optional[str] = None,
        scraped_data: Optional[list] = None,
        push_to_dagshub: bool = True,
    ) -> dict:
        """
        Generalized end-to-end ingestion pipeline supporting both 
        remote downloads and pre-existing local files.
        """
        save_dir = save_directory or self.temp_download_dir
        stats = {"new": 0, "updated": 0, "skipped": 0, "failed": 0,
                 "pushed": 0, "push_failed": 0}

        # --- Step 1: Obtain raw data ---
        if scraped_data is not None:
            self.logger.info("📂 Using pre-loaded data (%d items).", len(scraped_data))
            raw_data = scraped_data
        else:
            if not target_url:
                self.logger.error("❌ No target_url and no scraped_data. Halted.")
                return stats
            raw_data = self.fetch_incoming_data(url=target_url, is_crawl=is_crawl, limit=limit)

        if not raw_data:
            self.logger.warning("🚫 No data available. Pipeline halted.")
            return stats

        # --- Step 2: Normalise ---
        document_groups = raw_data if raw_data and isinstance(raw_data[0], list) else [raw_data]
        total_docs = sum(len(g) for g in document_groups)
        self.logger.info("📋 Processing %d document(s) across %d group(s).", total_docs, len(document_groups))

        # --- Step 3: Process documents ---
        for group_idx, document_group in enumerate(document_groups, start=1):
            for doc_dict in document_group:
                title = doc_dict.get("title", "Unknown Title")
                file_url = doc_dict.get("file_url")
                
                # New keys for local processing
                local_path = doc_dict.get("local_path")
                pdf_name = doc_dict.get("pdf_name")

                self.logger.info("📄 Processing: %s", title)

                try:
                    if not file_url:
                        self.logger.warning("⚠️ [SKIP] No file_url found for '%s'.", title)
                        stats["skipped"] += 1
                        continue

                    pdf_bytes = None
                    final_file_path = ""

                    # ---- Step 3a: Check Local Path First --------------------
                    if local_path and pdf_name:
                        potential_path = os.path.join(local_path, pdf_name)
                        print(f"DEBUG: I am looking for the file exactly here: {os.path.abspath(potential_path)}") 
                        if os.path.exists(potential_path):
                            self.logger.info("🏠 [LOCAL] File found at %s. Skipping download.", potential_path)
                            try:
                                with open(potential_path, "rb") as f:
                                    pdf_bytes = f.read()
                                final_file_path = potential_path
                            except Exception as e:
                                self.logger.error("❌ [FAIL] Could not read local file %s: %s", potential_path, e)

                    # ---- Step 3b: Fallback to Download ----------------------
                    if not pdf_bytes:
                        safe_name = title.replace(" ", "_").replace("/", "-").replace("\\", "-")
                        if not safe_name.endswith(".pdf"):
                            safe_name += ".pdf"
                            
                        pdf_bytes = self.download_pdf(
                            file_url=file_url,
                            file_name=safe_name,
                            save_directory=save_dir,
                        )
                        final_file_path = os.path.join(save_dir, safe_name)

                    if not pdf_bytes:
                        self.logger.error("❌ [FAIL] Source acquisition failed for '%s'. Skipping.", title)
                        stats["failed"] += 1
                        continue

                    # ---- Step 3c: Hash -------------------------------------
                    new_hash = self.calculate_hash(file_content=pdf_bytes)
                    if not new_hash:
                        stats["failed"] += 1
                        continue

                    # Build Payload
                    insert_payload = {
                        "file_url": file_url,
                        "sha256_hash": new_hash,
                        "is_last": True,
                        "title": title,
                        "document_type": doc_dict.get("document_type"),
                        "issuing_entity": doc_dict.get("issuing_entity"),
                        "document_number": doc_dict.get("document_number"),
                        "year": doc_dict.get("year"),
                        "date": doc_dict.get("date"),
                        "language": doc_dict.get("language"),
                        "file_path": final_file_path,
                        "file_size_bytes": len(pdf_bytes),
                        "download_status": "downloaded",
                    }

                    # ---- Step 3d: DB existence & Versioning ----------------
                    exist_result = self.does_document_exist(file_url=file_url)
                    if not exist_result.success:
                        stats["failed"] += 1
                        continue

                    if bool(exist_result.data):
                        self.logger.info("🗃️ Record found. Checking hash...")
                        meta_result = self.fetch_existing_metadata(file_url=file_url)
                        
                        if not meta_result.success or meta_result.data is None:
                            stats["failed"] += 1
                            continue

                        stored_doc = meta_result.data
                        if self.has_file_changed(new_hash, stored_doc.sha256_hash):
                            self.logger.info("⬆️ [UPDATE] Content changed.")
                            self.update_old_version(pdf_url=file_url, fields={"is_last": False})
                            store_result = self.store_new_version(insert_payload)
                            if store_result.success:
                                stats["updated"] += 1
                                if push_to_dagshub:
                                    pushed = self.push_to_dagshub(final_file_path, file_url, new_hash)
                                    stats["pushed" if pushed else "push_failed"] += 1
                        else:
                            self.logger.info("🔄 [SKIP] Up-to-date: '%s'", title)
                            stats["skipped"] += 1
                    else:
                        self.logger.info("➕ [NEW] Inserting version 1...")
                        store_result = self.store_new_version(insert_payload)
                        if store_result.success:
                            stats["new"] += 1
                            if push_to_dagshub:
                                pushed = self.push_to_dagshub(final_file_path, file_url, new_hash)
                                stats["pushed" if pushed else "push_failed"] += 1

                except Exception as exc:
                    self.logger.exception("💥 [UNHANDLED] Error processing '%s': %s", title, exc)
                    stats["failed"] += 1

        return stats