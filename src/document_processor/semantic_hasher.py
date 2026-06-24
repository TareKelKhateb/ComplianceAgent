import hashlib
import re
from typing import List, Dict, Any
from .chunk_id_generator import LegalArticleParser

class SemanticHasher:
    """
    Layer 2: Handles Arabic-specific text normalization and semantic hashing.
    Ensures that orthographic variations (like Alef shapes) don't trigger false diffs.
    """

    def __init__(self) -> None:

        self.article_parser: LegalArticleParser = LegalArticleParser()

    def process_layer_two(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            """
            Refines a batch of raw chunks by normalizing text, extracting Arabic legal article 
            numbers to build deterministic IDs, and calculating robust SHA-256 hashes.

            Args:
                chunks (List[Dict[str, Any]]): The list of raw chunk dictionaries from Layer 1.

            Returns:
                List[Dict[str, Any]]: The mutation-safe, enriched chunks ready for Diff Analysis.
            """
            print(f"[*] Layer 2: Normalizing and assigning IDs to {len(chunks)} chunks...")
            
            # 3. REPLACE YOUR ENTIRE process_layer_two LOOP WITH THIS
            for chunk in chunks:
                # Identity Check (Table vs Text)
                is_table: bool = chunk.get('type') == 'table'
                
                # Extract and normalize text to strip orthographic noise
                raw_content: str = chunk.get('content', '')
                normalized_content: str = self._normalize_text(raw_content, is_table=is_table)
                chunk['content'] = normalized_content
                
                # Determine document type (Internal vs External/Legal) to assign appropriate chunk ID format
                is_internal = chunk.get('metadata', {}).get('type') == 'embedding_semantic_block'
                doc_id: str = chunk.get('doc_id', 'unknown_doc')
                
                if is_internal:
                    chunk['chunk_id'] = f"{doc_id}_sec_{chunk.get('chunk_index', 0)}"
                else:
                    # Extract the legal article number ("45", "12", or "0" if not detected)
                    article_num: str = self.article_parser.extract_article_id(normalized_content)
                    chunk['chunk_id'] = f"{doc_id}_art_{article_num}"
                
                # Regenerate Hash based on the pristine Normalized text
                chunk['chunk_hash'] = self._generate_hash(normalized_content)

            print("[+] Layer 2 Complete: Hashes and Clean Legal IDs are now consistent.")
            return chunks       

    def _normalize_text(self, text: str, is_table: bool = False) -> str:
        if not text: return ""
            
        # Standardize whitespace
        if is_table:
            text = re.sub(r'[ \t]+', ' ', text)
        else:
            text = re.sub(r'\s+', ' ', text)
        
        # Arabic Normalization (Standardizing Alef and Ta-Marbuta)
        text = re.sub(r'[إأآ]', 'ا', text)
        text = re.sub(r'ة\b', 'ه', text)
        text = re.sub(r'[يى]\b', 'ي', text)
        
        return text.strip()

    def _generate_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode('utf-8')).hexdigest()