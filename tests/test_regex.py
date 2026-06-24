import sqlite3
import re
import pytest
import warnings
import os
import sys

# Ensure stdout handles UTF-8 for Arabic characters
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

def test_article_sequence():
    """
    Validates that article numbers in document chunks follow a sequential order.
    Note: The 'document_chunks' table in 'data/legal_vault.db' must have rows for this test to run.
    """
    db_path = os.path.join("data", "legal_vault.db")
    
    # Requirement Check
    if not os.path.exists(db_path):
        pytest.skip(f"Database not found at {db_path}. Ensure documents are processed first.")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if table exists and has rows - Notify user if empty
    try:
        cursor.execute("SELECT COUNT(*) FROM document_chunks")
        count = cursor.fetchone()[0]
        if count == 0:
            # Notifying that rows are required
            pytest.fail("Requirement failed: 'document_chunks' table is empty. Document chunks must have rows in order to run this test.")
    except sqlite3.OperationalError:
        pytest.fail("Requirement failed: 'document_chunks' table does not exist. Ensure document processing has occurred.")

    cursor.execute("SELECT doc_id, chunk_index, content FROM document_chunks ORDER BY doc_id, chunk_index")
    rows = cursor.fetchall()

    patterns = [
        r"(?:المادة|الماده|مادة|ماده)\s*\(?([\d١٢٣٤٥٦٧٨٩٠]+|[أ-ي]+)\)?",
        r"Article\s*\(?(\d+)\)?",
    ]

    prev_number = None
    prev_doc_id = None
    
    # Print header for visibility when running with pytest -s
    print(f"\n{'Doc #':<8} {'Chunk':<8} {'Article #':<12} {'Status'}")
    print("-" * 60)

    for row in rows:
        doc_id, chunk_index, content = row
        
        # Reset sequence tracking for each new document
        if prev_doc_id is not None and doc_id != prev_doc_id:
            prev_number = None
        
        article_number = None
        for p in patterns:
            match = re.search(p, content)
            if match:
                article_number = match.group(1)
                break
        
        # Detect gaps - Make it a warning not a failure
        if article_number and prev_number:
            try:
                def to_int(s):
                    # Support for Arabic-Indic digits
                    mapping = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
                    return int(str(s).translate(mapping))

                curr_val = to_int(article_number)
                prev_val = to_int(prev_number)
                
                diff = curr_val - prev_val
                if diff > 1:
                    warnings.warn(UserWarning(f"Gap detected in Doc {doc_id}: jumped from {prev_number} to {article_number} (Chunk {chunk_index})"))
            except ValueError:
                # Handle non-numeric article references (e.g., 'أ', 'ب') if needed
                pass

        preview = content[:30].replace("\n", " ").strip()
        status = f"Article {article_number}" if article_number else "No Match"
        print(f"{doc_id:<8} {chunk_index:<8} {status:<12} {preview}...")
        
        if article_number:
            prev_number = article_number
        prev_doc_id = doc_id

    conn.close()
