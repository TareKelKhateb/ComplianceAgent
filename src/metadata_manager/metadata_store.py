"""
metadata_store.py
-----------------
THE ONLY FILE YOUR TEAMMATE NEEDS TO IMPORT.

Your teammate (Tier 1B) sends you a JSON/dict with:
    - file_url       (required)
    - sha256_hash    (required — computed by your teammate, not here)
    - title, document_type, issuing_entity, ... (optional metadata)
    - file_path, file_size_bytes, download_status (optional, set by teammate)

This layer stores everything in SQLite and gives full CRUD access.
No downloading, no hashing, no file I/O — that's your teammate's job.

QUICKSTART:
    from storage import MetadataStore

    store = MetadataStore()

    # Insert a document received from teammate
    result = store.insert_document({
        "file_url":    "https://cbe.org.eg/law194.pdf",
        "sha256_hash": "a3f9...",
        "title":       "CBE Law No. 194",
        "year":        "2020",
        "file_path":   "/pdfs/law194_v1.pdf",
    })

    print(result.success)  # True
    print(result.data)     # StoredDocument(id=1, version=1, ...)
"""

import csv
import json
import os
import sqlite3
from typing import Optional
import subprocess
import shutil

from .db import (
    init_db,
    check_hash,
    insert_document,               # Use this instead of insert_document (Correct)
    update_document_file_info,     # Use this instead of db_update_fields
    get_document_by_id,            # Use this instead of db_get_by_id
    get_latest_by_url,             # Use this instead of db_get_latest_by_url
    get_all_versions_by_url,       # (Correct)
    get_all_latest_documents,      # Use this instead of db_get_all_latest
    search_by_metadata,            # Use this instead of db_search
    get_documents_by_download_status, # Use this for status-based queries
    mark_download_failed,
    insert_documents_batch,
)
from .models import StorageResult, StoredDocument, BatchStorageResult

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_FILE_PATH = os.path.join(ROOT_DIR, "config.yaml")
DEFAULT_DB_PATH = os.path.join(ROOT_DIR, "data", "legal_vault.db")


def _parse_simple_yaml(yaml_text: str) -> dict[str, str]:
    """Parse a minimal YAML mapping from key: value lines."""
    config = {}
    for raw_line in yaml_text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith("\"") and value.endswith("\"")) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        config[key] = value
    return config


def _load_config() -> dict[str, str]:
    if not os.path.exists(CONFIG_FILE_PATH):
        return {}
    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as fh:
            return _parse_simple_yaml(fh.read())
    except Exception:
        return {}


def _get_database_path_from_config() -> str:
    config = _load_config()
    db_path = config.get("database_path")
    if not db_path:
        return DEFAULT_DB_PATH
    if os.path.isabs(db_path):
        return db_path
    return os.path.join(ROOT_DIR, db_path)


def _get_vault_path_from_config() -> str:
    config = _load_config()
    vault_path = config.get("vault_path")
    if not vault_path:
        return os.path.join(ROOT_DIR, "data")
    if os.path.isabs(vault_path):
        return vault_path
    return os.path.join(ROOT_DIR, vault_path)


