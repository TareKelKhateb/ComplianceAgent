import os
import yaml
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Core component imports
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
        raise ValueError(f"Unknown extractor_type '{extractor_type}'. Valid options: 'mistral', 'easyocr'.")

def _build_chunker(cfg: Dict[str, Any]) -> BaseChunker:
    chunker_type = cfg.get("chunker_type", "overlapping").lower()

    if chunker_type == "semantic":
        print("[*] Factory: Using SemanticChunker (article-header split)")
        return SemanticChunker()

    elif chunker_type == "overlapping":
        oc = cfg.get("overlapping_chunker", {})
        print(f"[*] Factory: Using OverlappingChunker (size={oc.get('chunk_size', 600)}, overlap={oc.get('overlap', 100)})")
        return OverlappingChunker(
            chunk_size=oc.get('chunk_size', 600),
            overlap=oc.get('overlap', 100),
            min_chunk_length=oc.get('min_chunk_length', 50),
        )

    else:
        raise ValueError(f"Unknown chunker_type '{chunker_type}'. Valid options: 'semantic', 'overlapping'.")

# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

class OCRPipeline:
    """
    Orchestrates the full document processing pipeline.
    Uses the Strategy Pattern to dynamically load extractors and chunkers.
    Logic is split into modular layers for clarity and maintainability.
    """

    def __init__(
        self,
        metadata_store: Any,
        config_path: Optional[str] = None,
        extractor: Optional[BaseExtractor] = None,
        chunker: Optional[BaseChunker] = None,
    ) -> None:
        self.store = metadata_store
        self._cfg = _load_pipeline_config(config_path)

        # Strategy injection: explicit > config-driven
        self.extractor: BaseExtractor = extractor or _build_extractor(self._cfg)
        self.chunker: BaseChunker = chunker or _build_chunker(self._cfg)

        self.hasher = SemanticHasher()
        self.diff_engine = DiffEngine()

        self._save_full_text: bool = self._cfg.get("save_full_text", True)
        self._full_text_dir: str = self._cfg.get("full_text_output_dir", "output_markdown")

    def run(self, pdf_path: str, doc_id: str) -> bool:
        """
        Execute the full processing pipeline for one document version.
        """
        try:
            # 0. Preparation
            base_chunks, next_ver, created_at = self._prepare_pipeline_session(doc_id)
            print(f"\n[>] Pipeline starting — Doc ID: {doc_id} | Target version: {next_ver}")

            # 1. Layer 1 — Extraction
            full_text = self._execute_extraction_layer(pdf_path, doc_id)
            if not full_text:
                return False

            # 2. Chunking
            raw_chunks = self._execute_chunking_layer(full_text, doc_id)
            if not raw_chunks:
                return False

            # 3. Layer 2 — Normalization & Semantic Hashing
            refined_chunks = self._execute_semantic_layer(raw_chunks, next_ver, created_at)

            # 4. Layer 3 — Diff Analysis
            final_chunks = self._execute_diff_layer(base_chunks, refined_chunks)

            # 5. Persistence
            return self._finalize_pipeline_results(doc_id, final_chunks, base_chunks)

        except Exception as exc:
            self._handle_pipeline_failure(doc_id, exc)
            raise




    # ------------------------------------------------------------------
    # Private Implementation Methods
    # ------------------------------------------------------------------

    def _prepare_pipeline_session(self, doc_id: str):
        """Initializes the processing session by fetching metadata."""
        self.store.update_ocr_status(doc_id, "processing")
        base_chunks = self.store.get_latest_chunks(doc_id)
        next_ver = self.store.get_next_version_number(doc_id)
        created_at = datetime.now().isoformat()
        return base_chunks, next_ver, created_at

    def _execute_extraction_layer(self, pdf_path: str, doc_id: str) -> Optional[str]:
        """Handles Layer 1: PDF Extraction."""
        print(f"[*] Layer 1: Extracting text using {type(self.extractor).__name__}...")
        full_text: str = self.extractor.extract_text(pdf_path)

        if not full_text or len(full_text.strip()) < 10:
            print(f"[!] No content extracted for Doc ID {doc_id}. Aborting.")
            self.store.update_ocr_status(doc_id, "failed")
            return None

        if self._save_full_text:
            self._persist_full_text(full_text, pdf_path)
            
        return full_text

    def _execute_chunking_layer(self, full_text: str, doc_id: str) -> Optional[List[Dict[str, Any]]]:
        """Splits text into chunks."""
        print(f"[*] Chunking: Using {type(self.chunker).__name__}...")
        raw_chunks = self.chunker.create_chunks(full_text, doc_id)

        if not raw_chunks:
            print(f"[!] Chunker produced no chunks for Doc ID {doc_id}. Aborting.")
            self.store.update_ocr_status(doc_id, "failed")
            return None

        return raw_chunks

    def _execute_semantic_layer(self, raw_chunks: List[Dict[str, Any]], next_ver: int, created_at: str) -> List[Dict[str, Any]]:
        """Handles Layer 2: Normalization and Hashing."""
        refined_chunks = self.hasher.process_layer_two(raw_chunks)
        for chunk in refined_chunks:
            chunk.update({
                "version": next_ver,
                "created_at": created_at,
                "is_active": 1
            })
        return refined_chunks

    def _execute_diff_layer(self, base_chunks: List[Dict[str, Any]], refined_chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Handles Layer 3: Version Comparison."""
        if not base_chunks:
            print("[*] Initial upload detected. Marking all as 'added'.")
            for chunk in refined_chunks:
                chunk["change_type"] = "added"
            return refined_chunks

        print(f"[*] Layer 3: Comparing with {len(base_chunks)} previous chunks…")
        return self.diff_engine.compare_documents(base_chunks, refined_chunks)

    def _finalize_pipeline_results(self, doc_id: str, final_chunks: List[Dict[str, Any]], base_chunks: List[Dict[str, Any]]) -> bool:
        """Saves data to DB and updates status."""
        print(f"[*] Synchronizing DB for Doc ID {doc_id}…")
        self.store.archive_old_chunks(doc_id)
        save_result = self.store.save_chunks(final_chunks)

        if save_result.success:
            self.store.update_ocr_status(doc_id, "completed")
            score = self.diff_engine.get_similarity_score(base_chunks, final_chunks)
            print(f"[+] Pipeline complete — {len(final_chunks)} chunks saved | Similarity: {score}%")
            return True
        else:
            print(f"[!] Storage failed: {save_result.message}")
            self.store.update_ocr_status(doc_id, "failed")
            return False

    def _handle_pipeline_failure(self, doc_id: str, exc: Exception):
        """Logs errors and updates DB status."""
        print(f"[!] Pipeline error for Doc ID {doc_id}: {exc}")
        self.store.update_ocr_status(doc_id, "failed")

    def _persist_full_text(self, full_text: str, pdf_path: str) -> str:
        """Save the full Markdown string to a file in ``_full_text_dir``."""
        os.makedirs(self._full_text_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        md_path = os.path.join(self._full_text_dir, f"{base_name}.md")

        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write(full_text)

        print(f"[+] Full text saved: {md_path}")
        return md_path

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    def process_pending_queue(self) -> None:
        """
        Fetch all documents with status 'pending' and run sequentially.
        """
        pending_docs = self.store.get_pending_documents()
        if not pending_docs:
            print("[*] No pending documents found in the queue.")
            return

        print(f"[*] Found {len(pending_docs)} pending document(s). Starting batch…")
        for doc in pending_docs:
            doc_id, pdf_path = doc["id"], doc["file_path"]
            print(f"\n[>] Processing: {pdf_path} (ID: {doc_id})")
            success = self.run(pdf_path, doc_id)
            status = "SUCCESS" if success else "FAILED"
            print(f"[{status}] Document {doc_id} processed.")
