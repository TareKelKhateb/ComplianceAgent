"""
reset_all.py
------------
Utility to wipe both databases clean so you can start from zero:

  1. legal_vault.db  — SQLite (documents, chunks, internal_documents, corporate_chunks)
  2. Chatbot storage — Chroma vector DBs (external_regulations, internal_policies)
                       + the SQLRecordManager cache

Usage:
    python -m src.utils.reset_all          # interactive confirmation
    python -m src.utils.reset_all --force  # skip confirmation
"""

import os
import sys
import shutil
import pathlib
import argparse
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_LEGAL_VAULT_DB = _PROJECT_ROOT / "data" / "legal_vault.db"
_CHATBOT_STORAGE = _PROJECT_ROOT / "src" / "chatbot" / "storage"


def reset_legal_vault() -> None:
    """
    Wipe all tables in legal_vault.db:
      - documents, document_chunks
      - internal_documents, corporate_chunks
    Preserves the schema (tables are truncated, not dropped).
    """
    if not _LEGAL_VAULT_DB.exists():
        print(f"  [SKIP] legal_vault.db not found at {_LEGAL_VAULT_DB}")
        return

    # Use the existing MetadataStore.reset_all_data() which handles this properly
    sys.path.insert(0, str(_PROJECT_ROOT))
    from src.metadata_manager.metadata_store import MetadataStore

    store = MetadataStore(db_path=str(_LEGAL_VAULT_DB))
    result = store.reset_all_data()

    if result.success:
        print(f"  [OK] legal_vault.db reset: {result.message}")
    else:
        print(f"  [FAIL] legal_vault.db reset failed: {result.message}")


def reset_chatbot_vectordb() -> None:
    """
    Wipe the chatbot's Chroma vector databases and record manager cache:
      - src/chatbot/storage/external_regulations/
      - src/chatbot/storage/internal_policies/
      - src/chatbot/storage/record_manager_cache.sql
    """
    if not _CHATBOT_STORAGE.exists():
        print(f"  [SKIP] Chatbot storage not found at {_CHATBOT_STORAGE}")
        return

    targets = [
        _CHATBOT_STORAGE / "external_regulations",
        _CHATBOT_STORAGE / "internal_policies",
        _CHATBOT_STORAGE / "record_manager_cache.sql",
    ]

    for target in targets:
        if target.is_dir():
            shutil.rmtree(target)
            print(f"  [OK] Deleted directory: {target.relative_to(_PROJECT_ROOT)}")
        elif target.is_file():
            target.unlink()
            print(f"  [OK] Deleted file: {target.relative_to(_PROJECT_ROOT)}")
        else:
            print(f"  [SKIP] Not found: {target.relative_to(_PROJECT_ROOT)}")

    # Recreate the storage directory so the chatbot doesn't fail on next startup
    _CHATBOT_STORAGE.mkdir(parents=True, exist_ok=True)
    print("  [OK] Chatbot storage directory recreated (empty)")


def reset_all(force: bool = False) -> None:
    """
    Reset both databases. Asks for confirmation unless force=True.
    """
    print("=" * 60)
    print("  FULL RESET — This will wipe ALL data:")
    print("    1. legal_vault.db (documents + chunks)")
    print("    2. Chatbot vector databases (Chroma + record manager)")
    print("=" * 60)

    if not force:
        answer = input("\n  Are you sure? Type 'yes' to confirm: ").strip().lower()
        if answer != "yes":
            print("  Aborted.")
            return

    print("\n--- Resetting legal_vault.db ---")
    reset_legal_vault()

    print("\n--- Resetting chatbot vector databases ---")
    reset_chatbot_vectordb()

    print("\n" + "=" * 60)
    print("  RESET COMPLETE — both databases are now empty")
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reset all databases to a clean state.")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    reset_all(force=args.force)
