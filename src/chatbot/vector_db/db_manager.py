import os
from langchain_classic.indexes import SQLRecordManager, index
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_chroma import Chroma

from chatbot.config import RECORD_MANAGER_DB_URL

class IncrementalVectorManager:
    def __init__(
        self, 
        collection_name: str, 
        embedding_model: Embeddings,
        persist_directory: str,  # FIXED: Removed the hardcoded default trap!
        record_db_url: str = RECORD_MANAGER_DB_URL
    ):
        """
        Initializes a specialized Chroma VectorStore instance paired with a 
        SQLRecordManager to track and process incremental data updates safely.
        
        Args:
            collection_name: Unique name for the Chroma collection (e.g., "internal_docs").
            embedding_model: An implementation of LangChain's Embeddings interface.
            persist_directory: Absolute local path where Chroma will save its vector data.
            record_db_url: SQLite connection string tracking chunk hashes and states.
        """
        self.collection_name = collection_name
        
        # 1. Initialize Chroma VectorStore for this specific collection
        self.vector_store = Chroma(
            collection_name=collection_name,
            embedding_function=embedding_model,
            persist_directory=persist_directory
        )
        
        # 2. Formulate a unique namespace for the SQLRecordManager based on collection
        self.namespace = f"chroma/{collection_name}"
        
        # 3. Setup the SQLRecordManager to prevent duplicate embeddings
        self.record_manager = SQLRecordManager(
            namespace=self.namespace,
            db_url=record_db_url
        )
        
        # Create schema tables if they don't exist yet
        self.record_manager.create_schema()

    def update_database(self, documents: list[Document]) -> dict:
        """
        Indexes incoming documents into Chroma using incremental cleanup.
        Ensures that mutated or deleted source documents are updated correctly.
        """
        if not documents:
            return {"num_added": 0, "num_updated": 0, "num_skipped": 0, "num_deleted": 0}

        # Verification safeguard for incremental tracking
        for doc in documents:
            if "source" not in doc.metadata:
                raise ValueError(
                    f"Document missing 'source' key in metadata. "
                    f"Incremental indexing requires a tracking source. Metadata: {doc.metadata}"
                )

        print(f"[{self.collection_name}] Executing incremental synchronization...")
        
        indexing_result = index(
            docs_source=documents,
            record_manager=self.record_manager,
            vector_store=self.vector_store,
            cleanup="incremental",
            source_id_key="source"
        )
        
        print(f"[{self.collection_name}] Synchronization complete: {indexing_result}")
        return indexing_result

    def as_retriever(self, search_kwargs: dict = None):
        """
        Exposes the active Chroma collection as a retriever object for the router.
        """
        kwargs = search_kwargs or {"k": 4}
        return self.vector_store.as_retriever(search_kwargs=kwargs)