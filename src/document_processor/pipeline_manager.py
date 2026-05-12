"""
pipeline_manager.py
-------------------
Orchestrates the document processing pipeline using the Strategy Pattern.

The concrete extractor and chunker are selected at runtime from
``config/document_processor_config.yaml``, so switching engines requires
only a YAML edit — no code change.

Flow:
  1. Load config → instantiate Extractor & Chunker via factory helpers.
  2. Run Extractor  → full Markdown string.
  3. Persist full text (optional, config-driven).
  4. Run Chunker    → list of chunk dicts.
  5. Run SemanticHasher (Layer 2).
  6. Run DiffEngine (Layer 3).
  7. Persist chunks to the database.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .extractors.base_extractor import BaseExtractor
from .extractors.easyocr_extractor import EasyOcrExtractor
from .extractors.mistral_extractor import MistralExtractor
from .chunkers.base_chunker import BaseChunker
from .chunkers.overlapping_chunker import OverlappingChunker
from .chunkers.semantic_chunker import SemanticChunker
from .semantic_hasher import SemanticHasher
from .diff_engine import DiffEngine


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "document_processor_config.yaml"


def _load_pipeline_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load and return the ``processing_pipeline`` section from the YAML config.

    Falls back gracefully to sensible defaults if the file is missing.
    """
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    if not path.exists():
        print(f"[!] Config not found at '{path}'. Using built-in defaults.")
        return {
            "extractor_type": "easyocr",
            "chunker_type": "overlapping",
            "save_full_text": False,
            "full_text_output_dir": "output_markdown",
            "mistral": {"model": "mistral-ocr-latest", "table_format": "markdown"},
            "easyocr": {
                "languages": ["ar", "en"],
                "gpu": True,
                "poppler_path": None,
                "dpi": 300,
            },
            "overlapping_chunker": {
                "chunk_size": 600,
                "overlap": 100,
                "min_chunk_length": 50,
            },
        }

    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    return raw.get("processing_pipeline", {})


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _build_extractor(cfg: Dict[str, Any]) -> BaseExtractor:
    extractor_type = cfg.get("extractor_type", "easyocr").lower()

    if extractor_type == "mistral":
        m = cfg.get("mistral", {})
        print(f"[*] Factory: Using MistralExtractor (model={m.get('model', 'mistral-ocr-latest')})")
        return MistralExtractor(
            model=m.get("model", "mistral-ocr-latest"),
            table_format=m.get("table_format", "markdown"),
        )

    elif extractor_type == "easyocr":
        e = cfg.get("easyocr", {})
        print(f"[*] Factory: Using EasyOcrExtractor (gpu={e.get('gpu', True)})")
        return EasyOcrExtractor(
            languages=e.get("languages", ["ar", "en"]),
            gpu=e.get("gpu", True),
            poppler_path=e.get("poppler_path"),
            dpi=e.get("dpi", 300),
        )

    else:
        raise ValueError(
            f"Unknown extractor_type '{extractor_type}'. "
            "Valid options: 'mistral', 'easyocr'."
        )


def _build_chunker(cfg: Dict[str, Any]) -> BaseChunker:
    chunker_type = cfg.get("chunker_type", "overlapping").lower()

    if chunker_type == "semantic":
        print("[*] Factory: Using SemanticChunker (article-header split)")
        return SemanticChunker()

    elif chunker_type == "overlapping":
        oc = cfg.get("overlapping_chunker", {})
        print(
            f"[*] Factory: Using OverlappingChunker "
            f"(size={oc.get('chunk_size', 600)}, overlap={oc.get('overlap', 100)})"
        )
        return OverlappingChunker(
            chunk_size=oc.get("chunk_size", 600),
            overlap=oc.get("overlap", 100),
            min_chunk_length=oc.get("min_chunk_length", 50),
        )

    else:
        raise ValueError(
            f"Unknown chunker_type '{chunker_type}'. "
            "Valid options: 'semantic', 'overlapping'."
        )


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

