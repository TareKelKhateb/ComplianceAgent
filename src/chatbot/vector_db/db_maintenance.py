import os
from uuid import uuid4
from typing import List, Literal
from langchain_core.documents import Document
from langchain_classic.indexes import index 

from chatbot.config import get_embeddings, STORAGE_DIR
from chatbot.vector_db.db_manager import IncrementalVectorManager

# FIXED: Updated Literal to match our new Compliance databases
def get_db_manager(category: Literal["internal_policies", "external_regulations"]) -> IncrementalVectorManager:
    """Helper to initialize the correct database manager dynamically."""
    embeddings = get_embeddings()
    return IncrementalVectorManager(
        collection_name=category,
        embedding_model=embeddings,
        persist_directory=str(STORAGE_DIR / category)
    )

# FIXED: Updated Literal
def add_or_update_documents(
    category: Literal["internal_policies", "external_regulations"], 
    documents: List[Document]
):
    """
    Adds new documents or updates existing ones if their content changes.
    """
    print(f"\n--- [Indexing] Ingesting/Updating {len(documents)} docs into {category} ---")
    
    manager = get_db_manager(category)
    
    # Ensure every document has a source tracking ID in metadata
    for doc in documents:
        if "source" not in doc.metadata:
            doc.metadata["source"] = f"manual_upload_{uuid4().hex[:8]}"
            
    summary = index(
        docs_source=documents,
        record_manager=manager.record_manager,
        vector_store=manager.vector_store,
        cleanup="incremental",
        source_id_key="source"
    )
    
    print(f"Result Summary: {summary}")
    return summary

# FIXED: Updated Literal
def delete_source_documents(
    category: Literal["internal_policies", "external_regulations"], 
    source_ids: List[str]
):
    """
    Deletes documents from the vector store matching specific source tracking IDs.
    """
    print(f"\n--- [Deletion] Removing source IDs {source_ids} from {category} ---")
    manager = get_db_manager(category)
    
    summary = index(
        docs_source=[],
        record_manager=manager.record_manager,
        vector_store=manager.vector_store,
        cleanup="incremental",
        source_id_key="source",
        source_ids=source_ids
    )
    print(f"Deletion Summary: {summary}")
    return summary