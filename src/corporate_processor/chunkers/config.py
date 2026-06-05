import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """
    LLM Configuration for the Corporate Chunker.
    """
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/api/generate")
    LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "qwen2.5:7b")
    LLM_TEMPERATURE = 0.0