class OCRPipeline:
    """
    Orchestrates the full document processing pipeline.

    Strategies (extractor + chunker) are injected at construction time
    based on ``config/document_processor_config.yaml``.
    """

    def __init__(
        self,
        metadata_store: Any,
        config_path: Optional[str] = None,
        extractor: Optional[BaseExtractor] = None,
        chunker: Optional[BaseChunker] = None,
    ) -> None:
        """
        Args:
            metadata_store: Database abstraction layer (provides get_latest_chunks,
                            save_chunks, archive_old_chunks, etc.).
            config_path (str | None): Override path to the YAML config file.
                                      Defaults to ``config/document_processor_config.yaml``.
            extractor (BaseExtractor | None): Inject a custom extractor directly,
                                              bypassing config (useful for testing).
            chunker (BaseChunker | None):     Inject a custom chunker directly,
                                              bypassing config (useful for testing).
        """
        self.store = metadata_store
        self._cfg = _load_pipeline_config(config_path)

        # Strategy injection: explicit > config-driven
        self.extractor: BaseExtractor = extractor or _build_extractor(self._cfg)
        self.chunker: BaseChunker = chunker or _build_chunker(self._cfg)

        self.hasher = SemanticHasher()
        self.diff_engine = DiffEngine()

        self._save_full_text: bool = self._cfg.get("save_full_text", True)
        self._full_text_dir: str = self._cfg.get("full_text_output_dir", "output_markdown")

    # ------------------------------------------------------------------
    # Full-text persistence
    # ------------------------------------------------------------------

    def _persist_full_text(self, full_text: str, pdf_path: str) -> str:
        """
        Save the full Markdown string to a .md file in ``_full_text_dir``.

        Returns the path of the saved file.
        """
        os.makedirs(self._full_text_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        md_path = os.path.join(self._full_text_dir, f"{base_name}.md")

        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write(full_text)

        print(f"[+] Full text saved: {md_path}")
        return md_path

    # ------------------------------------------------------------------
    # Primary run method
    # ------------------------------------------------------------------

    def run(self, pdf_path: str, doc_id: int) -> bool:
        """
        Execute the full processing pipeline for one document version.

        Steps
        -----
        1. Update DB status → "processing".
        2. Extract full Markdown text via the configured Extractor.
        3. (Optional) Persist the full Markdown file to disk.
        4. Chunk the Markdown via the configured Chunker.
        5. Normalize + hash chunks (SemanticHasher / Layer 2).
        6. Compare with previous version (DiffEngine / Layer 3).
        7. Archive old chunks and persist new ones to the DB.
        8. Update DB status → "completed" or "failed".

        Args:
            pdf_path (str): Path to the input PDF.
            doc_id (int):   Document identifier in the metadata store.

        Returns:
            bool: True on success, False on failure.
        """
        try:
            # 0. Preparation
            self.store.update_ocr_status(doc_id, "processing")
            base_chunks = self.store.get_latest_chunks(doc_id)
            next_ver = self.store.get_next_version_number(doc_id)
            created_at = datetime.now().isoformat()

            print(
                f"\n[>] Pipeline starting — Doc ID: {doc_id} | "
                f"Extractor: {type(self.extractor).__name__} | "
                f"Chunker: {type(self.chunker).__name__} | "
                f"Target version: {next_ver}"
            )

            # 1. Layer 1 — Extraction
            full_text: str = self.extractor.extract_text(pdf_path)

            if not full_text or len(full_text.strip()) < 10:
                print(f"[!] No content extracted for Doc ID {doc_id}. Aborting.")
                self.store.update_ocr_status(doc_id, "failed")
                return False

            # 2. (Optional) Persist full Markdown "ground truth"
            if self._save_full_text:
                self._persist_full_text(full_text, pdf_path)

            # 3. Chunking
            raw_chunks: List[Dict[str, Any]] = self.chunker.create_chunks(full_text, doc_id)

            if not raw_chunks:
                print(f"[!] Chunker produced no chunks for Doc ID {doc_id}. Aborting.")
                self.store.update_ocr_status(doc_id, "failed")
                return False

            # 4. Layer 2 — Normalization & Semantic Hashing
            refined_chunks = self.hasher.process_layer_two(raw_chunks)

            # Enrich chunks with versioning metadata
            for chunk in refined_chunks:
                chunk["version"] = next_ver
                chunk["created_at"] = created_at
                chunk["is_active"] = 1

            # 5. Layer 3 — Diff Analysis
            if base_chunks:
                print(f"[*] Comparing with {len(base_chunks)} previous chunks…")
                final_chunks = self.diff_engine.compare_documents(base_chunks, refined_chunks)
            else:
                # First upload: every chunk is brand new
                for chunk in refined_chunks:
                    chunk["change_type"] = "added"
                final_chunks = refined_chunks

            # 6. Persistence — archive previous + save new
            print(f"[*] Synchronising DB for Doc ID {doc_id}…")
            self.store.archive_old_chunks(doc_id)
            save_result = self.store.save_chunks(final_chunks)

            if save_result.success:
                self.store.update_ocr_status(doc_id, "completed")
                score = self.diff_engine.get_similarity_score(base_chunks, final_chunks)
                print(
                    f"[+] Pipeline complete — "
                    f"{len(final_chunks)} chunks saved | "
                    f"Similarity: {score}%"
                )
                return True
            else:
                print(f"[!] Storage failed: {save_result.message}")
                self.store.update_ocr_status(doc_id, "failed")
                return False

        except Exception as exc:
            self.store.update_ocr_status(doc_id, "failed")
            print(f"[!] Pipeline error for Doc ID {doc_id}: {exc}")
            raise

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    def process_pending_queue(self) -> None:
        """
        Fetch all documents with status ``'pending'`` and run the pipeline
        for each one sequentially.
        """
        pending_docs = self.store.get_pending_documents()

        if not pending_docs:
            print("[*] No pending documents found in the queue.")
            return

        print(f"[*] Found {len(pending_docs)} pending document(s). Starting batch…")

        for doc in pending_docs:
            doc_id = doc["id"]
            pdf_path = doc["file_path"]

            print(f"\n[>] Processing: {pdf_path} (ID: {doc_id})")
            success = self.run(pdf_path, doc_id)

            if success:
                print(f"[SUCCESS] Document {doc_id} indexed successfully.")
            else:
                print(f"[FAILED]  Document {doc_id} could not be processed.")