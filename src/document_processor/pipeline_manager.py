import os
import yaml
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

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

        self.task_queue = queue.Queue()

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
                chunk["version"] = 1
            return refined_chunks

        print(f"[*] Layer 3: Comparing with {len(base_chunks)} previous chunks…")
        return self.diff_engine.compare_documents(base_chunks, refined_chunks)

    def _finalize_pipeline_results(self, doc_id: str, final_chunks: List[Dict[str, Any]], base_chunks: List[Dict[str, Any]]) -> bool:
        """Saves data to DB and updates status using an incremental strategy."""
        print(f"[*] Synchronizing DB for Doc ID {doc_id}…")
        
        # 1. Separate chunks into those that need saving and those that are unchanged
        to_save = [c for c in final_chunks if c.get('change_type') != 'unchanged']
        unchanged_ids = {c['chunk_id'] for c in final_chunks if c.get('change_type') == 'unchanged'}
        
        # 2. Archive everything that ISN'T in the unchanged set
        # We'll use a new method or a clever query. 
        # For now, let's just archive the modified/deleted ones explicitly.
        try:
            # Archive all current active chunks for this doc EXCEPT the ones we identified as unchanged
            # This keeps Article 2 'is_active=1' without a new row.
            with self.store._get_connection() as conn:
                # We need to archive chunks that were modified (they are in to_save) 
                # and chunks that were deleted (they are in base_chunks but not in final_chunks)
                for chunk in to_save:
                    # Archive previous version of this specific chunk_id if it exists
                    conn.execute(
                        "UPDATE document_chunks SET is_active = 0 WHERE doc_id = ? AND chunk_id = ? AND is_active = 1",
                        (doc_id, chunk['chunk_id'])
                    )
                
                # Also handle deletions: anything in base_chunks not in final_chunks
                final_ids = {c['chunk_id'] for c in final_chunks}
                for b_chunk in base_chunks:
                    if b_chunk['chunk_id'] not in final_ids:
                        conn.execute(
                            "UPDATE document_chunks SET is_active = 0 WHERE doc_id = ? AND chunk_id = ? AND is_active = 1",
                            (doc_id, b_chunk['chunk_id'])
                        )
                conn.commit()
        except Exception as e:
            print(f"[!] Archiving error: {e}")

        # 3. Save only the new/modified chunks
        if not to_save:
            self.store.update_ocr_status(doc_id, "completed")
            score = self.diff_engine.get_similarity_score(base_chunks, final_chunks)
            print(f"[+] Pipeline complete — 0 new/modified chunks. No changes detected. | Similarity: {score}%")
            return True

        save_result = self.store.save_chunks(to_save)

        if save_result.success:
            self.store.update_ocr_status(doc_id, "completed")
            score = self.diff_engine.get_similarity_score(base_chunks, final_chunks)
            print(f"[+] Pipeline complete — {len(to_save)} new/modified chunks saved | Similarity: {score}%")
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
    # Producer-Consumer Concurrency Methods
    # ------------------------------------------------------------------

    def _run_extraction_only(self, pdf_path: str, doc_id: str) -> None:
        """Producer worker: extracts text and places it in the queue."""
        try:
            self.store.update_ocr_status(doc_id, "processing")
            full_text = self._execute_extraction_layer(pdf_path, doc_id)
            if full_text:
                self.task_queue.put({
                    "doc_id": doc_id,
                    "full_text": full_text
                })
        except Exception as exc:
            self._handle_pipeline_failure(doc_id, exc)

    def _consumer_daemon(self) -> None:
        """Consumer thread: reads text from the queue and processes DB operations sequentially."""
        while True:
            task = self.task_queue.get()
            if task is None:  # Poison pill to shut down
                break
            
            doc_id = task["doc_id"]
            full_text = task["full_text"]
            
            try:
                base_chunks, next_ver, created_at = self._prepare_pipeline_session(doc_id)
                
                raw_chunks = self._execute_chunking_layer(full_text, doc_id)
                if not raw_chunks:
                    continue
                
                refined_chunks = self._execute_semantic_layer(raw_chunks, next_ver, created_at)
                final_chunks = self._execute_diff_layer(base_chunks, refined_chunks)
                
                self._finalize_pipeline_results(doc_id, final_chunks, base_chunks)
            except Exception as exc:
                self._handle_pipeline_failure(doc_id, exc)

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    def process_pending_queue(self, max_workers: Optional[int] = None) -> None:
        """
        Fetch all documents with status 'pending' and run them using a Producer-Consumer architecture.
        """
        if max_workers is None:
            env_val = os.getenv("MAX_WORKERS")
            max_workers = int(env_val) if env_val else 5

        pending_docs = self.store.get_pending_documents()
        if not pending_docs:
            print("[*] No pending documents found in the queue.")
            return

        print(f"[*] Found {len(pending_docs)} pending document(s).")
        self.run_batch(pending_docs, max_workers=max_workers)

    def run_batch(self, documents: List[Dict[str, Any]], max_workers: Optional[int] = None) -> None:
        """
        Process a specific list of documents using the Producer-Consumer architecture.
        OCR is parallelized across workers, while DB insertion is forced to be sequential.
        
        Parameters
        ----------
        documents : List[Dict[str, Any]]
            A list of document dictionaries. Each must contain 'id' and 'file_path'.
        max_workers : int, optional
            Maximum number of concurrent OCR threads.
        """
        if not documents:
            print("[*] No documents provided for batch processing.")
            return

        if max_workers is None:
            env_val = os.getenv("MAX_WORKERS")
            max_workers = int(env_val) if env_val else 5

        print(f"[*] Starting parallel batch processing for {len(documents)} document(s)…")
        
        # 1. Start the Consumer Thread (Daemon)
        consumer_thread = threading.Thread(target=self._consumer_daemon)
        consumer_thread.start()

        # 2. Start the Producers (ThreadPoolExecutor for OCR)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for doc in documents:
                doc_id, pdf_path = doc["id"], doc["file_path"]
                print(f"\n[>] Queuing for Extraction: {pdf_path} (ID: {doc_id})")
                executor.submit(self._run_extraction_only, pdf_path, doc_id)
                
        # 3. All producers finished. Send poison pill to Consumer and wait for it.
        self.task_queue.put(None)
        consumer_thread.join()
        
        print("[+] Batch processing completed.")
