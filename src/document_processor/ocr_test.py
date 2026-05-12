import os
import sys

# Add the project root to sys.path to resolve 'src' correctly
# This ensures that 'src' is discoverable regardless of where the script is run
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.metadata_manager.metadata_store import MetadataStore
from src.document_processor.pipeline_manager import OCRPipeline 

def main():
    # Database path relative to the project root
    db_path = "data/legal_vault.db"
    
    # 1. Initialize MetadataStore
    if not os.path.exists(db_path):
        print(f"[!] Error: Database not found at {db_path}. Please ensure the 'data' folder exists.")
        return
        
    db = MetadataStore(db_path)
    
    print("="*50)
    print(" FCC Regulatory Compliance - Full System Test")
    print("="*50)
    
    # 2. STEP 1: Full Reset
    # This wipes 'document_chunks' and sets ALL 9 documents to 'pending'
    print("[*] Phase 1: Resetting Database for a clean run...")
    reset_result = db.reset_all_chunks()
    
    if reset_result.success:
        print(f"[OK] {reset_result.message}")
    else:
        print(f"[!] Reset failed: {reset_result.message}")
        return

    # 3. STEP 2: Initialize the Pipeline Manager
    manager = OCRPipeline(metadata_store=db)
    
    print("\n" + "="*50)
    print("[*] Phase 2: Processing All Documents in the Queue")
    print("="*50)
    
    try:
        # 4. STEP 3: Batch Processing
        # The manager will now iterate through all 'pending' documents (1 to 9)
        manager.process_pending_queue()
        
        print("\n" + "="*50)
        print("✅ SUCCESS: All documents processed successfully!")
        print("You can now inspect 'document_chunks' in the database.")
        print("="*50)
        
    except Exception as e:
        print(f"\n[!] Critical Error during batch execution: {str(e)}")

if __name__ == "__main__":
    main()