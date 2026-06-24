import hashlib
from typing import List, Dict, Any

class DiffEngine:
    """
    Layer 3: Comparison Engine for version control.
    Analyzes differences between the existing active chunks and the newly processed ones.
    """

    def __init__(self) -> None:
        """Initializes the Diff Engine."""
        pass

    def compare_documents(self, base_chunks: List[Dict[str, Any]], target_chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Compares two versions of a document to identify changes, movements, and new content.

        Args:
            base_chunks (List[Dict[str, Any]]): The current active chunks in the database (Previous Version).
            target_chunks (List[Dict[str, Any]]): The newly generated and normalized chunks (New Version).

        Returns:
            List[Dict[str, Any]]: The target chunks updated with change_type and historical metadata.
        """
        # Map base chunks by hash for fast content-based lookup (detects 'moved' or 'unchanged')
        base_hashes: Dict[str, Dict[str, Any]] = {c['chunk_hash']: c for c in base_chunks}
        
        # Map base chunks by index for position-based lookup (detects 'modified')
        base_by_idx: Dict[int, Dict[str, Any]] = {c['chunk_index']: c for c in base_chunks}
        
        matched_base_hashes = set()
        final_report: List[Dict[str, Any]] = []

        for t_chunk in target_chunks:
            t_hash = t_chunk['chunk_hash']
            t_idx = t_chunk['chunk_index']

            # Case 1: Content found in the previous version
            if t_hash in base_hashes:
                b_match = base_hashes[t_hash]
                matched_base_hashes.add(t_hash)
                
                # Carry over version and previous metadata
                t_chunk['version'] = b_match.get('version', 1)
                
                if b_match['chunk_index'] == t_idx:
                    t_chunk['change_type'] = 'unchanged'
                else:
                    # Content is identical but position (index/page) has shifted
                    t_chunk['change_type'] = 'moved'
                    t_chunk['old_metadata'] = {
                        "prev_index": b_match['chunk_index'],
                        "prev_page": b_match['page_number']
                    }
            
            # Case 2: Content is either modified or entirely new
            else:
                b_at_idx = base_by_idx.get(t_idx)
                
                if b_at_idx:
                    # Same position but different content -> Modification
                    t_chunk['change_type'] = 'modified'
                    t_chunk['old_content'] = b_at_idx['content']
                    t_chunk['old_hash'] = b_at_idx['chunk_hash']
                    t_chunk['version'] = b_at_idx.get('version', 0) + 1
                else:
                    # Position didn't exist before -> Addition
                    t_chunk['change_type'] = 'added'
                    t_chunk['version'] = 1 # Start at version 1 for new provisions

            final_report.append(t_chunk)

        # Note: Deleted chunks are handled by the MetadataStore's archive_old_chunks method,
        # which sets is_active=0 for everything not in the new version.
        
        return final_report

    def get_similarity_score(self, base_chunks: List[Dict[str, Any]], target_chunks: List[Dict[str, Any]]) -> float:
        """
        Calculates the Jaccard Similarity score between two versions based on unique hashes.
        """
        if not base_chunks or not target_chunks:
            return 0.0

        b_hashes = {c['chunk_hash'] for c in base_chunks}
        t_hashes = {c['chunk_hash'] for c in target_chunks}
        
        intersection = b_hashes.intersection(t_hashes)
        union = b_hashes.union(t_hashes)
        
        return round((len(intersection) / len(union)) * 100, 2)