import os
import sys

# Add the project root to sys.path to resolve 'src' correctly
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# pyrefly: ignore [missing-import]
from src.metadata_manager.metadata_store import MetadataStore
# pyrefly: ignore [missing-import]
from src.document_processor.pipeline_manager import OCRPipeline 

def main():
    """
    Test script for the Document Processing Pipeline.
    This script uses 'pipeline_manager.py' (the unified orchestrator).
    """
    # Database path relative to the project root
    db_path = "data/legal_vault.db"
    
    # 1. Initialize MetadataStore
    if not os.path.exists(db_path):
        print(f"[!] Error: Database not found at {db_path}.")
        print("[*] Tip: Make sure you are running this from the project root and 'data/legal_vault.db' exists.")
        return
        
    db = MetadataStore(db_path)
    
    print("="*60)
    print(" FCC Regulatory Compliance - Pipeline Integration Test")
    print(" Using: pipeline_manager.py")
    print("="*60)
    
    # 2. STEP 1: Database Audit/Reset
    # Optionally reset chunks if you want to test from scratch
    user_input = input("[?] Would you like to reset all chunks before starting? (y/N): ").lower()
    if user_input == 'y':
        print("[*] Phase 1: Resetting Database for a clean run...")
        reset_result = db.reset_all_chunks()
        if reset_result.success:
            print(f"[OK] {reset_result.message}")
        else:
            print(f"[!] Reset failed: {reset_result.message}")
            return
    else:
        print("[*] Phase 1: Skipping reset. Processing only 'pending' documents.")

    # 3. STEP 2: Initialize the Unified Pipeline Manager
    try:
        manager = OCRPipeline(metadata_store=db)
    except Exception as e:
        print(f"[!] Error initializing pipeline: {e}")
        return
    
    print("\n" + "="*60)
    print("[*] Phase 2: Processing Documents in the Queue")
    print("="*60)
    
    try:
        # 4. STEP 3: Batch Processing
        # Fetches all documents with 'pending' status and processes them sequentially
        manager.process_pending_queue()
        
        print("\n" + "="*60)
        print("SUCCESS: Testing Complete!")
        print("Final chunks have been synchronized with 'document_chunks' table.")
        print("="*60)
        
    except Exception as e:
        print(f"\n[!] Critical Error during execution: {str(e)}")

if __name__ == "__main__":
    main()