import hashlib
from typing import List, Dict, Any, Optional
from .ocr_engine import DocumentProcessor
from .semantic_hasher import SemanticHasher
from .diff_engine import DiffEngine # --- NEW ---
import arabic_reshaper
from bidi.algorithm import get_display
class OCRPipeline:
    """
    Orchestrates the entire OCR process by coordinating between Layer 1, Layer 2, 
    Layer 3 (Diff), and the MetadataStore for persistence and versioning.
    """

    def __init__(self, metadata_store: Any, lang: str = 'ar') -> None:
        self.store = metadata_store
        self.processor = DocumentProcessor(lang=lang)
        self.hasher = SemanticHasher()
        self.diff_engine = DiffEngine() # --- NEW ---
    
    def fix_arabic_text(self,text):
        # 1. Reshape characters (fixing letters connections)
        reshaped_text = arabic_reshaper.reshape(text)
        # 2. Re-order for correct display (Right-to-Left)
        bidi_text = get_display(reshaped_text)
        return bidi_text

    def run(self, pdf_path: str, doc_id: int) -> bool:
            """
            Executes the full pipeline for a specific document version.
            Integrates Smart Chunking to group raw lines into semantic blocks for better RAG performance.
            
            Args:
                pdf_path (str): The physical path to the PDF file.
                doc_id (int): The unique identifier of the document in the metadata store.
                
            Returns:
                bool: True if processing and persistence succeeded, False otherwise.
            """
            from datetime import datetime
            try:
                # 0. Preparation: Initialize status and fetch context
                self.store.update_ocr_status(doc_id, "processing")
                base_chunks = self.store.get_latest_chunks(doc_id)
                next_ver = self.store.get_next_version_number(doc_id)
                created_at = datetime.now().isoformat()
                
                print(f"[*] Starting Pipeline for Doc ID {doc_id} (Target Version: {next_ver})")

                # 1. Layer 1: Raw Extraction (Optical Character Recognition)
                # Extracts individual lines/boxes from the PDF
                raw_lines = self.processor.process_layer_one(pdf_path, doc_id)
                
                if not raw_lines:
                    print(f"[!] No content extracted for Doc ID {doc_id}.")
                    return False

                # --- SMART CHUNKING LOGIC ---
                # Grouping raw lines into larger semantic blocks to preserve context (e.g., Article Title + Content)
                # This ensures the LLM receives meaningful paragraphs rather than fragmented lines.
                cleaned_lines = [line['content'].strip() for line in raw_lines if len(line['content'].strip()) > 1]
                full_text = " ".join(cleaned_lines)
                if len(full_text) < 10:
                    print(f"[!] Warning: Very little text extracted for Doc ID {doc_id}")

                def create_semantic_blocks(text, chunk_size=600, overlap=100):
                    if len(text) <= chunk_size:
                        return [{
                            'doc_id': doc_id,
                            'chunk_index': 0,
                            'content': text,
                            'metadata': {'type': 'full_page_block'}
                        }]
                    
                    blocks = []
                    for idx, i in enumerate(range(0, len(text), chunk_size - overlap)):
                        chunk_content = text[i : i + chunk_size]
                        if len(chunk_content) < 50 and len(blocks) > 0:
                            blocks[-1]['content'] += " " + chunk_content
                        else:
                            blocks.append({
                                'doc_id': doc_id,
                                'chunk_index': idx,
                                'content': chunk_content,
                                'metadata': {'type': 'semantic_block'}
                            })
                    return blocks

                # Convert raw lines into substantial blocks (1000 characters each with 200 overlap)
                smart_chunks = create_semantic_blocks(full_text)
                
                # 2. Layer 2: Normalization & Semantic Hashing
                # Hashes are now generated for full paragraphs, making Diff analysis more meaningful.
                refined_chunks = self.hasher.process_layer_two(smart_chunks)
                
                # Enrich chunks with versioning metadata
                for c in refined_chunks:
                    c['version'] = next_ver
                    c['created_at'] = created_at
                    c['is_active'] = 1

                # 3. Layer 3: Diff Analysis (Version Comparison)
                # Compares previous version blocks with the new ones to detect regulatory changes.
                if base_chunks:
                    print(f"[*] Comparing with {len(base_chunks)} previous semantic blocks...")
                    final_chunks = self.diff_engine.compare_documents(base_chunks, refined_chunks)
                else:
                    # Initial upload logic: all blocks are marked as 'added'
                    for c in refined_chunks:
                        c['change_type'] = 'added'
                    final_chunks = refined_chunks

                # 4. Persistence: Database Synchronization
                # Archive existing active version and save the new versioned blocks.
                print(f"[*] Synchronizing database for Doc ID {doc_id}...")
                self.store.archive_old_chunks(doc_id)
                
                save_result = self.store.save_chunks(final_chunks)

                if save_result.success:
                    # 5. Final Status Update and Metrics Logging
                    self.store.update_ocr_status(doc_id, "completed")
                    
                    score = self.diff_engine.get_similarity_score(base_chunks, final_chunks)
                    print(f"[+] Pipeline successful. Similarity score: {score}%")
                    return True
                else:
                    print(f"[!] Storage failed: {save_result.message}")
                    self.store.update_ocr_status(doc_id, "failed")
                    return False

            except Exception as e:
                # Global error handling to ensure status is updated even on crash
                self.store.update_ocr_status(doc_id, "failed")
                print(f"[!] Pipeline Error: {str(e)}")
                return False

    def process_pending_queue(self) -> None:
        """
        Fetches all documents with 'pending' status from the database 
        and executes the pipeline for each.
        """
        # 1. Get list of pending documents (Make sure this method exists in MetadataStore)
        pending_docs = self.store.get_pending_documents()
        
        if not pending_docs:
            print("[*] No pending documents found in the queue.")
            return

        print(f"[*] Found {len(pending_docs)} pending documents. Starting batch processing...")

        for doc in pending_docs:
            doc_id = doc['id']
            pdf_path = doc['file_path'] # Adjust key name based on your schema
            
            print(f"\n[>] Processing: {pdf_path} (ID: {doc_id})")
            
            # Execute the run method we built together
            success = self.run(pdf_path, doc_id)
            
            if success:
                print(f"[SUCCESS] Document {doc_id} is now indexed.")
            else:
                print(f"[FAILED] Could not process document {doc_id}.")        