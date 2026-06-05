import json
import logging
import os
import sys

# Ensure project root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

# pyrefly: ignore [missing-import]
from src.corporate_processor.chunkers.chunk_orchestrator import ChunkOrchestrator

class RealDataPipeline:
    """
    A pipeline wrapper that reads real files from your disk.
    """
    def __init__(self, text_path: str, json_path: str):
        self.text_path = text_path
        self.json_path = json_path

    def _execute_extraction_layer(self, pdf_path: str, doc_id: str) -> str:
        with open(self.text_path, 'r', encoding='utf-8') as f:
            return f.read()

    def _execute_chunking_layer(self, full_text: str, doc_id: str) -> list:
        # Instead of loading the metadata JSON (which is a dict, causing the 'str' error),
        # we mock 2 chunks using the first 500 characters of the real text.
        # This prevents sending 100+ chunks to Ollama which would take hours!
        text_preview = full_text[:500] if len(full_text) > 500 else full_text
        return [
            {"chunk_index": 0, "content": text_preview[:250]},
            {"chunk_index": 1, "content": text_preview[250:]}
        ]

def run_test_with_real_files():
    # Configure logging
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    # Define file paths
    text_path = r"data/text/2016_580ab4.txt"
    json_path = r"data/metadata/2016_580ab4.json"
    
    # Check if files exist
    if not os.path.exists(text_path) or not os.path.exists(json_path):
        print(f"[!] Error: Files not found. Please check paths:")
        print(f"Text: {os.path.abspath(text_path)}")
        print(f"JSON: {os.path.abspath(json_path)}")
        return

    # Initialize components
    pipeline = RealDataPipeline(text_path, json_path)
    orchestrator = ChunkOrchestrator(pipeline=pipeline)
    
    print(f"\n{'='*20} TESTING WITH REAL FILES {'='*20}")
    
    # Run linear pipeline — all chunks are automatically refined
    print("\n[+] Running Orchestrator (linear refinement for all chunks)...")
    final_result = orchestrator.run("dummy.pdf", "2016_580ab4")
    
    if final_result:
        print(f"[+] Processing successful. Total chunks: {len(final_result)}")
        # Print the first refined chunk to verify
        print("\n--- Sample Refined Chunk ---")
        print(json.dumps(final_result[0], indent=4, ensure_ascii=False))
    else:
        print("[!] Processing returned no data.")

if __name__ == "__main__":
    run_test_with_real_files()