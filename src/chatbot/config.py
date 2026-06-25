import os
import pathlib
from typing import Literal
from langchain_core.language_models import BaseChatModel
from langchain_core.embeddings import Embeddings

# FIXED: Use find_dotenv to automatically traverse up the directory tree to find the .env file
from dotenv import load_dotenv, find_dotenv

# This is now 100% bulletproof regardless of where the terminal command is run from
load_dotenv(find_dotenv())

# ==========================================
# ABSOLUTE STORAGE PATHS
# ==========================================
# This ensures databases are always created inside src/chatbot/storage
CHATBOT_DIR = pathlib.Path(__file__).parent
STORAGE_DIR = CHATBOT_DIR / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

RECORD_MANAGER_DB_URL = f"sqlite:///{STORAGE_DIR / 'record_manager_cache.sql'}"

# ==========================================
# CENTRAL CONFIGURATION SETUP (FREE CLOUD APIs)
# ==========================================

# 1. Groq LLM setup
LLM_PROVIDER: Literal["google", "groq"] = "groq"
LLM_MODEL_NAME: str = "llama-3.1-8b-instant"  # Updated to the currently supported model

# 2. Google Embeddings setup
EMBEDDING_PROVIDER: Literal["google"] = "google"
EMBEDDING_MODEL_NAME: str = "gemini-embedding-001"

def get_llm(temperature: float = 0.0) -> BaseChatModel:
    """
    Factory function returning the selected free API-based LLM.
    """
    if LLM_PROVIDER == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=LLM_MODEL_NAME, 
            temperature=temperature,
            google_api_key=os.getenv("GOOGLE_API_KEY")
        )
        
    elif LLM_PROVIDER == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=LLM_MODEL_NAME, 
            temperature=temperature,
            groq_api_key=os.getenv("GROQ_API_KEY")
        )
        
    else:
        raise ValueError(f"Unsupported free API provider: {LLM_PROVIDER}")


def get_embeddings() -> Embeddings:
    """
    Factory function returning the selected free API-based embedding model.
    """
    if EMBEDDING_PROVIDER == "google":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        return GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL_NAME,
            google_api_key=os.getenv("GOOGLE_API_KEY")
        )
    else:
        raise ValueError(f"Unsupported embedding provider: {EMBEDDING_PROVIDER}")