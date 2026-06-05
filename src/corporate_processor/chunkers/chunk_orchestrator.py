import logging
from typing import Any, Dict, List, Optional
from src.document_processor.pipeline_manager import OCRPipeline
from src.corporate_processor.chunkers.corporate_chunker import CorporateChunker

logger = logging.getLogger(__name__)

class ChunkOrchestrator:
    """
    Consolidated Orchestrator handling extraction, chunking, and LLM refinement logic.
    Provides a clean, single-entry interface without unnecessary abstractions.
    """
    def __init__(self, pipeline: OCRPipeline):
        self.pipeline = pipeline
        self.chunker = CorporateChunker()

    def run(self, pdf_path: str, doc_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        Executes the full extraction, chunking, and refinement flow.
        The pipeline is strictly linear: every chunk is passed to the CorporateChunker.
        """
        logger.info(f"[*] ChunkOrchestrator: Processing document {doc_id}...")
        
        # 1. Extraction (via OCRPipeline)
        full_text = self.pipeline._execute_extraction_layer(pdf_path, doc_id)
        if not full_text:
            logger.warning(f"[!] Extraction failed or returned empty for {doc_id}.")
            return None
            
        # 2. Chunking (via OCRPipeline)
        raw_chunks = self.pipeline._execute_chunking_layer(full_text, doc_id)
        if not raw_chunks:
            logger.warning(f"[!] Chunking produced no output for {doc_id}.")
            return None

        # 3. Refinement (via CorporateChunker)
        logger.info(f"[*] Passing {len(raw_chunks)} chunks to CorporateChunker for refinement.")
        for chunk in raw_chunks:
            original_text = chunk.get("content", "")
            if original_text:
                try:
                    refined_text = self.chunker.refine_chunk(original_text)
                    if refined_text:
                        chunk["content"] = refined_text
                except Exception as e:
                    logger.error(f"[!] Refinement failed for chunk in {doc_id}. Falling back to raw text. Error: {e}")

        logger.info(f"[+] ChunkOrchestrator: Processing complete for {doc_id}.")
        return raw_chunks


if __name__ == "__main__":
    # -------------------------------------------------------------------------
    # Test Script: Mocks the pipeline and verifies the flow directly
    # -------------------------------------------------------------------------
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    class MockPipeline:
        """Simulates OCRPipeline without DB or actual OCR overhead."""
        def __init__(self, simulated_chunks: List[Dict[str, Any]]):
            self.simulated_chunks = simulated_chunks

        def _execute_extraction_layer(self, pdf_path: str, doc_id: str) -> str:
            return "Simulated text for the full document."

        def _execute_chunking_layer(self, full_text: str, doc_id: str) -> List[Dict[str, Any]]:
            return self.simulated_chunks

    print("=" * 60)
    print("RUNNING CHUNK ORCHESTRATOR TESTS")
    print("=" * 60)

    # Simulated Data
    simulated_chunks_data = [
        {"chunk_index": 0, "content": "This is raw unrefined chunk 1."},
        {"chunk_index": 1, "content": "This is raw unrefined chunk 2 with 500 USD."}
    ]

    mock_pipeline = MockPipeline(simulated_chunks_data)
    orchestrator = ChunkOrchestrator(pipeline=mock_pipeline)

    # --- Test: Linear Flow ---
    print("\n--- TEST CASE: Linear Flow ---")
    print("Note: If Ollama is running, it will refine. Otherwise, it gracefully falls back.")
    chunks = orchestrator.run("dummy.pdf", "DOC_01")
    if chunks:
        for chunk in chunks:
            print(f"  Result: {chunk['content']}")

    print("\n" + "=" * 60)
    print("TESTS COMPLETED")
    print("=" * 60)