class MetadataStore:
    """
    Full metadata CRUD layer over SQLite.
    Instantiate once and reuse across your script.

        store = MetadataStore()                      # default path
        store = MetadataStore(db_path="custom.db")   # custom path
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or _get_database_path_from_config()
        self.vault_path = _get_vault_path_from_config()
        init_db(self.db_path)

    # =======================================================================
    # INSERT
    # =======================================================================

    def insert_document(self, data: dict) -> StorageResult:
        """
        Insert one document received from your teammate.

        Required keys in data:
            file_url    (str)  — URL of the PDF
            sha256_hash (str)  — hash computed by your teammate

        Optional keys:
            title, document_type, issuing_entity, document_number,
            year, date, language, file_path, file_size_bytes, download_status

        Deduplication logic (automatic):
            Same URL + Same hash    → skip, return existing record
            Same hash, diff URL     → skip (same PDF content already stored)
            Same URL, diff hash     → insert as next version (content changed)
            New URL + New hash      → insert as version 1

        Returns:
            StorageResult where .data is the StoredDocument
        """
        file_url    = data.get("file_url", "").strip()
        sha256_hash = data.get("sha256_hash", "").strip()

        if not file_url:
            return StorageResult(
                success=False,
                message="Insert failed: 'file_url' is required but missing.",
            )
        if not sha256_hash:
            return StorageResult(
                success=False,
                message="Insert failed: 'sha256_hash' is required but missing. "
                        "Your teammate should compute this before calling insert_document().",
            )

        check = check_hash(self.db_path, file_url, sha256_hash)

        if check["action"] == "skip":
            # return the existing record so the caller still gets a StoredDocument
            existing = get_latest_by_url(self.db_path, file_url)
            return StorageResult(
                success=True,
                message=f"Skipped (no insert needed): {check['reason']}",
                data=existing,
            )

        try:
            doc = insert_document(self.db_path, data, version=check["new_version"])
            return StorageResult(
                success=True,
                message=f"Inserted successfully — {check['reason']}",
                data=doc,
            )
        except sqlite3.IntegrityError as e:
            return StorageResult(
                success=False,
                message=f"Insert failed — database integrity error: {e}",
            )
        except Exception as e:
            return StorageResult(success=False, message=f"Insert failed: {e}")

    def insert_documents_batch(self, data_list: list[dict]) -> StorageResult:
        """
        Insert multiple documents at once from a JSON list.

        Args:
            data_list: list of dicts, each matching insert_document() format

        Returns:
            StorageResult where .data is a list of individual StorageResult objects
        """
        if not data_list:
            return StorageResult(
                success=False,
                message="Batch insert failed: received an empty list.",
            )

        results = []
        for i, item in enumerate(data_list, start=1):
            label = item.get("title") or item.get("file_url") or f"item #{i}"
            result = self.insert_document(item)
            results.append(result)

        inserted = sum(1 for r in results if r.success and "Inserted" in r.message)
        skipped  = sum(1 for r in results if r.success and "Skipped"  in r.message)
        failed   = sum(1 for r in results if not r.success)

        return StorageResult(
            success=failed == 0,
            message=(
                f"Batch complete — {inserted} inserted, "
                f"{skipped} skipped (duplicates), "
                f"{failed} failed out of {len(data_list)} total."
            ),
            data=results,
        )

    def insert_documents_from_json_file(self, json_file_path: str) -> StorageResult:
        """
        Load a JSON file from disk and insert all records.
        The file should be a JSON array of document dicts.

        Example file content:
            [
              {"file_url": "...", "sha256_hash": "...", "title": "..."},
              {"file_url": "...", "sha256_hash": "...", "title": "..."}
            ]

        Returns:
            StorageResult — same as insert_documents_batch()
        """
        if not os.path.exists(json_file_path):
            return StorageResult(
                success=False,
                message=f"JSON file not found at: '{json_file_path}'",
            )
        try:
            with open(json_file_path, "r", encoding="utf-8") as f:
                data_list = json.load(f)
        except json.JSONDecodeError as e:
            return StorageResult(
                success=False,
                message=f"Failed to parse JSON file '{json_file_path}': {e}",
            )
        except Exception as e:
            return StorageResult(success=False, message=f"Failed to read file: {e}")

        if not isinstance(data_list, list):
            return StorageResult(
                success=False,
                message="JSON file must contain a list (array) at the top level.",
            )

        return self.insert_documents_batch(data_list)

    # =======================================================================
    # UPDATE
    # =======================================================================

    def update_document_by_id(self, document_id: int, fields: dict) -> StorageResult:
        """
        Update any metadata fields of a document by its ID.
        Only the keys you provide are updated — everything else stays the same.

        Updatable fields:
            title, document_type, issuing_entity, document_number,
            year, date, language, file_path, file_size_bytes, download_status

        Example:
            store.update_document_by_id(5, {"title": "New Title", "year": "2021"})

        Returns:
            StorageResult where .data is the updated StoredDocument
        """
        if not fields:
            return StorageResult(
                success=False,
                message="Update failed: no fields provided. Pass a dict with at least one field.",
            )

        existing = get_document_by_id(self.db_path, document_id)
        if not existing:
            return StorageResult(
                success=False,
                message=f"Update failed: no document found with id={document_id}.",
            )

        try:
            updated = update_document_file_info(self.db_path, document_id, fields)
            changed = [k for k in fields if k in {
                "title", "document_type", "issuing_entity", "document_number",
                "year", "date", "language", "file_path", "file_size_bytes", "download_status",
            }]
            return StorageResult(
                success=True,
                message=f"Updated document id={document_id}. Fields changed: {changed}.",
                data=updated,
            )
        except Exception as e:
            return StorageResult(success=False, message=f"Update failed: {e}")

    def update_document_by_url(self, file_url: str, fields: dict) -> StorageResult:
        """
        Update metadata of the LATEST version of a document by its URL.
        Same rules as update_document_by_id() — only provided fields are updated.

        Example:
            store.update_document_by_url(
                "https://cbe.org.eg/law194.pdf",
                {"issuing_entity": "CBE", "language": "Arabic"}
            )

        Returns:
            StorageResult where .data is the updated StoredDocument
        """
        doc = get_latest_by_url(self.db_path, file_url)
        if not doc:
            return StorageResult(
                success=False,
                message=f"Update failed: no document found for URL '{file_url}'.",
            )
        return self.update_document_by_id(doc.id, fields)

    def update_all_versions_by_url(self, file_url: str, fields: dict) -> StorageResult:
        """
        Update metadata across ALL versions of a URL.
        Useful when the issuing_entity or language was wrong and needs correction everywhere.

        Returns:
            StorageResult where .data is list of updated StoredDocument objects
        """
        docs = get_all_versions_by_url(self.db_path, file_url)
        if not docs:
            return StorageResult(
                success=False,
                message=f"No documents found for URL '{file_url}'.",
            )

        updated = []
        for doc in docs:
            result = self.update_document_by_id(doc.id, fields)
            if result.success:
                updated.append(result.data)

        return StorageResult(
            success=True,
            message=f"Updated {len(updated)} version(s) of '{file_url}'.",
            data=updated,
        )

    # =======================================================================
    # DELETE
    # =======================================================================

    def delete_document_by_id(self, document_id: int) -> StorageResult:
        """Permanently removes a document record from the database by its ID."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Get info for version promotion logic if needed
                cursor = conn.execute("SELECT file_url, is_last FROM documents WHERE id = ?", (document_id,))
                row = cursor.fetchone()
                
                if not row:
                    return StorageResult(success=False, message="Document not found.")

                file_url, was_last = row
                
                # Perform the actual deletion
                conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
                conn.commit()

            # If you deleted the most recent version, promote the one before it
            if was_last:
                self._promote_previous_version(file_url)

            return StorageResult(
                success=True, 
                message=f"Successfully deleted document ID {document_id}."
            )
        except Exception as e:
            return StorageResult(success=False, message=str(e))
        
    def delete_all_versions_by_url(self, file_url: str) -> StorageResult:
            """Wipes all historical versions associated with a specific URL."""
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.execute("DELETE FROM documents WHERE file_url = ?", (file_url,))
                    deleted_count = cursor.rowcount
                    conn.commit()
                    
                return StorageResult(
                    success=True,
                    message=f"Deleted {deleted_count} version(s) for {file_url}.",
                    data=deleted_count
                )
            except Exception as e:
                return StorageResult(success=False, message=str(e))

    def delete_old_versions_by_url(self, file_url: str) -> StorageResult:
        """
        Delete only the OLD versions of a document — keeps the latest (is_last=True).
        Useful for cleanup after confirming the new version is correct.

        Returns:
            StorageResult where .data is count of deleted old records
        """
        all_versions = get_all_versions_by_url(self.db_path, file_url)
        old_versions = [d for d in all_versions if not d.is_last]

        if not old_versions:
            return StorageResult(
                success=True,
                message=f"No old versions to delete for '{file_url}' — only one version exists.",
                data=0,
            )

        count = 0
        for doc in old_versions:
            mark_download_failed(self.db_path, doc.id)
            count += 1

        return StorageResult(
            success=True,
            message=f"Deleted {count} old version(s) of '{file_url}'. Latest version kept.",
            data=count,
        )

    def delete_documents_batch_by_ids(self, document_ids: list[int]) -> StorageResult:
        """
        Delete multiple documents by a list of IDs.

        Returns:
            StorageResult where .data is dict with deleted/not_found counts
        """
        if not document_ids:
            return StorageResult(
                success=False,
                message="Delete failed: received empty list of IDs.",
            )

        deleted = not_found = 0
        for doc_id in document_ids:
            result = self.delete_document_by_id(doc_id)
            if result.success:
                deleted += 1
            else:
                not_found += 1

        return StorageResult(
            success=True,
            message=f"Batch delete — {deleted} deleted, {not_found} not found.",
            data={"deleted": deleted, "not_found": not_found},
        )

    def reset_all_data(self) -> StorageResult:
        """
        ⚠ DANGER: Wipe the entire database and reset ID counter.
        Use only in development/testing.

        Returns:
            StorageResult
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM documents")
                # Reset the AUTOINCREMENT counter so IDs restart from 1
                conn.execute(
                    "DELETE FROM sqlite_sequence WHERE name = 'documents'"
                )
                conn.commit()
            return StorageResult(
                success=True,
                message="Database wiped and reset. All records deleted, ID counter restarted.",
            )
        except Exception as e:
            return StorageResult(success=False, message=f"Reset failed: {e}")

    # =======================================================================
    # READ / QUERY
    # =======================================================================

    def get_document_by_id(self, document_id: int) -> StorageResult:
        """
        Get one document by its database ID.

        Returns:
            StorageResult where .data is StoredDocument or None
        """
        doc = get_document_by_id(self.db_path, document_id)
        if not doc:
            return StorageResult(
                success=False,
                message=f"No document found with id={document_id}.",
            )
        return StorageResult(
            success=True,
            message=f"Found document id={document_id} (version {doc.version}).",
            data=doc,
        )

    def get_latest_document_by_url(self, file_url: str) -> StorageResult:
        """
        Get the latest version of a document by URL.

        Returns:
            StorageResult where .data is StoredDocument
        """
        doc = get_latest_by_url(self.db_path, file_url)
        if not doc:
            return StorageResult(
                success=False,
                message=f"No document found for URL '{file_url}'.",
            )
        return StorageResult(
            success=True,
            message=f"Latest version of '{file_url}' is version {doc.version}.",
            data=doc,
        )

    def get_all_versions_by_url(self, file_url: str) -> StorageResult:
        """
        Get all versions of a document by URL, ordered v1 → vN.

        Returns:
            StorageResult where .data is list of StoredDocument
        """
        docs = get_all_versions_by_url(self.db_path, file_url)
        if not docs:
            return StorageResult(
                success=False,
                message=f"No documents found for URL '{file_url}'.",
            )
        return StorageResult(
            success=True,
            message=f"Found {len(docs)} version(s) for '{file_url}'.",
            data=docs,
        )

    def get_all_latest_documents(self) -> StorageResult:
        """
        Get the latest version of every document in the DB.
        This is the main handoff to Tier 2 (chunking & vector DB).

        Returns:
            StorageResult where .data is list of StoredDocument
        """
        docs = get_all_latest_documents(self.db_path)
        return StorageResult(
            success=True,
            message=f"Retrieved {len(docs)} document(s) (latest versions only).",
            data=docs,
        )

    def get_all_documents_all_versions(self) -> StorageResult:
        """
        Get every record in the DB — all versions of all documents.

        Returns:
            StorageResult where .data is list of StoredDocument
        """
        docs = search_by_metadata(self.db_path, latest_only=False)
        return StorageResult(
            success=True,
            message=f"Retrieved {len(docs)} total record(s) (all versions included).",
            data=docs,
        )

    def search_documents(
        self,
        title:           Optional[str] = None,
        document_type:   Optional[str] = None,
        issuing_entity:  Optional[str] = None,
        document_number: Optional[str] = None,
        year:            Optional[str] = None,
        language:        Optional[str] = None,
        download_status: Optional[str] = None,
        latest_only:     bool = True,
    ) -> StorageResult:
        """
        Search documents by any combination of metadata fields.
        All arguments are optional — pass only what you want to filter by.
        title and issuing_entity support partial match (LIKE search).

        Examples:
            store.search_documents(issuing_entity="Central Bank")
            store.search_documents(document_type="LAW", year="2020")
            store.search_documents(download_status="failed")
            store.search_documents(title="CBE", latest_only=False)

        Returns:
            StorageResult where .data is list of StoredDocument
        """
        docs = search_by_metadata(
            self.db_path,
            title=title,
            document_type=document_type,
            issuing_entity=issuing_entity,
            document_number=document_number,
            year=year,
            language=language,
            download_status=download_status,
            latest_only=latest_only,
        )
        active_filters = {k: v for k, v in {
            "title": title, "document_type": document_type,
            "issuing_entity": issuing_entity, "year": year,
            "language": language, "download_status": download_status,
        }.items() if v}
        filter_str = ", ".join(f"{k}='{v}'" for k, v in active_filters.items()) or "none"
        return StorageResult(
            success=True,
            message=f"Found {len(docs)} document(s) — filters: {filter_str}.",
            data=docs,
        )

    def check_document_exists(self, file_url: str = None, sha256_hash: str = None) -> StorageResult:
        """
        Check if a document already exists by URL or hash (or both).

        Returns:
            StorageResult where .data is True/False
        """
        if not file_url and not sha256_hash:
            return StorageResult(
                success=False,
                message="Provide at least one of: file_url, sha256_hash.",
            )

        docs = search_by_metadata(
            self.db_path,
            latest_only=False,
        )
        found = [
            d for d in docs
            if (file_url and d.file_url == file_url)
            or (sha256_hash and d.sha256_hash == sha256_hash)
        ]
        exists = len(found) > 0
        return StorageResult(
            success=True,
            message=f"Document {'found' if exists else 'not found'} — "
                    f"matched {len(found)} record(s).",
            data=exists,
        )

    def get_database_stats(self) -> StorageResult:
        """
        Summary statistics about the database.

        Returns:
            StorageResult where .data is a dict:
            {
                "total_records":    int,
                "unique_documents": int,
                "latest_versions":  int,
                "failed":           int,
                "pending":          int,
            }
        """
        all_docs   = search_by_metadata(self.db_path, latest_only=False)
        latest     = get_all_latest_documents(self.db_path)
        failed     = get_documents_by_download_status(self.db_path, "failed")
        pending    = get_documents_by_download_status(self.db_path, "pending")

        unique_urls = len({d.file_url for d in all_docs})
        stats = {
            "total_records":    len(all_docs),
            "unique_documents": unique_urls,
            "latest_versions":  len(latest),
            "failed":           len(failed),
            "pending":          len(pending),
        }
        return StorageResult(
            success=True,
            message=(
                f"DB has {stats['total_records']} total records across "
                f"{stats['unique_documents']} unique document(s). "
                f"{stats['failed']} failed, {stats['pending']} pending."
            ),
            data=stats,
        )

    # =======================================================================
    # DagsHub / DVC EXPORT & IMPORT
    # =======================================================================

    def export_to_json(self, output_path: str = None) -> StorageResult:
        """
        Export the full DB to a JSON file so it can be tracked by DVC and
        pushed to DagsHub for your teammates to share.

        Default output: data/legal_vault_export.json

        Workflow:
            1. store.export_to_json()
            2. dvc add data/
            3. dvc push          ← sends to DagsHub
            --- teammate ---
            4. dvc pull
            5. store.import_from_json()

        Returns:
            StorageResult where .data is the output file path
        """
        if output_path is None:
            db_dir = os.path.dirname(os.path.abspath(self.db_path))
            output_path = os.path.join(db_dir, "legal_vault_export.json")

        try:
            docs = search_by_metadata(self.db_path, latest_only=False)
            records = [
                {
                    "id": d.id, "file_url": d.file_url,
                    "sha256_hash": d.sha256_hash, "version": d.version,
                    "is_last": d.is_last, "download_status": d.download_status,
                    "created_at": d.created_at, "title": d.title,
                    "document_type": d.document_type,
                    "issuing_entity": d.issuing_entity,
                    "document_number": d.document_number, "year": d.year,
                    "date": d.date, "language": d.language,
                    "file_path": d.file_path,
                    "file_size_bytes": d.file_size_bytes,
                }
                for d in docs
            ]
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2, ensure_ascii=False)

            return StorageResult(
                success=True,
                message=f"Exported {len(records)} record(s) to '{output_path}'. "
                        "Now run: dvc add data/ && dvc push",
                data=output_path,
            )
        except Exception as e:
            return StorageResult(success=False, message=f"Export failed: {e}")

    def export_to_csv(self, output_path: str = None) -> StorageResult:
        """
        Export the full DB to a CSV file (easy to open in Excel for review).
        Also tracked by DVC alongside the JSON export.

        Returns:
            StorageResult where .data is the output file path
        """
        if output_path is None:
            db_dir = os.path.dirname(os.path.abspath(self.db_path))
            output_path = os.path.join(db_dir, "legal_vault_export.csv")

        try:
            docs = search_by_metadata(self.db_path, latest_only=False)
            if not docs:
                return StorageResult(
                    success=False,
                    message="Nothing to export — database is empty.",
                )
            rows = [
                {
                    "id": d.id, "file_url": d.file_url,
                    "sha256_hash": d.sha256_hash, "version": d.version,
                    "is_last": int(d.is_last),
                    "download_status": d.download_status, "created_at": d.created_at,
                    "title": d.title, "document_type": d.document_type,
                    "issuing_entity": d.issuing_entity,
                    "document_number": d.document_number, "year": d.year,
                    "date": d.date, "language": d.language,
                    "file_path": d.file_path, "file_size_bytes": d.file_size_bytes,
                }
                for d in docs
            ]
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

            return StorageResult(
                success=True,
                message=f"Exported {len(rows)} record(s) to CSV: '{output_path}'.",
                data=output_path,
            )
        except Exception as e:
            return StorageResult(success=False, message=f"CSV export failed: {e}")

    def import_from_json(self, json_path: str = None) -> StorageResult:
        """
        Import records from a JSON export file.
        Used after 'dvc pull' to sync the shared metadata into your local DB.
        Safe to run multiple times — existing records are skipped.

        Returns:
            StorageResult where .data is {"inserted": int, "skipped": int}
        """
        if json_path is None:
            db_dir = os.path.dirname(os.path.abspath(self.db_path))
            json_path = os.path.join(db_dir, "legal_vault_export.json")

        if not os.path.exists(json_path):
            return StorageResult(
                success=False,
                message=f"File not found: '{json_path}'. Run 'dvc pull' first.",
            )
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                records = json.load(f)

            inserted = skipped = 0
            with sqlite3.connect(self.db_path) as conn:
                for rec in records:
                    exists = conn.execute(
                        "SELECT 1 FROM documents WHERE id=?", (rec["id"],)
                    ).fetchone()
                    if exists:
                        skipped += 1
                        continue
                    conn.execute(
                        """
                        INSERT INTO documents (
                            id, file_url, sha256_hash, version, is_last,
                            download_status, created_at,
                            title, document_type, issuing_entity, document_number,
                            year, date, language, file_path, file_size_bytes
                        ) VALUES (
                            :id, :file_url, :sha256_hash, :version, :is_last,
                            :download_status, :created_at,
                            :title, :document_type, :issuing_entity, :document_number,
                            :year, :date, :language, :file_path, :file_size_bytes
                        )
                        """,
                        rec,
                    )
                    inserted += 1
                conn.commit()

            return StorageResult(
                success=True,
                message=f"Import complete — {inserted} inserted, {skipped} already existed.",
                data={"inserted": inserted, "skipped": skipped},
            )
        except json.JSONDecodeError as e:
            return StorageResult(success=False, message=f"Invalid JSON: {e}")
        except Exception as e:
            return StorageResult(success=False, message=f"Import failed: {e}")

    # =======================================================================
    # Internal helpers
    # =======================================================================

    def _promote_previous_version(self, file_url: str) -> None:
        """After deleting the latest version, promote the next newest to is_last=1."""
        # Re-query AFTER the delete so we only see remaining versions
        remaining = get_all_versions_by_url(self.db_path, file_url)
        if not remaining:
            return
        # Check if any version is already marked is_last (shouldn't be, but safe)
        if any(d.is_last for d in remaining):
            return
        newest = max(remaining, key=lambda d: d.version)
        update_document_file_info(self.db_path, newest.id, {"is_last": 1})

    def save_documents_to_db(db_path: str, docs_list: list[StoredDocument]) -> BatchStorageResult:
        """
        Abstracted function to save metadata.
        1. Ensures DB is ready.
        2. Executes the batch insert.
        3. Returns the result dataclass.
        """
        init_db(db_path)
        
        result = insert_documents_batch(db_path, docs_list)
        
        return result
    
    def sync_to_dagshub(self, local_pdf_path: str, file_url: str = None) -> bool:
        """
        Orchestrates the movement of a local file into the DVC vault and 
        pushes the changes to DagsHub. Updates the metadata database upon success.
        
        Args:
            local_pdf_path (str): Path to the local PDF file to sync
            file_url (str, optional): Document URL for database lookup. If provided,
                                     the document status will be marked as 'uploaded'
                                     after successful sync.
        
        Returns:
            bool: True if sync and (optionally) database update succeeded, False otherwise
        
        Database Integration:
            - If file_url is provided, searches for latest document by URL
            - Updates download_status to 'uploaded' upon successful dvc push
            - If document not found by URL, warns but returns True (file was synced)
        """
        if not os.path.exists(local_pdf_path):
            print(f"Error: File not found at {local_pdf_path}")
            return False

        # Get file name and define the destination inside the project
        file_name = os.path.basename(local_pdf_path)
        final_path = os.path.join(self.vault_path, file_name)
        os.makedirs(self.vault_path, exist_ok=True)

        try:
            # 1. Copy the file to the DVC-tracked folder
            shutil.copy2(local_pdf_path, final_path)
            print(f"File moved to vault: {final_path}")

            # 2. Add file to DVC tracking
            subprocess.run(["dvc", "add", final_path], check=True)

            # 3. Stage the .dvc pointer file for Git
            dvc_pointer = f"{final_path}.dvc"
            subprocess.run(["git", "add", dvc_pointer], check=True)

            # 4. Commit the pointer file to Git history
            commit_message = f"DVC: Track new document {file_name}"
            subprocess.run(["git", "commit", "-m", commit_message], check=True)

            # 5. Push the actual heavy file to DagsHub remote storage
            subprocess.run(["dvc", "push"], check=True)
            print(f"Successfully synced {file_name} to DagsHub storage.")

            # 6. Update database metadata upon successful push
            if file_url:
                try:
                    # Find the document by URL and mark as uploaded
                    doc = get_latest_by_url(self.db_path, file_url)
                    if doc:
                        update_result = update_document_file_info(
                            self.db_path,
                            doc.id,
                            {"download_status": "uploaded", "file_path": final_path}
                        )
                        if update_result:
                            print(f"✓ Database updated: document {doc.id} marked as 'uploaded'")
                        else:
                            print(f"⚠ Warning: Document {doc.id} not updated in DB (unexpected)")
                    else:
                        print(f"⚠ Warning: Document with URL '{file_url}' not found in DB. "
                              f"File synced to DagsHub but DB not updated.")
                except Exception as db_error:
                    print(f"⚠ Warning: Database update failed: {db_error}. "
                          f"File was synced to DagsHub but status not recorded.")
            
            return True

        except subprocess.CalledProcessError as e:
            print(f"CLI Error during DagsHub sync: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error during sync: {e}")
            return False
        
    def get_latest_document_by_url(self, url: str) -> Optional[StoredDocument]:

        query = "SELECT * FROM metadata WHERE file_url = ? AND is_last = 1"
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query, (url,))
                row = cursor.fetchone()
                
                if row:
                    return StoredDocument(**dict(row))
                return None
        except Exception as e:
            print(f"Error: {e}")
            return None        