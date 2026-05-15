import hashlib
import re
from typing import List, Dict, Any

class SemanticHasher:
    """
    Layer 2: Handles Arabic-specific text normalization and semantic hashing.
    Ensures that orthographic variations (like Alef shapes) don't trigger false diffs.
    """

    def __init__(self) -> None:
        pass

    def process_layer_two(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Refines chunks by normalizing content and regenerating hashes before Diff Analysis.
        """
        print(f"[*] Layer 2: Normalizing {len(chunks)} chunks...")
        
        for chunk in chunks:
            # 1. Identity Check (Table vs Text)
            # Ensure 'type' was saved in Layer 1
            is_table: bool = chunk.get('type') == 'table'
            
            # 2. Normalize Content (The Arabic Logic)
            raw_content = chunk.get('content', '')
            normalized_content = self._normalize_text(raw_content, is_table=is_table)
            
            # 3. Update Chunk
            chunk['content'] = normalized_content
            
            # 4. Regenerate Hash based on Normalized text
            # This is critical! The DiffEngine will use this hash.
            chunk['chunk_hash'] = self._generate_hash(normalized_content)

        print("[+] Layer 2 Complete: Hashes are now semantically consistent.")
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