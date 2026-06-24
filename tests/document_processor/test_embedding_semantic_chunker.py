import pytest
import numpy as np
from unittest.mock import MagicMock
from src.document_processor.chunkers.embedding_semantic_chunker import EmbeddingSemanticChunker

DOC_ID = "test_doc_123"

@pytest.fixture(autouse=True)
def clean_chunker_singleton():
    """Ensure the singleton model is reset before/after each test."""
    EmbeddingSemanticChunker._model = None
    EmbeddingSemanticChunker._model_name_loaded = None
    yield
    EmbeddingSemanticChunker._model = None
    EmbeddingSemanticChunker._model_name_loaded = None

def test_embedding_semantic_chunker_basic():
    # Arrange
    chunker = EmbeddingSemanticChunker(
        similarity_threshold=0.5,
        max_chunk_words=100,
        min_chunk_words=5
    )
    
    # Mock model
    mock_model = MagicMock()
    # We have 3 sentences:
    # 1. "This is the first sentence."
    # 2. "It is very similar to the first."
    # 3. "Completely different topic here now."
    # Let's return embeddings such that:
    # - Sim between 1 and 2 is high (e.g. cosine sim ~ 0.9)
    # - Sim between 2 and 3 is low (e.g. cosine sim ~ 0.1)
    
    v1 = np.array([1.0, 0.0])
    v2 = np.array([0.9, 0.1])
    v3 = np.array([0.0, 1.0])
    
    mock_model.encode.return_value = np.array([v1, v2, v3])
    EmbeddingSemanticChunker._model = mock_model
    EmbeddingSemanticChunker._model_name_loaded = chunker.model_name
    
    text = "This is the first sentence. It is very similar to the first. Completely different topic here now."
    
    # Act
    chunks = chunker.create_chunks(text, DOC_ID)
    
    # Assert
    # Word counts:
    # "This is the first sentence. It is very similar to the first." -> 13 words (>= 5 min)
    # "Completely different topic here now." -> 5 words (>= 5 min)
    # So we should get 2 chunks.
    assert len(chunks) == 2
    assert chunks[0]["doc_id"] == DOC_ID
    assert chunks[0]["chunk_index"] == 0
    assert "first sentence" in chunks[0]["content"]
    assert "similar to the first" in chunks[0]["content"]
    assert "Completely different topic" in chunks[1]["content"]

def test_embedding_semantic_chunker_force_split():
    # Arrange
    chunker = EmbeddingSemanticChunker(
        similarity_threshold=0.95, # high threshold to split everything
        max_chunk_words=10, # low max words
        min_chunk_words=1
    )
    
    mock_model = MagicMock()
    # 3 sentences, make them orthogonal so similarity is 0.0 (< 0.95)
    v1 = np.array([1.0, 0.0, 0.0])
    v2 = np.array([0.0, 1.0, 0.0])
    v3 = np.array([0.0, 0.0, 1.0])
    mock_model.encode.return_value = np.array([v1, v2, v3])
    EmbeddingSemanticChunker._model = mock_model
    EmbeddingSemanticChunker._model_name_loaded = chunker.model_name
    
    text = "This is sentence one. This is sentence two. This is sentence three."
    
    # Act
    chunks = chunker.create_chunks(text, DOC_ID)
    
    # Assert
    # Since they are force split or threshold is too high, each sentence gets its own chunk
    assert len(chunks) == 3
    assert chunks[0]["content"] == "This is sentence one."
    assert chunks[1]["content"] == "This is sentence two."
    assert chunks[2]["content"] == "This is sentence three."

def test_embedding_semantic_chunker_empty_input():
    chunker = EmbeddingSemanticChunker()
    with pytest.raises(ValueError, match="full_text must be a non-empty string"):
        chunker.create_chunks("", DOC_ID)
