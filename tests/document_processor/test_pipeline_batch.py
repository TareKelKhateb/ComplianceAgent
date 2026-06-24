import pytest
from src.document_processor.pipeline_manager import OCRPipeline
from src.metadata_manager.metadata_store import MetadataStore

@pytest.fixture
def store():
    """Provides a MetadataStore instance."""
    return MetadataStore()

@pytest.fixture
def pipeline(store):
    """Provides an OCRPipeline instance."""
    return OCRPipeline(metadata_store=store)

def test_run_batch_processes_successfully(pipeline):
    """
    Tests the Producer-Consumer architecture using the run_batch method.
    Ensures that parallel OCR and sequential DB insertions don't raise exceptions.
    """
    # 1. Define a fake batch of documents 
    # (These IDs and paths are pulled directly from legal_vault.db)
    docs_to_process = [
        {
            "id": 1,
            "file_path": r"./local_download\CBE_Law_No._194_of_2020.pdf"
        },
        {
            "id": 2,
            "file_path": r"./local_download\CBE_Statute.pdf"
        }
    ]
    
    # 2. Run the batch using 2 parallel workers
    try:
        pipeline.run_batch(documents=docs_to_process, max_workers=2)
    except Exception as exc:
        pytest.fail(f"pipeline.run_batch() raised an exception: {exc}")
        
    # Note: In a true CI environment, you would want to mock the DB 
    # or point the MetadataStore to an in-memory SQLite DB, and assert
    # that `store.get_ocr_status(1) == 'completed'`.
